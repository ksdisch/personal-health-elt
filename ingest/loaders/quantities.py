"""Loader for Apple Health quantity metrics.

Reads a HealthKit quantity CSV (as produced by SimpleHealthExport or
Health Auto Export) and lands rows in raw.quantities. Idempotent at two
levels:

1. File-level: a file whose SHA256 is already in raw.file_inventory is
   skipped entirely (fast path on re-exports).
2. Row-level: INSERT ... ON CONFLICT (metric_type, source_name, start_ts)
   DO NOTHING, so overlapping rows across files don't duplicate.

Both happen in a single transaction — rollback on any insert failure
leaves raw.file_inventory untouched so the next run retries cleanly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from ingest.config import DATABASE_URL
from ingest.file_inventory import hash_file

logger = logging.getLogger(__name__)

_HK_TO_SNAKE = {
    "type": "metric_type",
    "sourceName": "source_name",
    "sourceVersion": "source_version",
    "productType": "product_type",
    "device": "device",
    "startDate": "start_ts",
    "endDate": "end_ts",
    "unit": "unit",
    "value": "value",
}

_EXPECTED_COLUMNS = set(_HK_TO_SNAKE.values())


@dataclass(frozen=True)
class LoadResult:
    path: Path
    sha256: str
    rows_read: int
    rows_inserted: int
    skipped: bool


def parse_quantities_csv(path: Path) -> pd.DataFrame:
    """Read one HealthKit quantity CSV into a normalized DataFrame.

    - Strips the optional leading `sep=,` Excel hint.
    - Renames HK's camelCase columns to snake_case.
    - Parses timestamps as UTC (source format is ISO with +0000 offset).
    """
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    skiprows = 1 if first_line.startswith("sep=") else 0

    df = pd.read_csv(path, skiprows=skiprows)
    df = df.rename(columns=_HK_TO_SNAKE)

    missing = _EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"{path.name}: missing expected columns after rename: {sorted(missing)}"
        )

    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    return df[list(_EXPECTED_COLUMNS)]


def load_quantities_csv(path: Path, engine: Engine | None = None) -> LoadResult:
    """Load one quantity CSV into raw.quantities."""
    engine = engine or create_engine(DATABASE_URL)
    sha = hash_file(path)

    with engine.connect() as conn:
        if _already_loaded(conn, sha):
            logger.info("skip %s (sha=%s already loaded)", path.name, sha[:8])
            return LoadResult(
                path=path, sha256=sha, rows_read=0, rows_inserted=0, skipped=True
            )

    df = parse_quantities_csv(path)
    df = df.assign(source_file=path.name, source_sha256=sha)

    with engine.begin() as conn:
        _record_file(conn, sha, path.name)
        inserted = _upsert_rows(conn, df)

    logger.info(
        "loaded %s — read %d, inserted %d (sha=%s)",
        path.name, len(df), inserted, sha[:8],
    )
    return LoadResult(
        path=path,
        sha256=sha,
        rows_read=len(df),
        rows_inserted=inserted,
        skipped=False,
    )


def _already_loaded(conn: Connection, sha: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM raw.file_inventory WHERE sha256 = :sha"),
        {"sha": sha},
    ).first()
    return row is not None


def _record_file(conn: Connection, sha: str, file_name: str) -> None:
    conn.execute(
        text(
            "INSERT INTO raw.file_inventory (sha256, file_name) "
            "VALUES (:sha, :file_name) "
            "ON CONFLICT (sha256) DO NOTHING"
        ),
        {"sha": sha, "file_name": file_name},
    )


def _upsert_rows(conn: Connection, df: pd.DataFrame) -> int:
    """Upsert rows, returning the count actually inserted.

    psycopg's executemany returns rowcount=-1 for ON CONFLICT DO NOTHING, so
    we compute the delta via before/after counts. Two extra queries is cheap
    for weekly loads of small files, and the truthful count is worth more
    than the savings.
    """
    metadata = MetaData()
    quantities = Table("quantities", metadata, schema="raw", autoload_with=conn)
    stmt = pg_insert(quantities).on_conflict_do_nothing(
        index_elements=["metric_type", "source_name", "start_ts"]
    )
    records = _records_with_none_for_nan(df)

    count_sql = text("SELECT COUNT(*) FROM raw.quantities")
    before = conn.execute(count_sql).scalar_one()
    conn.execute(stmt, records)
    after = conn.execute(count_sql).scalar_one()
    return after - before


def _records_with_none_for_nan(df: pd.DataFrame) -> list[dict]:
    """pandas NaN in a TEXT column becomes the literal string 'NaN' in Postgres
    unless we coerce it to None first. Do that at the record boundary."""
    return [
        {k: (None if pd.isna(v) else v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]


def _main() -> None:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m ingest.loaders.quantities <path-to-csv>")
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_quantities_csv(Path(sys.argv[1]))
    print(f"file:        {result.path.name}")
    print(f"sha256:      {result.sha256}")
    if result.skipped:
        print("status:      SKIPPED (already loaded)")
    else:
        print(f"rows read:   {result.rows_read}")
        print(f"rows insert: {result.rows_inserted}")


if __name__ == "__main__":
    _main()
