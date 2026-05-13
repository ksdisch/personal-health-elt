"""Google Calendar density loader via secret iCal URL.

Fetches the user's calendar as ICS once per run, parses events
(expanding recurring rules into instances over the lookback window),
and rolls each day up into a small set of density signals:

    - timed_event_count   — non-all-day events on the day
    - timed_event_hours   — sum of those durations
    - all_day_event_count — count of all-day events
    - first_event_local   — earliest timed-event start (local TZ)
    - last_event_local    — latest timed-event end (local TZ)

These let downstream marts ask "how packed was yesterday?" without
needing OAuth or any synchronous API. Two-level idempotency contract:

  1. File-level — SHA256 of the ICS body in raw.file_inventory. An
     unchanged calendar short-circuits at the ledger check.
  2. Row-level — PK on (day, source_sha256) + ON CONFLICT DO NOTHING.
     A re-fetch of the same body (same SHA) inserts zero rows.

When the ICS body changes (you added or removed an event) the loader
sees a new SHA, ingests a fresh (day, sha) row-set, and downstream
stg_calendar picks the latest SHA per day for the mart join.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil.rrule import rrulestr
from icalendar import Calendar
from sqlalchemy.engine import Engine

from ingest.config import CALENDAR_ICS_URL
from ingest.db import get_engine
from ingest.loaders._idempotency import already_loaded, record_file, upsert_rows

logger = logging.getLogger(__name__)

# America/Chicago matches the project's staging-layer timezone choice
# in CLAUDE.md. Calendar aggregates are bucketed into local days because
# "how busy was yesterday" is a question about lived hours, not UTC.
LOCAL_TZ = ZoneInfo("America/Chicago")

_HTTP_TIMEOUT_SEC = 30

# Safety cap on RRULE iteration. Defends against pathological rules
# (e.g., FREQ=SECONDLY) without UNTIL/COUNT that would otherwise spin
# forever within a long window. A typical weekly cadence over a year
# is ~52 instances; 5,000 is a 100x margin that still terminates fast.
_MAX_RRULE_INSTANCES = 5000

FetchFn = Callable[[str], bytes]


@dataclass(frozen=True)
class CalendarLoadResult:
    rows_inserted: int
    days_aggregated: int
    sha256: str | None
    skipped: bool  # entire run skipped (no URL configured)
    skipped_unchanged: bool  # ICS body matched an already-loaded SHA


def _fetch_ics(url: str) -> bytes:
    """One HTTP GET against the secret iCal URL."""
    req = Request(url, headers={"User-Agent": "personal-health-elt/0.1"})
    with urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 (user-configured URL)
        body = resp.read()
    if not isinstance(body, bytes):
        raise ValueError(f"unexpected response type from ICS URL: {type(body).__name__}")
    return body


def _ensure_aware(dt: datetime | date) -> datetime:
    """Promote date → datetime-at-midnight-local, naive datetime → UTC.

    icalendar returns either a `date` (all-day events) or a `datetime`
    (timed events). Naive datetimes occur for floating events; treat
    them as UTC for safety. All-day events get midnight LOCAL_TZ so
    they bucket to the expected local day.
    """
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return datetime.combine(dt, time.min, tzinfo=LOCAL_TZ)


def _expand_event(
    component, window_start: date, window_end: date
) -> list[tuple[datetime, datetime, bool]]:
    """Expand one VEVENT (possibly RRULE-recurring) into concrete instances.

    Returns a list of (start_dt, end_dt, is_all_day) tuples in UTC-aware
    datetimes, clipped to the [window_start, window_end] range. Uses
    icalendar's PROPERTY accessors so DTSTART / DTEND / RRULE / EXDATE
    handling stays canonical (no manual rrule library wrangling).
    """
    dtstart_prop = component.get("dtstart")
    dtend_prop = component.get("dtend")
    if dtstart_prop is None:
        return []

    dtstart = dtstart_prop.dt
    is_all_day = not isinstance(dtstart, datetime)

    # Duration defaults: 0 for events with no DTEND (point-in-time);
    # 1 day for all-day events without DTEND.
    if dtend_prop is None:
        duration = timedelta(days=1) if is_all_day else timedelta(0)
    else:
        duration = dtend_prop.dt - dtstart
        if not isinstance(duration, timedelta):
            return []  # malformed

    window_start_dt = datetime.combine(window_start, time.min, tzinfo=LOCAL_TZ)
    window_end_dt = datetime.combine(window_end + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)

    rrule_prop = component.get("rrule")
    if rrule_prop is None:
        start = _ensure_aware(dtstart)
        if start >= window_end_dt:
            return []
        return [(start, start + duration, is_all_day)]

    # icalendar.cal.Event doesn't expose a portable RRULE expander, so
    # we hand the rule string to dateutil's rrulestr (imported at module
    # scope).
    #
    # rrulestr handles both an "RRULE:" prefix or just the rule body.
    rule_str = (
        rrule_prop.to_ical().decode("utf-8") if hasattr(rrule_prop, "to_ical") else str(rrule_prop)
    )
    dtstart_aware = _ensure_aware(dtstart)
    rule = rrulestr(f"RRULE:{rule_str}", dtstart=dtstart_aware)

    # EXDATE handling. icalendar returns a single vDDDLists when the
    # event has one EXDATE property and a list of them when there are
    # multiple. Normalize to a list before iterating; each vDDDLists
    # exposes its dates via `.dts`. The previous shape — iterating the
    # property directly — raised "TypeError: 'vDDDLists' object is not
    # iterable" on any event with even one EXDATE.
    excluded_set: set[datetime] = set()
    exdate_prop = component.get("exdate")
    if exdate_prop is not None:
        exdate_lists = exdate_prop if isinstance(exdate_prop, list) else [exdate_prop]
        for exdate_list in exdate_lists:
            for ex in exdate_list.dts:
                excluded_set.add(_ensure_aware(ex.dt))

    # Iterate occurrences in order (dateutil.rrule guarantees this for
    # rules without BYSETPOS). Stop at window_end_dt; rely on the
    # instance-count cap as a safety net for runaway rules.
    instances: list[tuple[datetime, datetime, bool]] = []
    for i, occ in enumerate(rule):
        if i >= _MAX_RRULE_INSTANCES:
            logger.warning(
                "calendar: hit RRULE expansion safety cap (%d instances) for event "
                "starting %s; truncating",
                _MAX_RRULE_INSTANCES,
                dtstart_aware,
            )
            break
        if not isinstance(occ, datetime):
            continue
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=UTC)
        if occ >= window_end_dt:
            break
        if occ < window_start_dt:
            continue
        if occ in excluded_set:
            continue
        instances.append((occ, occ + duration, is_all_day))
    return instances


_EMPTY_DAILY_COLUMNS: list[str] = [
    "day",
    "timed_event_count",
    "timed_event_hours",
    "all_day_event_count",
    "first_event_local",
    "last_event_local",
    "source_sha256",
]


def parse_ics_to_daily(
    body: bytes,
    window_start: date,
    window_end: date,
    sha: str,
) -> pd.DataFrame:
    """Parse an ICS body into per-day density aggregates.

    Returns one row per day in [window_start, window_end] that had at
    least one event (timed or all-day). Days with no events get no row
    — downstream stg_calendar / mart_daily_context left-join handles
    "no calendar activity" naturally as NULL.

    Tolerant of malformed bodies. icalendar's parser raises ValueError
    on bytes that don't start with a VCALENDAR block (or have an
    unparseable content line); we swallow that and return an empty
    DataFrame so a bad response from the iCal URL does not crash the
    weekly_load flow. The loader caller treats empty-DF as "no events
    on any day in the window," which matches the desired behavior.
    """
    try:
        cal = Calendar.from_ical(body)
    except ValueError:
        logger.warning("calendar: malformed ICS body (sha=%s); returning empty", sha[:8])
        return pd.DataFrame(columns=_EMPTY_DAILY_COLUMNS)

    rows: list[dict[str, object]] = []

    for component in cal.walk("VEVENT"):
        for start, end, is_all_day in _expand_event(component, window_start, window_end):
            local_start = start.astimezone(LOCAL_TZ)
            local_end = end.astimezone(LOCAL_TZ)
            day = local_start.date()
            if day < window_start or day > window_end:
                continue
            rows.append(
                {
                    "day": day,
                    "is_all_day": is_all_day,
                    "duration_hours": max(
                        (local_end - local_start).total_seconds() / 3600.0,
                        0.0,
                    ),
                    "start_local": local_start.replace(tzinfo=None),
                    "end_local": local_end.replace(tzinfo=None),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_EMPTY_DAILY_COLUMNS)

    df = pd.DataFrame(rows)
    timed = df[~df["is_all_day"]]
    all_day = df[df["is_all_day"]]

    timed_agg = (
        timed.groupby("day").agg(
            timed_event_count=("is_all_day", "size"),
            timed_event_hours=("duration_hours", "sum"),
            first_event_local=("start_local", "min"),
            last_event_local=("end_local", "max"),
        )
        if not timed.empty
        else pd.DataFrame(
            columns=[
                "timed_event_count",
                "timed_event_hours",
                "first_event_local",
                "last_event_local",
            ]
        )
    )
    all_day_agg = (
        all_day.groupby("day").agg(all_day_event_count=("is_all_day", "size"))
        if not all_day.empty
        else pd.DataFrame(columns=["all_day_event_count"])
    )
    daily = timed_agg.join(all_day_agg, how="outer").reset_index()
    daily["timed_event_count"] = daily["timed_event_count"].fillna(0).astype(int)
    daily["timed_event_hours"] = daily["timed_event_hours"].fillna(0.0)
    daily["all_day_event_count"] = daily["all_day_event_count"].fillna(0).astype(int)
    daily["source_sha256"] = sha
    return daily


def load_calendar_daily(
    *,
    lookback_days: int = 60,
    today: date | None = None,
    url: str | None = None,
    engine: Engine | None = None,
    fetch_fn: FetchFn | None = None,
) -> CalendarLoadResult:
    """Fetch + parse the configured ICS URL into raw.calendar_daily.

    Window: the trailing `lookback_days` ending at `today` (inclusive).
    Defaults to 60 days — long enough to cover any backfill gap from a
    skipped weekly_load run, short enough that RRULE expansion stays
    cheap.

    Returns ``CalendarLoadResult(skipped=True)`` when the URL is
    unconfigured. Returns ``skipped_unchanged=True`` when the ICS body
    SHA already exists in raw.file_inventory — the loader skipped the
    parse step but the table rows from the prior load are still valid.

    ``fetch_fn`` is injectable for tests so the suite can pass a
    sample ICS bytestring without HTTP.
    """
    url = url if url is not None else CALENDAR_ICS_URL
    if not url:
        logger.info("calendar: no ICS URL configured, skipping")
        return CalendarLoadResult(
            rows_inserted=0,
            days_aggregated=0,
            sha256=None,
            skipped=True,
            skipped_unchanged=False,
        )

    engine = engine or get_engine()
    fetch = fetch_fn or _fetch_ics
    body = fetch(url)
    sha = hashlib.sha256(body).hexdigest()

    with engine.connect() as conn:
        if already_loaded(conn, sha):
            logger.info("calendar: ICS unchanged (sha=%s), skipping parse", sha[:8])
            return CalendarLoadResult(
                rows_inserted=0,
                days_aggregated=0,
                sha256=sha,
                skipped=False,
                skipped_unchanged=True,
            )

    end = today if today is not None else date.today()
    start = end - timedelta(days=lookback_days - 1)
    daily = parse_ics_to_daily(body, start, end, sha)

    with engine.begin() as conn:
        record_file(conn, sha, "calendar.ics")
        inserted = (
            upsert_rows(
                conn,
                daily,
                table="calendar_daily",
                index_elements=["day", "source_sha256"],
            )
            if not daily.empty
            else 0
        )

    logger.info(
        "calendar: parsed %d days, inserted %d (sha=%s)",
        len(daily),
        inserted,
        sha[:8],
    )
    return CalendarLoadResult(
        rows_inserted=inserted,
        days_aggregated=len(daily),
        sha256=sha,
        skipped=False,
        skipped_unchanged=False,
    )


def _main() -> None:
    """CLI: backfill the trailing N days, default 60.

    Usage:
        uv run python -m ingest.loaders.calendar_google [days]
    """
    import sys

    days = int(sys.argv[1]) if len(sys.argv) >= 2 else 60
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_calendar_daily(lookback_days=days)
    if result.skipped:
        print("status:    SKIPPED (CALENDAR_ICS_URL not configured)")
        return
    if result.skipped_unchanged:
        sha_prefix = result.sha256[:8] if result.sha256 else "?"
        print(f"status:    SKIPPED (ICS unchanged, sha={sha_prefix})")
        return
    print(f"days:      {result.days_aggregated}")
    print(f"inserted:  {result.rows_inserted}")
    print(f"sha256:    {result.sha256}")


if __name__ == "__main__":
    _main()
