"""Prefect 3.x flow: scan the drop folder, load new files, trigger dbt build.

Invocation:
    uv run python -m ingest.flows.weekly_load
"""
from __future__ import annotations

from pathlib import Path

from prefect import flow, task

from ingest.config import RAW_DATA_PATH


@task
def scan_inventory(drop_dir: Path) -> list[Path]:
    """Return new CSVs to load. Week 1 — wire up to raw.file_inventory."""
    return []


@task
def load_files(paths: list[Path]) -> int:
    """Dispatch each CSV to the appropriate loader. Week 2/3."""
    return 0


@task
def run_dbt_build() -> None:
    """Trigger `dbt build`. Week 4 — prefer dbt Cloud trigger or subprocess."""
    return None


@flow(name="weekly-health-load")
def weekly_load() -> None:
    """End-to-end weekly refresh."""
    new_files = scan_inventory(RAW_DATA_PATH)
    load_files(new_files)
    run_dbt_build()


if __name__ == "__main__":
    weekly_load()
