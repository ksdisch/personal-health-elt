"""Prefect 3.x flow: load any new HK CSVs from the drop folder, then `dbt build`.

Three modes of invocation:

1.  **One-shot** — run once, exit:
        uv run python -m ingest.flows.weekly_load

2.  **Long-lived scheduler** — register a cron and stay running:
        uv run python -m ingest.flows.weekly_load --serve

3.  **From another Python process** — `from ingest.flows.weekly_load import weekly_load`
    then call `weekly_load()`.

The flow is idempotent: re-running it on a clean drop folder is a no-op
because every loader checks raw.file_inventory before doing work, and
ON CONFLICT DO NOTHING handles row-level overlaps.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import date, timedelta
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.exceptions import MissingContextError
from prefect.schedules import Cron

from ingest.config import RAW_DATA_PATH
from ingest.loaders.batch import BatchResult, load_folder
from ingest.loaders.calendar_google import CalendarLoadResult, load_calendar_daily
from ingest.loaders.weather_openweather import WeatherLoadResult, load_weather_daily

# How far back to backfill weather on every flow run. Weather data is
# small and immutable for past dates; a 14-day window cheaply re-covers
# any prior-run miss without thrashing the API.
_WEATHER_BACKFILL_DAYS = 14

# Calendar lookback: a couple of months covers any backfill gap from a
# skipped weekly_load and stays cheap on RRULE expansion. Calendar
# events are mutable (you might add/remove events affecting past days),
# so a longer window than weather is intentional.
_CALENDAR_LOOKBACK_DAYS = 60

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _logger() -> logging.Logger:
    """Prefect run logger when inside a flow/task context, else stdlib.

    Lets the @task functions be called directly (`.fn(...)`) from tests
    or ad-hoc scripts without a Prefect runtime. Inside a flow, logs
    route to the Prefect UI as expected.
    """
    try:
        return get_run_logger()  # type: ignore[return-value]
    except MissingContextError:
        return logging.getLogger(__name__)


@task(retries=1, retry_delay_seconds=30)
def load_drop_folder(drop_dir: Path) -> BatchResult:
    """Walk the drop folder and dispatch every recognized HK CSV.

    Retries once with a 30s delay — most failures are transient (e.g.,
    Postgres restarting between docker compose runs).
    """
    return load_folder(drop_dir)


@task(retries=1, retry_delay_seconds=60)
def load_weather() -> WeatherLoadResult:
    """Backfill the trailing `_WEATHER_BACKFILL_DAYS` of weather summaries.

    Non-fatal by design: caller wraps this in try/except and logs the
    failure as a warning rather than aborting the flow. Weather is
    enrichment, not a primary signal. The loader itself returns
    `WeatherLoadResult(skipped=True)` when no API key is configured —
    so a portfolio clone without credentials gets a quiet no-op here.
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=_WEATHER_BACKFILL_DAYS - 1)
    return load_weather_daily(start, end)


@task(retries=1, retry_delay_seconds=60)
def load_calendar() -> CalendarLoadResult:
    """Pull the trailing `_CALENDAR_LOOKBACK_DAYS` of calendar density.

    Same non-fatal pattern as weather: the loader skips silently when
    CALENDAR_ICS_URL is unset, and the flow swallows other errors so a
    Google iCal outage never blocks the dbt build.
    """
    return load_calendar_daily(lookback_days=_CALENDAR_LOOKBACK_DAYS)


class DbtBuildError(RuntimeError):
    """Raised when `dbt build` exits non-zero. Triggers Prefect retry."""


_STDERR_TAIL_LINES = 20


@task(retries=2, retry_delay_seconds=60)
def run_dbt_build() -> int:
    """Trigger `dbt build` via subprocess. Returns 0 on success; raises
    DbtBuildError on non-zero exit so Prefect's retry logic kicks in.

    After 3 total attempts (initial + 2 retries) the task fails terminally,
    Prefect propagates the exception, the flow run is marked failed, and
    the CLI invocation exits non-zero. The last `_STDERR_TAIL_LINES` of
    dbt stderr are logged at ERROR before each raise so the alert is in
    the Prefect UI / structured log without dumping a full stack trace.
    """
    log = _logger()
    cmd = [
        "uv",
        "run",
        "dbt",
        "build",
        "--project-dir",
        str(PROJECT_ROOT / "transform"),
        "--profiles-dir",
        str(PROJECT_ROOT / "transform"),
    ]
    log.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-_STDERR_TAIL_LINES:])
        log.error(
            "dbt build failed (rc=%s). stderr tail:\n%s",
            proc.returncode,
            tail or "(empty)",
        )
        raise DbtBuildError(f"dbt build failed with rc={proc.returncode}")
    log.info("dbt build succeeded")
    return proc.returncode


