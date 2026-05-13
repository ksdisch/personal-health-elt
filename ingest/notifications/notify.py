"""Anomaly → notification orchestrator.

Reads `analytics_marts.mart_recovery_state`, evaluates the YAML rules,
dedups against `raw.notification_log`, and fires whichever transports
are configured. Wired into `weekly_load` as a non-fatal task after the
dbt build, following the same try/except shape as the weather and
calendar enrichment tasks.

Dedup contract: the (rule_name, day) primary key on raw.notification_log
is the *only* mechanism. The orchestrator INSERTs first; if rowcount==0
the row already existed and the send is skipped. Same shape as the
weather loader's "fetch only missing dates" but at row-grain.

Send order: stdout always fires first (it can't fail), then Pushover.
A Pushover failure leaves a logged row + stdout signal + an error in
the returned NotifyResult — the operator gets the structured failure
in the Prefect log but loses the phone push for that day. Acceptable
trade-off for a personal pipeline; "guaranteed delivery" is not a
requirement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.config import (
    NOTIFICATION_RULES_PATH,
    NOTIFY_DRY_RUN,
    PUSHOVER_TOKEN,
    PUSHOVER_USER,
)
from ingest.db import get_engine
from ingest.notifications.rules import (
    MartRow,
    RuleConfigError,
    Trigger,
    evaluate,
    load_rules,
)
from ingest.notifications.transport import (
    PushoverError,
    send_pushover,
    send_stdout,
)

logger = logging.getLogger(__name__)

# Minimum lookback for the trailing window. transition_to needs 2 rows
# (today + yesterday); consecutive(N) needs N rows. We always pull at
# least this many days even if no rule asks for it, to keep the SELECT
# bounded and stable across rule edits.
_DEFAULT_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class NotifyResult:
    notifications_sent: int
    notifications_deduped: int  # rule fired but already in log → skipped transport
    rules_evaluated: int
    rows_read: int
    skipped: bool  # entire run skipped (no rules file, no rows in mart, etc.)
    errors: list[str] = field(default_factory=list)


def _read_recovery_state(engine: Engine, today: date, lookback_days: int) -> list[MartRow]:
    """Pull the trailing window from `analytics_marts.mart_recovery_state`.

    Returns rows ordered by `day` ascending. Returns empty list when the
    mart table doesn't exist yet (e.g., the dbt build has never run
    successfully in this environment) so the notifier skips gracefully
    instead of crashing the flow.
    """
    sql = text(
        """
        SELECT day, recovery_signal, hrv_ms, acwr, rhr_bpm
        FROM analytics_marts.mart_recovery_state
        WHERE day BETWEEN :start AND :end
        ORDER BY day
        """
    )
    start = today - timedelta(days=lookback_days)
    with engine.connect() as conn:
        try:
            result = conn.execute(sql, {"start": start, "end": today})
        except Exception as exc:
            # UndefinedTable, no such schema, etc. Don't bubble up — the
            # mart simply isn't there yet. notify_on_state_change treats
            # this as "no rows" and returns skipped=True.
            logger.warning("notify: mart query failed (%s); skipping", exc)
            return []
        return [
            MartRow(
                day=row[0],
                recovery_signal=row[1],
                hrv_ms=float(row[2]) if row[2] is not None else None,
                acwr=float(row[3]) if row[3] is not None else None,
                rhr_bpm=float(row[4]) if row[4] is not None else None,
            )
            for row in result
        ]


def _transport_label(dry_run: bool, has_pushover: bool) -> str:
    if dry_run:
        return "dry_run"
    if has_pushover:
        return "stdout+pushover"
    return "stdout"


def _claim_log_row(
    engine: Engine,
    trigger: Trigger,
    transport: str,
) -> bool:
    """Claim a row in raw.notification_log via INSERT ON CONFLICT DO NOTHING.

    Returns True when the row was newly inserted (caller should send),
    False when a row for this (rule_name, day) already existed (caller
    should skip).
    """
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO raw.notification_log
                    (rule_name, day, severity, signal, message, transport)
                VALUES (:rule_name, :day, :severity, :signal, :message, :transport)
                ON CONFLICT (rule_name, day) DO NOTHING
                """
            ),
            {
                "rule_name": trigger.rule_name,
                "day": trigger.day,
                "severity": trigger.severity,
                "signal": trigger.signal,
                "message": trigger.message,
                "transport": transport,
            },
        )
    return result.rowcount == 1


