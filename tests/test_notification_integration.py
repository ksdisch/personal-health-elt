"""End-to-end integration test for the notification pipeline.

Plants a sequence of `mart_recovery_state` rows, runs
`notify_on_state_change`, and asserts:

  1.  A red-transition sequence (yesterday=neutral, today=strained)
      fires exactly one notification.
  2.  A second invocation on the same day fires zero (dedup via
      raw.notification_log's PK).
  3.  The log row records the right metadata (rule_name, day,
      severity, transport).
  4.  A consecutive(3) rule fires on day 3 of a fresh strained streak.

Sentinel values:
  - test rule names are prefixed with `_test_` so cleanup is surgical
  - planted mart days use year 2099 to never collide with real export
    data the fixture preserves

The test uses `raw_test_engine` for the file-ledger safety guarantee
(even though notifications don't write file_inventory rows, the fixture
is the established pattern). Cleanup of planted mart rows + log rows
happens in try/finally — the fixture doesn't clean those tables.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.notifications.notify import notify_on_state_change

# Year 2099 is far enough out that no Apple Health export could ever
# overlap. The fixture preserves the user's real data; this guarantees
# our planted rows are surgically removable on cleanup.
_TEST_BASE_DAY = date(2099, 4, 1)
_TEST_RULE_PREFIX = "_test_"

# Ensure the mart-shaped table exists even when dbt build hasn't run.
# Schema + columns mirror the real mart's contract; dbt's CREATE OR
# REPLACE TABLE will fully replace this on the next build, so leaving
# it in place is safe.
_BOOTSTRAP_MART_SQL = """
CREATE SCHEMA IF NOT EXISTS analytics_marts;

CREATE TABLE IF NOT EXISTS analytics_marts.mart_recovery_state (
    day                  DATE,
    is_today             BOOLEAN,
    rhr_bpm              DOUBLE PRECISION,
    hrv_ms               DOUBLE PRECISION,
    hrv_ms_7d_prior_avg  DOUBLE PRECISION,
    zone_2_min_today     DOUBLE PRECISION,
    zone_2_min_7d        DOUBLE PRECISION,
    strength_sessions_7d INTEGER,
    training_load_today  DOUBLE PRECISION,
    acute_load_7d        DOUBLE PRECISION,
    chronic_load_28d     DOUBLE PRECISION,
    acwr                 DOUBLE PRECISION,
    days_since_last_workout INTEGER,
    recovery_signal      TEXT
);
"""


def _plant_mart_rows(engine: Engine, base_day: date, signals: list[str]) -> list[date]:
    """Insert one row per signal, oldest -> newest. Returns the list of days planted."""
    days: list[date] = []
    with engine.begin() as conn:
        for i, sig in enumerate(signals):
            d = base_day + timedelta(days=i)
            days.append(d)
            conn.execute(
                text(
                    """
                    INSERT INTO analytics_marts.mart_recovery_state
                        (day, recovery_signal, hrv_ms, acwr, rhr_bpm)
                    VALUES (:day, :sig, :hrv, :acwr, :rhr)
                    """
                ),
                # Sentinel numeric values so message templates render
                # without surprises if a test asserts on them.
                {"day": d, "sig": sig, "hrv": 42.0, "acwr": 1.67, "rhr": 58.0},
            )
    return days


def _cleanup(engine: Engine, planted_days: list[date]) -> None:
    """Best-effort removal of test-introduced rows.

    Always runs (even on test failure). Touches only:
      - rows in mart_recovery_state at the planted dates
      - rows in notification_log whose rule_name starts with the test prefix

    Leaves any pre-existing data untouched.
    """
    with engine.begin() as conn:
        if planted_days:
            conn.execute(
                text("DELETE FROM analytics_marts.mart_recovery_state WHERE day = ANY(:days)"),
                {"days": planted_days},
            )
        conn.execute(
            text("DELETE FROM raw.notification_log WHERE rule_name LIKE :prefix"),
            {"prefix": f"{_TEST_RULE_PREFIX}%"},
        )


@pytest.fixture
def mart_bootstrapped(raw_test_engine: Engine) -> Iterator[Engine]:
    """Engine with analytics_marts.mart_recovery_state guaranteed to exist."""
    engine = raw_test_engine
    with engine.begin() as conn:
        conn.execute(text(_BOOTSTRAP_MART_SQL))
    yield engine


def _write_transition_rule(tmp_path: Path) -> Path:
    """One transition_to:strained rule with the test-sentinel name."""
    path = tmp_path / "rules.yaml"
    path.write_text(
        f"""
- name: {_TEST_RULE_PREFIX}red_transition
  kind: transition_to
  signal: strained
  severity: warning
  message_template: "flipped to {{signal}} on {{day}} (HRV {{hrv_ms}}ms, ACWR {{acwr}})"
""",
        encoding="utf-8",
    )
    return path


def _write_consecutive_rule(tmp_path: Path, days: int = 3) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(
        f"""
- name: {_TEST_RULE_PREFIX}consecutive_strained
  kind: consecutive
  signal: strained
  days: {days}
  severity: critical
  message_template: "{days}-day strained streak ({{day}})"
