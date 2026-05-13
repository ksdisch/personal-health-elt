"""Unit tests for the pure rule evaluator.

No database. No filesystem beyond `tmp_path` for YAML round-trips. The
trigger logic is the part of the notification pipeline most worth
testing exhaustively — transport failures surface in flow logs, but a
silently wrong rule would mean a missed (or spurious) interruption to
the user's day.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from ingest.notifications.rules import (
    MartRow,
    Rule,
    RuleConfigError,
    evaluate,
    format_message,
    load_rules,
)


def _row(
    d: date,
    signal: str | None,
    hrv: float | None = 60.0,
    acwr: float | None = 1.0,
) -> MartRow:
    return MartRow(day=d, recovery_signal=signal, hrv_ms=hrv, acwr=acwr, rhr_bpm=55.0)


def _seq(*signals: str | None, start: date = date(2026, 5, 1)) -> list[MartRow]:
    """Build a contiguous trailing-window of MartRows from oldest to newest."""
    return [_row(start + timedelta(days=i), s) for i, s in enumerate(signals)]


# --------------------------------------------------------------------------
# load_rules
# --------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_rules_parses_both_kinds(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: red_transition
  kind: transition_to
  signal: strained
  severity: warning
  message_template: "Flipped to {signal} on {day}"

- name: three_strained_days
  kind: consecutive
  signal: strained
  days: 3
  severity: critical
  message_template: "3rd strained day ({day})"
""",
    )
    rules = load_rules(path)
    assert len(rules) == 2
    assert rules[0] == Rule(
        name="red_transition",
        kind="transition_to",
        signal="strained",
        severity="warning",
        message_template="Flipped to {signal} on {day}",
        days=None,
    )
    assert rules[1].days == 3
    assert rules[1].kind == "consecutive"


def test_load_rules_empty_file_returns_empty_list(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "")
    assert load_rules(path) == []


def test_load_rules_rejects_non_list_root(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "name: not-a-list")
    with pytest.raises(RuleConfigError, match="expected a list"):
        load_rules(path)


def test_load_rules_rejects_missing_field(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: missing_kind
  signal: strained
  severity: warning
  message_template: hi
""",
    )
    with pytest.raises(RuleConfigError, match="missing required field 'kind'"):
        load_rules(path)


def test_load_rules_rejects_unknown_kind(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: bad
  kind: rocket_launch
  signal: strained
  severity: warning
  message_template: hi
""",
    )
    with pytest.raises(RuleConfigError, match="unknown kind"):
        load_rules(path)


def test_load_rules_rejects_unknown_severity(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: bad
  kind: transition_to
  signal: strained
  severity: nuclear
  message_template: hi
""",
    )
    with pytest.raises(RuleConfigError, match="unknown severity"):
        load_rules(path)


def test_load_rules_rejects_consecutive_without_days(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: bad
  kind: consecutive
  signal: strained
  severity: warning
  message_template: hi
""",
    )
    with pytest.raises(RuleConfigError, match="kind=consecutive requires"):
        load_rules(path)


def test_load_rules_rejects_consecutive_zero_days(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: bad
  kind: consecutive
  signal: strained
  days: 0
  severity: warning
  message_template: hi
""",
    )
    with pytest.raises(RuleConfigError, match="`days` must be an integer"):
        load_rules(path)


def test_load_rules_rejects_duplicate_names(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
- name: dup
  kind: transition_to
  signal: strained
  severity: warning
  message_template: a
- name: dup
  kind: transition_to
  signal: neutral
  severity: warning
  message_template: b
""",
    )
    with pytest.raises(RuleConfigError, match="duplicate rule name 'dup'"):
        load_rules(path)


# --------------------------------------------------------------------------
# evaluate — transition_to
# --------------------------------------------------------------------------


_TRANSITION = Rule(
    name="red_transition",
    kind="transition_to",
    signal="strained",
    severity="warning",
    message_template="Flipped to {signal} on {day}",
)


def test_transition_fires_when_signal_flips_into_target() -> None:
    rows = _seq("neutral", "neutral", "strained")
    triggers = evaluate([_TRANSITION], rows)
    assert len(triggers) == 1
    assert triggers[0].rule_name == "red_transition"
    assert triggers[0].day == rows[-1].day
    assert triggers[0].signal == "strained"


def test_transition_does_not_fire_when_already_in_signal_state() -> None:
    rows = _seq("neutral", "strained", "strained")
    assert evaluate([_TRANSITION], rows) == []


def test_transition_does_not_fire_when_today_is_not_signal() -> None:
    rows = _seq("strained", "strained", "neutral")
    assert evaluate([_TRANSITION], rows) == []


def test_transition_needs_at_least_two_rows() -> None:
    rows = _seq("strained")
    assert evaluate([_TRANSITION], rows) == []


def test_transition_fires_from_insufficient_data_to_strained() -> None:
    # `insufficient_data` is not the target signal, so the transition counts.
    rows = _seq("insufficient_data", "strained")
    assert len(evaluate([_TRANSITION], rows)) == 1


# --------------------------------------------------------------------------
# evaluate — consecutive
# --------------------------------------------------------------------------


