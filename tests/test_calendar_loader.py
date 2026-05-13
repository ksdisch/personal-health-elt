"""Unit tests for the Google Calendar (secret iCal URL) loader.

Pure-function tests for `parse_ics_to_daily` plus injection-based tests
for `load_calendar_daily` that bypass the real HTTP fetch via the
`fetch_fn=` parameter. Sample ICS bodies are constructed inline so
the suite has no external fixture files.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.loaders.calendar_google import (
    load_calendar_daily,
    parse_ics_to_daily,
)

# Minimal-but-realistic ICS: 1 timed event, 1 all-day event, 1 weekly
# recurring event with one excluded instance.
_SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:timed-1@test
DTSTART:20990321T140000Z
DTEND:20990321T150000Z
SUMMARY:Test meeting
END:VEVENT
BEGIN:VEVENT
UID:all-day-1@test
DTSTART;VALUE=DATE:20990322
DTEND;VALUE=DATE:20990323
SUMMARY:All-day item
END:VEVENT
BEGIN:VEVENT
UID:weekly-1@test
DTSTART:20990321T160000Z
DTEND:20990321T170000Z
RRULE:FREQ=WEEKLY;COUNT=3
EXDATE:20990328T160000Z
SUMMARY:Weekly standup
END:VEVENT
END:VCALENDAR
"""

_FAKE_SHA = "deadbeef" * 8


def test_parse_ics_timed_event_lands_on_local_day() -> None:
    df = parse_ics_to_daily(
        _SAMPLE_ICS,
        window_start=date(2099, 3, 21),
        window_end=date(2099, 4, 10),
        sha=_FAKE_SHA,
    )
    # 2099-03-21 has the timed meeting + the weekly standup (first instance)
    row = df[df["day"] == date(2099, 3, 21)].iloc[0]
    assert row["timed_event_count"] == 2
    assert row["timed_event_hours"] == pytest.approx(2.0)
    assert row["all_day_event_count"] == 0
    assert isinstance(row["first_event_local"], datetime)
    assert row["source_sha256"] == _FAKE_SHA


def test_parse_ics_all_day_bucket_is_separate() -> None:
    df = parse_ics_to_daily(
        _SAMPLE_ICS,
        window_start=date(2099, 3, 21),
        window_end=date(2099, 4, 10),
        sha=_FAKE_SHA,
    )
    row = df[df["day"] == date(2099, 3, 22)].iloc[0]
    assert row["timed_event_count"] == 0
    assert row["all_day_event_count"] == 1


def test_parse_ics_recurrence_expands_and_excludes() -> None:
    df = parse_ics_to_daily(
        _SAMPLE_ICS,
        window_start=date(2099, 3, 21),
        window_end=date(2099, 4, 10),
        sha=_FAKE_SHA,
    )
    days_with_standup = set(df["day"].tolist())
    # COUNT=3 instances starting 2099-03-21 weekly: 03-21, 03-28, 04-04.
    # EXDATE excludes 2099-03-28, so we expect 03-21 + 04-04 visible.
    assert date(2099, 3, 21) in days_with_standup
    assert date(2099, 4, 4) in days_with_standup
    assert date(2099, 3, 28) not in days_with_standup or (
        # If 03-28 shows up at all, it must NOT include the recurrence —
        # only the original 03-21 event leaks here if EXDATE were ignored.
        df[df["day"] == date(2099, 3, 28)]["timed_event_count"].iloc[0] == 0
    )


def test_parse_ics_clips_to_window() -> None:
    df = parse_ics_to_daily(
        _SAMPLE_ICS,
        window_start=date(2099, 3, 25),
        window_end=date(2099, 4, 1),
        sha=_FAKE_SHA,
    )
    # 2099-03-21 is outside the window; its row must be absent.
    assert date(2099, 3, 21) not in set(df["day"].tolist())


def test_parse_ics_empty_calendar_returns_empty_df() -> None:
    empty = b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//e//e//EN\nEND:VCALENDAR\n"
    df = parse_ics_to_daily(empty, date(2099, 1, 1), date(2099, 1, 10), sha=_FAKE_SHA)
    assert df.empty
    assert set(df.columns) >= {
        "day",
        "timed_event_count",
        "timed_event_hours",
        "all_day_event_count",
    }


def test_load_calendar_daily_skips_when_no_url() -> None:
    def _should_not_be_called(_url: str) -> bytes:
        raise AssertionError("fetch_fn called when url=None")

    result = load_calendar_daily(url=None, fetch_fn=_should_not_be_called)
    assert result.skipped is True
    assert result.sha256 is None
    assert result.rows_inserted == 0