""",
        encoding="utf-8",
    )
    return path


def test_red_transition_fires_exactly_once_then_dedups(
    mart_bootstrapped: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """neutral, neutral, STRAINED (today) → one fire on run 1, zero on run 2."""
    engine = mart_bootstrapped
    planted: list[date] = []
    try:
        planted = _plant_mart_rows(engine, _TEST_BASE_DAY, ["neutral", "neutral", "strained"])
        today = planted[-1]
        rules_path = _write_transition_rule(tmp_path)

        # Run 1: expect 1 sent, 0 deduped.
        first = notify_on_state_change(
            engine=engine,
            rules_path=rules_path,
            today=today,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert first.skipped is False
        assert first.notifications_sent == 1, f"expected 1 fire, got {first}"
        assert first.notifications_deduped == 0
        assert first.errors == []

        # stdout signal landed
        out = capsys.readouterr().out
        assert f"{_TEST_RULE_PREFIX}red_transition" in out
        assert "strained" in out

        # Log row exists with expected metadata.
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT severity, signal, transport FROM raw.notification_log "
                    "WHERE rule_name = :rn AND day = :d"
                ),
                {"rn": f"{_TEST_RULE_PREFIX}red_transition", "d": today},
            ).one()
        assert row.severity == "warning"
        assert row.signal == "strained"
        assert row.transport == "dry_run"

        # Run 2 on the same day: expect 0 sent, 1 deduped.
        second = notify_on_state_change(
            engine=engine,
            rules_path=rules_path,
            today=today,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert second.skipped is False
        assert second.notifications_sent == 0
        assert second.notifications_deduped == 1
        assert second.errors == []
    finally:
        _cleanup(engine, planted)


def test_no_transition_no_fire(mart_bootstrapped: Engine, tmp_path: Path) -> None:
    """strained, strained, strained (today) → already in state, zero fires."""
    engine = mart_bootstrapped
    planted: list[date] = []
    try:
        planted = _plant_mart_rows(engine, _TEST_BASE_DAY, ["strained", "strained", "strained"])
        today = planted[-1]
        rules_path = _write_transition_rule(tmp_path)

        result = notify_on_state_change(
            engine=engine,
            rules_path=rules_path,
            today=today,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert result.notifications_sent == 0
        assert result.notifications_deduped == 0
        # rows_read counts only the window — 3 planted rows fall inside the
        # default lookback (7 days), so all 3 are read.
        assert result.rows_read >= 3
    finally:
        _cleanup(engine, planted)


def test_consecutive_streak_fires_only_on_threshold_day(
    mart_bootstrapped: Engine, tmp_path: Path
) -> None:
    """neutral, strained, strained, strained (today) → consecutive(3) fires."""
    engine = mart_bootstrapped
    planted: list[date] = []
    try:
        planted = _plant_mart_rows(
            engine, _TEST_BASE_DAY, ["neutral", "strained", "strained", "strained"]
        )
        today = planted[-1]
        rules_path = _write_consecutive_rule(tmp_path, days=3)

        first = notify_on_state_change(
            engine=engine,
            rules_path=rules_path,
            today=today,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert first.notifications_sent == 1
        assert first.notifications_deduped == 0

        # A day later: streak extends to 4 with a 4th planted row.
        # The consecutive(3) rule should NOT re-fire — the streak began
        # on day 2 of the window, day 3 already fired.
        with engine.begin() as conn:
            extra_day = today + timedelta(days=1)
            conn.execute(
                text(
                    "INSERT INTO analytics_marts.mart_recovery_state "
                    "(day, recovery_signal, hrv_ms, acwr, rhr_bpm) "
                    "VALUES (:d, 'strained', 40.0, 1.7, 60.0)"
                ),
                {"d": extra_day},
            )
        planted.append(extra_day)

        next_day = notify_on_state_change(
            engine=engine,
            rules_path=rules_path,
            today=extra_day,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert next_day.notifications_sent == 0, (
            "consecutive(3) must not re-fire on day 4 of an extended streak"
        )
        assert next_day.notifications_deduped == 0
    finally:
        _cleanup(engine, planted)


def test_skipped_when_rules_file_missing(mart_bootstrapped: Engine, tmp_path: Path) -> None:
    """No rules file = skipped=True, no errors."""
    engine = mart_bootstrapped
    planted: list[date] = []
    try:
        planted = _plant_mart_rows(engine, _TEST_BASE_DAY, ["neutral", "strained"])
        today = planted[-1]
        missing = tmp_path / "does_not_exist.yaml"

        result = notify_on_state_change(
            engine=engine,
            rules_path=missing,
            today=today,
            pushover_token=None,
            pushover_user=None,
            dry_run=True,
        )
        assert result.skipped is True
        assert result.notifications_sent == 0
        assert result.errors == []
    finally:
        _cleanup(engine, planted)


def test_skipped_when_mart_is_empty(mart_bootstrapped: Engine, tmp_path: Path) -> None:
    """Mart table exists but no rows in the lookback window → skipped=True."""
    engine = mart_bootstrapped
    rules_path = _write_transition_rule(tmp_path)
    # Use a `today` far from any planted data so the window comes back empty.
    far_future_today = date(2099, 12, 31)

    result = notify_on_state_change(
        engine=engine,
        rules_path=rules_path,
        today=far_future_today,
        pushover_token=None,
        pushover_user=None,
        dry_run=True,
    )
    assert result.skipped is True
    assert result.rows_read == 0
    assert result.rules_evaluated == 1