def notify_on_state_change(
    *,
    engine: Engine | None = None,
    rules_path: Path | None = None,
    today: date | None = None,
    pushover_token: str | None = None,
    pushover_user: str | None = None,
    dry_run: bool | None = None,
) -> NotifyResult:
    """Evaluate rules against mart_recovery_state and fire notifications.

    All inputs are injectable for testing. Defaults pull from
    `ingest.config` so a flow-level call needs no arguments.

    `dry_run=True` forces stdout-only regardless of Pushover config —
    matches the BACKLOG's "test mode where notifications go to stdout
    instead." The flag also propagates into the log row's `transport`
    column so a post-mortem can distinguish real fires from rehearsals.
    """
    engine = engine if engine is not None else get_engine()
    rules_path = rules_path if rules_path is not None else NOTIFICATION_RULES_PATH
    token = pushover_token if pushover_token is not None else PUSHOVER_TOKEN
    user = pushover_user if pushover_user is not None else PUSHOVER_USER
    dry = dry_run if dry_run is not None else NOTIFY_DRY_RUN
    today = today if today is not None else date.today()

    if not rules_path.exists():
        logger.info("notify: no rules file at %s; skipping", rules_path)
        return NotifyResult(0, 0, 0, 0, skipped=True)

    try:
        rules = load_rules(rules_path)
    except RuleConfigError as exc:
        logger.error("notify: rules file invalid: %s", exc)
        return NotifyResult(0, 0, 0, 0, skipped=True, errors=[str(exc)])

    if not rules:
        logger.info("notify: rules file is empty; skipping")
        return NotifyResult(0, 0, 0, 0, skipped=True)

    lookback = max([_DEFAULT_LOOKBACK_DAYS] + [r.days for r in rules if r.days is not None])
    rows = _read_recovery_state(engine, today, lookback)
    if not rows:
        logger.info("notify: no rows in mart_recovery_state for window; skipping")
        return NotifyResult(0, 0, len(rules), 0, skipped=True)

    triggers = evaluate(rules, rows)
    has_pushover = bool(token and user) and not dry
    transport_label = _transport_label(dry, bool(token and user))

    sent = 0
    deduped = 0
    errors: list[str] = []

    for trig in triggers:
        # Belt-and-suspenders: rule evaluator only ever fires for today's
        # row, but enforce it again here so a future evaluator change
        # can't accidentally back-date a notification.
        if trig.day != today:
            logger.warning("notify: skipping non-today trigger %s for %s", trig.rule_name, trig.day)
            continue
        claimed = _claim_log_row(engine, trig, transport_label)
        if not claimed:
            deduped += 1
            logger.info("notify: %s already fired today (deduped via log)", trig.rule_name)
            continue
        # Stdout first: it can't fail, so even if Pushover errors below
        # the operator still has the signal in the Prefect log.
        send_stdout(trig)
        if has_pushover:
            try:
                assert token is not None and user is not None
                send_pushover(trig, token, user)
            except PushoverError as exc:
                msg = f"{trig.rule_name}: pushover failed: {exc}"
                errors.append(msg)
                logger.error("notify: %s", msg)
        sent += 1

    return NotifyResult(
        notifications_sent=sent,
        notifications_deduped=deduped,
        rules_evaluated=len(rules),
        rows_read=len(rows),
        skipped=False,
        errors=errors,
    )