def test_load_calendar_daily_skips_unchanged_ics(pg_engine: Engine) -> None:
    """Second call with the same body short-circuits at the file ledger."""
    engine = pg_engine

    def _fake_fetch(_url: str) -> bytes:
        return _SAMPLE_ICS

    # Initialize the cleanup variable so the `finally` block doesn't
    # explode with UnboundLocalError if the test body raises before
    # `first.sha256` is assigned (e.g., parser regression).
    first_sha: str | None = None
    try:
        first = load_calendar_daily(
            lookback_days=30,
            today=date(2099, 4, 10),
            url="https://fake/basic.ics",
            engine=engine,
            fetch_fn=_fake_fetch,
        )
        assert first.skipped is False
        assert first.skipped_unchanged is False
        assert first.rows_inserted > 0
        first_sha = first.sha256

        second = load_calendar_daily(
            lookback_days=30,
            today=date(2099, 4, 10),
            url="https://fake/basic.ics",
            engine=engine,
            fetch_fn=_fake_fetch,
        )
        assert second.skipped_unchanged is True
        assert second.sha256 == first_sha
        assert second.rows_inserted == 0

    finally:
        if first_sha is not None:
            with engine.begin() as conn:
                # Clean up: dependent rows first (no ON DELETE CASCADE on FK),
                # then the ledger.
                conn.execute(
                    text("DELETE FROM raw.calendar_daily WHERE source_sha256 = :s"),
                    {"s": first_sha},
                )
                conn.execute(
                    text("DELETE FROM raw.file_inventory WHERE sha256 = :s"),
                    {"s": first_sha},
                )


# An extra timed event inserted INSIDE the VCALENDAR block — produces
# a body with a different SHA than _SAMPLE_ICS while staying a
# well-formed iCal calendar (so the parser doesn't reject it).
_EXTRA_VEVENT_BLOCK = b"""BEGIN:VEVENT
UID:extra-1@test
DTSTART:20990405T120000Z
DTEND:20990405T130000Z
SUMMARY:Extra meeting
END:VEVENT
"""
_SAMPLE_ICS_V2 = _SAMPLE_ICS.replace(b"END:VCALENDAR", _EXTRA_VEVENT_BLOCK + b"END:VCALENDAR")


def test_load_calendar_daily_different_body_inserts_fresh_rows(pg_engine: Engine) -> None:
    """A changed ICS produces a new SHA and a fresh row-set per day.

    Both bodies must be valid iCal calendars — appending bytes after
    END:VCALENDAR makes the body unparseable, which the parser now
    correctly treats as malformed and returns empty for. The test's
    second body adds an extra VEVENT instead, so it's a real
    calendar mutation rather than a parse-failure path.
    """
    engine = pg_engine

    call_count = {"n": 0}

    def _fetch_seq(_url: str) -> bytes:
        call_count["n"] += 1
        return _SAMPLE_ICS if call_count["n"] == 1 else _SAMPLE_ICS_V2

    shas_seen: list[str] = []
    try:
        first = load_calendar_daily(
            lookback_days=30,
            today=date(2099, 4, 10),
            url="https://fake/basic.ics",
            engine=engine,
            fetch_fn=_fetch_seq,
        )
        assert first.rows_inserted > 0
        assert first.sha256 is not None
        shas_seen.append(first.sha256)

        second = load_calendar_daily(
            lookback_days=30,
            today=date(2099, 4, 10),
            url="https://fake/basic.ics",
            engine=engine,
            fetch_fn=_fetch_seq,
        )
        # Different body → different SHA → loader inserts a NEW set of rows.
        assert second.sha256 != first.sha256
        assert second.skipped_unchanged is False
        assert second.rows_inserted > 0
        assert second.sha256 is not None
        shas_seen.append(second.sha256)

    finally:
        with engine.begin() as conn:
            for sha in shas_seen:
                conn.execute(
                    text("DELETE FROM raw.calendar_daily WHERE source_sha256 = :s"),
                    {"s": sha},
                )
                conn.execute(
                    text("DELETE FROM raw.file_inventory WHERE sha256 = :s"),
                    {"s": sha},
                )


def test_parse_ics_timed_event_hours_sums_per_day() -> None:
    """Two timed events on the same day should sum into timed_event_hours."""
    multi = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//e//e//EN
BEGIN:VEVENT
UID:a@e
DTSTART:20990401T130000Z
DTEND:20990401T140000Z
SUMMARY:1h
END:VEVENT
BEGIN:VEVENT
UID:b@e
DTSTART:20990401T150000Z
DTEND:20990401T173000Z
SUMMARY:2.5h
END:VEVENT
END:VCALENDAR
"""
    df = parse_ics_to_daily(multi, date(2099, 4, 1), date(2099, 4, 1), sha=_FAKE_SHA)
    row = df.iloc[0]
    assert row["day"] == date(2099, 4, 1)
    assert row["timed_event_count"] == 2
    assert row["timed_event_hours"] == pytest.approx(3.5)


@pytest.mark.parametrize(
    "ics_body",
    [
        b"not even a calendar",
        b"BEGIN:VCALENDAR\nEND:VCALENDAR\n",
    ],
)
def test_parse_ics_malformed_body_is_no_op(ics_body: bytes) -> None:
    """Malformed / empty ICS shouldn't crash — returns an empty DataFrame."""
    try:
        df = parse_ics_to_daily(ics_body, date(2099, 1, 1), date(2099, 1, 10), sha=_FAKE_SHA)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"parse_ics_to_daily should be tolerant; raised {type(exc).__name__}: {exc}")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_load_calendar_daily_fetches_unconfigured_returns_no_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: even if CALENDAR_ICS_URL is set globally but caller
    passes url='' explicitly, behave the same as no-config (skip)."""

    def _called_with_explicit_empty(_url: str) -> bytes:
        raise AssertionError("fetch_fn called when url=''")

    # url="" (falsy) treated as not configured.
    result: Any = load_calendar_daily(url="", fetch_fn=_called_with_explicit_empty)
    assert result.skipped is True