@flow(name="weekly-health-load")
def weekly_load() -> dict[str, int | None]:
    """End-to-end weekly refresh: load CSVs → dbt build → return summary."""
    log = _logger()
    result = load_drop_folder(RAW_DATA_PATH)

    # Weather is enrichment, not a primary signal. Swallow failures so a
    # bad API key / quota / outage never blocks the dbt build downstream.
    try:
        weather = load_weather()
    except Exception:
        log.exception("weather backfill failed; continuing without it")
        weather = WeatherLoadResult(
            rows_read=0,
            rows_inserted=0,
            days_fetched=0,
            days_already_present=0,
            skipped=True,
        )

    # Same non-fatal pattern for calendar.
    try:
        calendar = load_calendar()
    except Exception:
        log.exception("calendar fetch failed; continuing without it")
        calendar = CalendarLoadResult(
            rows_inserted=0,
            days_aggregated=0,
            sha256=None,
            skipped=True,
            skipped_unchanged=False,
        )

    summary: dict[str, int | None] = {
        "files_loaded": result.files_loaded,
        "files_already_seen": result.files_already_loaded,
        "files_skipped": len(result.skipped),
        "files_errored": len(result.errors),
        "rows_inserted": result.total_rows_inserted,
        "weather_days_fetched": weather.days_fetched,
        "weather_rows_inserted": weather.rows_inserted,
        "weather_skipped": int(weather.skipped),
        "calendar_rows_inserted": calendar.rows_inserted,
        "calendar_days_aggregated": calendar.days_aggregated,
        "calendar_skipped": int(calendar.skipped),
        "calendar_skipped_unchanged": int(calendar.skipped_unchanged),
    }

    # Per-kind breakdown is always logged so a flaky family (e.g. only
    # workouts failed) is obvious at a glance. JSON-formatted because
    # the structured Prefect UI parses it nicely.
    log.info("per-kind breakdown:\n%s", result.format_summary_table())
    log.info(
        "per-kind breakdown (json): %s",
        json.dumps(result.per_kind_summary(), default=str),
    )

    if result.errors:
        # Structured ERROR log so on-call (or future Slack/email hook)
        # gets the exact paths + error types without grepping stderr.
        log.error(
            "%d files errored — skipping dbt build. errored metric types: %s",
            len(result.errors),
            json.dumps(result.errored_metric_types(), default=str),
        )
        summary["dbt_exit_code"] = None
    elif (
        result.total_rows_inserted == 0
        and weather.rows_inserted == 0
        and calendar.rows_inserted == 0
    ):
        log.info("No new rows (HK, weather, or calendar); skipping dbt build")
        summary["dbt_exit_code"] = None
    else:
        summary["dbt_exit_code"] = run_dbt_build()

    log.info("weekly_load summary: %s", json.dumps(summary, default=str))
    return summary


def _serve() -> None:
    """Register a cron schedule and keep the process alive (Prefect 3.x serve).

    Cadence: Sunday 11 AM CT — gives Kyle time to export from the iOS app
    in the morning, runs before the weekly-health-review (5:30 PM, planned)
    and weekly-workout-planner (6:00 PM).

    Press Ctrl-C to stop.
    """
    weekly_load.serve(
        name="weekly-health-load",
        schedules=[Cron("0 11 * * 0", timezone="America/Chicago")],
        description="Load new HK CSVs from data/raw and run dbt build.",
        tags=["health", "weekly"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Register the Sunday 11am CT cron and stay alive (long-running).",
    )
    args = parser.parse_args()

    if args.serve:
        _serve()
    else:
        weekly_load()


if __name__ == "__main__":
    main()