_CONSECUTIVE_3 = Rule(
    name="three_strained_days",
    kind="consecutive",
    signal="strained",
    severity="critical",
    message_template="3rd strained day ({day})",
    days=3,
)


def test_consecutive_fires_on_exact_streak_length() -> None:
    rows = _seq("neutral", "strained", "strained", "strained")
    triggers = evaluate([_CONSECUTIVE_3], rows)
    assert len(triggers) == 1
    assert triggers[0].rule_name == "three_strained_days"


def test_consecutive_does_not_fire_on_day_4_of_streak() -> None:
    # Streak of 4: day before the 3-day window is also strained → suppress.
    rows = _seq("strained", "strained", "strained", "strained")
    assert evaluate([_CONSECUTIVE_3], rows) == []


def test_consecutive_fires_when_streak_begins_at_window_left_edge() -> None:
    # No prior row exists; can't distinguish "day 3 of streak" from
    # "day N+ of longer streak" — defensive fire.
    rows = _seq("strained", "strained", "strained")
    assert len(evaluate([_CONSECUTIVE_3], rows)) == 1


def test_consecutive_does_not_fire_on_short_streak() -> None:
    rows = _seq("neutral", "strained", "strained")
    assert evaluate([_CONSECUTIVE_3], rows) == []


def test_consecutive_does_not_fire_when_streak_is_broken() -> None:
    rows = _seq("strained", "neutral", "strained", "strained")
    assert evaluate([_CONSECUTIVE_3], rows) == []


def test_consecutive_resets_after_neutral_day() -> None:
    # After a 4-day strained streak the next day is neutral, then the
    # 3-day rule should NOT fire again until a fresh 3-strained-streak
    # begins (and only on its 3rd day, with a prior neutral).
    rows = _seq("strained", "strained", "strained", "strained", "neutral")
    assert evaluate([_CONSECUTIVE_3], rows) == []
    rows = _seq("strained", "strained", "strained", "strained", "neutral", "strained")
    assert evaluate([_CONSECUTIVE_3], rows) == []  # only 1 day into new streak
    rows.append(_row(rows[-1].day + timedelta(days=1), "strained"))
    rows.append(_row(rows[-1].day + timedelta(days=1), "strained"))
    triggers = evaluate([_CONSECUTIVE_3], rows)
    assert len(triggers) == 1, "fresh 3-strained streak (with prior neutral) should fire"


# --------------------------------------------------------------------------
# evaluate — multi-rule interaction
# --------------------------------------------------------------------------


def test_evaluate_with_no_rules_is_empty() -> None:
    rows = _seq("neutral", "strained")
    assert evaluate([], rows) == []


def test_evaluate_with_no_rows_is_empty() -> None:
    assert evaluate([_TRANSITION, _CONSECUTIVE_3], []) == []


def test_multiple_rules_can_fire_in_same_run() -> None:
    # A 3-day streak that also represents a fresh transition (day -3
    # was neutral) fires BOTH rules simultaneously.
    rows = _seq("neutral", "strained", "strained", "strained")
    triggers = evaluate([_TRANSITION, _CONSECUTIVE_3], rows)
    # transition_to: today=strained, yesterday=strained → NO (already in state)
    # consecutive(3): last 3 strained, prior neutral → YES
    assert {t.rule_name for t in triggers} == {"three_strained_days"}


def test_both_rules_fire_when_day_minus_3_was_neutral() -> None:
    # Construct a window where today is the FIRST strained day of a
    # streak (transition fires) AND the consecutive(1) rule would too.
    rule_consec_1 = Rule(
        name="any_strained",
        kind="consecutive",
        signal="strained",
        severity="info",
        message_template="strained {day}",
        days=1,
    )
    rows = _seq("neutral", "strained")
    triggers = evaluate([_TRANSITION, rule_consec_1], rows)
    assert {t.rule_name for t in triggers} == {"red_transition", "any_strained"}


# --------------------------------------------------------------------------
# format_message
# --------------------------------------------------------------------------


def test_format_message_renders_all_fields() -> None:
    row = MartRow(
        day=date(2026, 5, 13),
        recovery_signal="strained",
        hrv_ms=42.7,
        acwr=1.673,
        rhr_bpm=58.2,
    )
    out = format_message("{signal} on {day}: HRV {hrv_ms}ms, ACWR {acwr}, RHR {rhr_bpm}", row)
    assert out == "strained on 2026-05-13: HRV 43ms, ACWR 1.67, RHR 58"


def test_format_message_renders_none_as_na() -> None:
    row = MartRow(day=date(2026, 5, 13), recovery_signal=None, hrv_ms=None, acwr=None, rhr_bpm=None)
    out = format_message("{signal}/{hrv_ms}/{acwr}/{rhr_bpm}", row)
    assert out == "n/a/n/a/n/a/n/a"


def test_format_message_falls_back_on_unknown_template_var() -> None:
    row = MartRow(
        day=date(2026, 5, 13), recovery_signal="strained", hrv_ms=42.0, acwr=1.0, rhr_bpm=58.0
    )
    out = format_message("today is {temperature} degrees", row)
    assert out.startswith("[template error:")
    assert "2026-05-13" in out  # day still surfaces for the operator's reference
