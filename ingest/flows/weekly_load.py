"""Prefect 3.x flow: scan the drop folder, load new files, trigger dbt build.

Invocation:
    uv run python -m ingest.flows.weekly_load
"""
from __future__ import annotations

from pathlib import Path

from prefect import flow, task

from ingest.config import RAW_DATA_PATH
from ingest.file_inventory import FileEntry, scan, unseen


@task
def scan_inventory(drop_dir: Path) -> list[FileEntry]:
    """Hash CSVs in the drop folder and return those not yet in raw.file_inventory.

    Week 1 — wire the seen_hashes query. Today we return everything as new.
    """
    seen_hashes: set[str] = set()  # TODO: SELECT sha256 FROM raw.file_inventory
    return unseen(scan(drop_dir), seen_hashes)


@task
def load_files(entries: list[FileEntry]) -> int:
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
