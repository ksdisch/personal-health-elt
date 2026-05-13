"""Pure rule evaluation for the anomaly → notification pipeline.

No database, no I/O beyond reading the YAML rules file. Tested in
isolation so the trigger logic stays fast to iterate on without
spinning up Postgres.

Two rule kinds in v1:

    transition_to
        Fires on the day the mart's `recovery_signal` flips INTO the
        rule's `signal` value — i.e., yesterday's signal ≠ rule.signal
        AND today's signal == rule.signal. Captures "red-edge events"
        without re-firing every day the streak continues.

    consecutive
        Fires on the day a streak of `rule.days` consecutive matching
        signals JUST reached length N — i.e., the last N rows all match
        the signal AND day N+1 (if any) does not. Captures the BACKLOG's
        "3rd consecutive day of elevated RHR" semantics without
        re-firing on days 4, 5, 6 of an extended streak.

A future `raw_threshold` kind (numeric comparison against the mart's
hrv_ms / acwr / rhr_bpm columns) is anticipated but deferred — the
mart's existing band-math already populates `recovery_signal`, so
"strained" already encodes the threshold logic for v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

RuleKind = Literal["transition_to", "consecutive"]
_VALID_KINDS: tuple[str, ...] = ("transition_to", "consecutive")
_VALID_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")


@dataclass(frozen=True)
class Rule:
    name: str
    kind: RuleKind
    signal: str
    severity: str
    message_template: str
    days: int | None = None  # required when kind == "consecutive"


@dataclass(frozen=True)
class MartRow:
    """The subset of mart_recovery_state columns the notifier consumes.

    Kept narrow on purpose: adding a column here is a contract change
    that ripples into the SQL select and the template-format kwargs.
    """

    day: date
    recovery_signal: str | None
    hrv_ms: float | None
    acwr: float | None
    rhr_bpm: float | None


@dataclass(frozen=True)
class Trigger:
    rule_name: str
    day: date
    severity: str
    signal: str | None
    message: str


class RuleConfigError(ValueError):
    """Raised when the YAML rules file is malformed."""


def load_rules(path: Path) -> list[Rule]:
    """Parse YAML at `path` into a list of validated Rule dataclasses.

    The YAML root must be a list. Each list element must be a mapping
    with the required fields for its kind. Unknown kinds, missing
    fields, or `consecutive` without `days >= 1` raise RuleConfigError
    with a path-prefixed message so the operator knows which file is
    wrong.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuleConfigError(f"{path}: expected a list at the YAML root, got {type(raw).__name__}")
    rules: list[Rule] = []
    seen_names: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuleConfigError(f"{path}[{i}]: each rule must be a mapping")
        try:
            rule = _parse_rule(item)
        except RuleConfigError as exc:
            raise RuleConfigError(f"{path}[{i}]: {exc}") from None
        if rule.name in seen_names:
            raise RuleConfigError(f"{path}[{i}]: duplicate rule name {rule.name!r}")
        seen_names.add(rule.name)
        rules.append(rule)
    return rules


def _parse_rule(item: dict[str, Any]) -> Rule:
    for field in ("name", "kind", "signal", "severity", "message_template"):
        if field not in item:
            raise RuleConfigError(f"missing required field {field!r}")
    kind = item["kind"]
    if kind not in _VALID_KINDS:
        raise RuleConfigError(f"unknown kind {kind!r}; must be one of {_VALID_KINDS}")
    severity = item["severity"]
    if severity not in _VALID_SEVERITIES:
        raise RuleConfigError(f"unknown severity {severity!r}; must be one of {_VALID_SEVERITIES}")
    days: int | None = None
    if kind == "consecutive":
        if "days" not in item:
            raise RuleConfigError("kind=consecutive requires a `days` integer ≥ 1")
        days = item["days"]
        if not isinstance(days, int) or days < 1:
            raise RuleConfigError(f"`days` must be an integer ≥ 1, got {days!r}")
    return Rule(
        name=str(item["name"]),
        kind=kind,
        signal=str(item["signal"]),
        severity=str(severity),
        message_template=str(item["message_template"]),
        days=days,
    )


def evaluate(rules: list[Rule], rows: list[MartRow]) -> list[Trigger]:
    """Evaluate every rule against the trailing-window of mart rows.

    `rows` MUST be sorted by `day` ascending; the last element is treated
    as "today." Empty `rows` returns []. Each rule fires at most one
    trigger per call (since each rule pins to "today"); dedup across
    runs is handled by the caller via raw.notification_log.
    """
    if not rows:
        return []
    today_row = rows[-1]
    out: list[Trigger] = []
    for rule in rules:
        trigger = _eval_rule(rule, rows, today_row)
        if trigger is not None:
            out.append(trigger)
    return out


def _eval_rule(rule: Rule, rows: list[MartRow], today_row: MartRow) -> Trigger | None:
    if rule.kind == "transition_to":
        if len(rows) < 2:
            return None
        prev_row = rows[-2]
        if today_row.recovery_signal != rule.signal:
            return None
        if prev_row.recovery_signal == rule.signal:
            return None  # not a transition — already in the signal state yesterday
        return _make_trigger(rule, today_row)

    if rule.kind == "consecutive":
        assert rule.days is not None  # guaranteed by _parse_rule
        if len(rows) < rule.days:
            return None
        last_n = rows[-rule.days :]
        if not all(r.recovery_signal == rule.signal for r in last_n):
            return None
        # Don't fire on streak day N+1, N+2, ... — only fire the day the
        # streak first reaches length N. Exception: when the streak
        # started at the left edge of the window, the row before doesn't
        # exist; in that case we can't tell whether this is "day N" or
        # "day N+1 of a longer streak," and we fire defensively.
        if len(rows) > rule.days:
            prior = rows[-(rule.days + 1)]
            if prior.recovery_signal == rule.signal:
                return None
        return _make_trigger(rule, today_row)

    raise RuleConfigError(f"unknown rule kind: {rule.kind}")  # unreachable past _parse_rule


def _make_trigger(rule: Rule, row: MartRow) -> Trigger:
    return Trigger(
        rule_name=rule.name,
        day=row.day,
        severity=rule.severity,
        signal=row.recovery_signal,
        message=format_message(rule.message_template, row),
    )


def format_message(template: str, row: MartRow) -> str:
    """Render a rule's `message_template` using values from `row`.

    Numeric fields are pre-formatted to readable precision so the
    template doesn't need to know Python format-spec syntax. Missing
    values render as ``"n/a"`` rather than raising. A malformed
    template (referencing an unknown variable) falls back to a generic
    message so a single bad rule can't crash the flow.
    """
    args = {
        "day": row.day.isoformat(),
        "signal": row.recovery_signal if row.recovery_signal else "n/a",
        "hrv_ms": f"{row.hrv_ms:.0f}" if row.hrv_ms is not None else "n/a",
        "acwr": f"{row.acwr:.2f}" if row.acwr is not None else "n/a",
        "rhr_bpm": f"{row.rhr_bpm:.0f}" if row.rhr_bpm is not None else "n/a",
    }
    try:
        return template.format(**args)
    except (KeyError, IndexError, ValueError) as exc:
        return f"[template error: {exc}] rule fired for {row.day.isoformat()}"
