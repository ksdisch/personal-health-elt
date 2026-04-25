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
import subprocess
from pathlib import Path

from prefect import flow, get_run_logger, task

from ingest.config import RAW_DATA_PATH
from ingest.loaders.batch import BatchResult, load_folder

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@task(retries=1, retry_delay_seconds=30)
def load_drop_folder(drop_dir: Path) -> BatchResult:
    """Walk the drop folder and dispatch every recognized HK CSV.

    Retries once with a 30s delay — most failures are transient (e.g.,
    Postgres restarting between docker compose runs).
    """
    return load_folder(drop_dir)


@task
def run_dbt_build() -> int:
    """Trigger `dbt build` via subprocess. Returns the exit code (0 = success)."""
    log = get_run_logger()
    cmd = [
        "uv", "run", "dbt", "build",
        "--project-dir", str(PROJECT_ROOT / "transform"),
        "--profiles-dir", str(PROJECT_ROOT / "transform"),
    ]
    log.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    return proc.returncode


@flow(name="weekly-health-load")
def weekly_load() -> dict:
    """End-to-end weekly refresh: load CSVs → dbt build → return summary."""
    log = get_run_logger()
    result = load_drop_folder(RAW_DATA_PATH)

    summary = {
        "files_loaded":       result.files_loaded,
        "files_already_seen": result.files_already_loaded,
        "files_skipped":      len(result.skipped),
        "files_errored":      len(result.errors),
        "rows_inserted":      result.total_rows_inserted,
    }

    if result.errors:
        log.warning("%d files errored — skipping dbt build", len(result.errors))
        summary["dbt_exit_code"] = None
    elif result.total_rows_inserted == 0:
        log.info("No new rows; skipping dbt build")
        summary["dbt_exit_code"] = None
    else:
        summary["dbt_exit_code"] = run_dbt_build()

    log.info("weekly_load summary: %s", summary)
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
        cron="0 11 * * 0",
        timezone="America/Chicago",
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
