"""End-to-end idempotency test: real CSV through real Postgres.

Validates the two-level idempotency contract on raw.quantities:

  1. File-hash ledger blocks re-ingest of an unchanged file. The
     loader sees the SHA256 in raw.file_inventory and short-circuits.
  2. ON CONFLICT DO NOTHING on the natural key drops duplicate rows
     when two DIFFERENT files (distinct SHAs) carry overlapping
     samples — the ledger doesn't help here, only the row-level guard
     does.

Assertions are written as *deltas* against counts captured before the
test runs, so the suite is safe to run against a populated local
database — see the `raw_test_engine` fixture in conftest. CSV
timestamps use a far-future year so the synthetic content cannot
collide with a real Apple Health export.

The unit tests in `test_quantities_loader.py` mock the database; this
file is the first that runs against a real Postgres. The conftest
fixture skips if no Postgres is reachable, so this file is a no-op on
developer machines without docker compose up.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.loaders.quantities import load_quantities_csv

_HEADER = "type,sourceName,sourceVersion,productType,device,startDate,endDate,unit,value\n"


def _row(ts: str, value: float = 70.0) -> str:
    """One HK quantity CSV row at the given UTC timestamp."""
    return (
        "HKQuantityTypeIdentifierRestingHeartRate,"
        "Kyle's Watch,26.2,Watch7,,"
        f"{ts},{ts},count/min,{value}\n"
    )


def _write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(_HEADER + "".join(rows), encoding="utf-8")
    return path


def _counts(engine: Engine) -> tuple[int, int]:
    """(raw.quantities count, raw.file_inventory count) snapshot."""
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT COUNT(*) FROM raw.quantities")).scalar_one(),
            conn.execute(text("SELECT COUNT(*) FROM raw.file_inventory")).scalar_one(),
        )


def test_double_load_is_noop_via_file_hash_ledger(raw_test_engine: Engine, tmp_path: Path) -> None:
    """Second run of the same file: 0 rows inserted, ledger gains 1 entry."""
    engine = raw_test_engine
    csv = _write_csv(
        tmp_path / "rhr.csv",
        [
            _row("2099-03-21 07:00:40 +0000", 70.0),
            _row("2099-03-21 08:00:40 +0000", 71.0),
        ],
    )

    rows_before, files_before = _counts(engine)

    first = load_quantities_csv(csv, engine=engine)
    assert first.rows_inserted == 2, "first ingest should insert all rows"
    assert first.skipped is False

    second = load_quantities_csv(csv, engine=engine)
    assert second.rows_inserted == 0, "second ingest must be a no-op"
    assert second.skipped is True, "loader should short-circuit on known SHA"

    rows_after, files_after = _counts(engine)
    assert rows_after - rows_before == 2
    assert files_after - files_before == 1


def test_overlapping_files_dedup_via_on_conflict(raw_test_engine: Engine, tmp_path: Path) -> None:
    """Two different files with overlapping samples.

    File A: 07:00, 08:00. File B: 08:00 (overlap), 09:00 (new).
    Different file content -> distinct SHAs -> the ledger doesn't skip
    either. The ON CONFLICT DO NOTHING on the natural key
    (metric_type, source_name, start_ts) drops the duplicate 08:00 row.
    """
    engine = raw_test_engine

    csv_a = _write_csv(
        tmp_path / "rhr_a.csv",
        [
            _row("2099-03-21 07:00:40 +0000", 70.0),
            _row("2099-03-21 08:00:40 +0000", 71.0),
        ],
    )
    csv_b = _write_csv(
        tmp_path / "rhr_b.csv",
        [
            _row("2099-03-21 08:00:40 +0000", 71.0),  # overlap with A
            _row("2099-03-21 09:00:40 +0000", 72.0),  # new
        ],
    )

    rows_before, files_before = _counts(engine)

    a = load_quantities_csv(csv_a, engine=engine)
    assert a.rows_inserted == 2
    assert a.skipped is False

    b = load_quantities_csv(csv_b, engine=engine)
    assert b.skipped is False, "different SHA, must not skip"
    assert b.rows_read == 2
    assert b.rows_inserted == 1, "ON CONFLICT must drop the 08:00 duplicate"

    rows_after, files_after = _counts(engine)
    assert rows_after - rows_before == 3, "should be 3 unique (metric, source, start_ts) rows"
    assert files_after - files_before == 2, "both files registered despite row overlap"
