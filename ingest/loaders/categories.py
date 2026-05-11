"""Loader for Apple Health category metrics.

Covers sleep stages, mindful sessions, audio events, AppleStandHour, and HR
threshold events. Lands rows in raw.categories.

The HK shape for categories is mostly uniform — `type`, `value`, and
timestamps — but two columns are conditional on the category subtype:
1. `HKTimeZone` appears on sleep rows (e.g. "America/Phoenix").
2. `HKHeartRateEventThreshold` appears on HR threshold rows
   (e.g. "120 count/min").

The loader tolerates missing optional columns and lands them as NULL.

Idempotency matches the quantities/workouts loaders: file-hash skip +
ON CONFLICT DO NOTHING at the natural key, both in a single transaction.
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

# HK camelCase -> snake_case. `value` becomes `category_value` so we don't
# clash with the more generic `value` column in raw.quantities.
_HK_TO_SNAKE = {
    "type": "category_type",
    "value": "category_value",
    "sourceName": "source_name",
    "sourceVersion": "source_version",
    "productType": "product_type",
    "device": "device",
    "startDate": "start_ts",
    "endDate": "end_ts",
    "HKTimeZone": "hk_time_zone",
    "HKHeartRateEventThreshold": "hk_heart_rate_threshold",
}

# Required after rename; ValueError if any of these are missing.
_REQUIRED_COLUMNS = {"category_type", "source_name", "start_ts"}

# Final column order for the insert — matches raw.categories definition.
_TARGET_COLUMNS = [
    "category_type",
    "category_value",
    "source_name",
    "source_version",
    "product_type",
    "device",
    "start_ts",
    "end_ts",
    "hk_time_zone",
    "hk_heart_rate_threshold",
    "source_file",
    "source_sha256",
]


@dataclass(frozen=True)
class LoadResult:
    path: Path
    sha256: str
    rows_read: int
    rows_inserted: int
    skipped: bool


def parse_categories_csv(path: Path) -> pd.DataFrame:
    """Read one HK category CSV into a normalized DataFrame.

    - Strips the optional `sep=,` Excel hint.
    - Renames camelCase columns to snake_case.
    - Raises if a required column is missing; tolerates missing optionals
      (HKTimeZone, HKHeartRateEventThreshold, end_ts, etc.) and lands
      them as NaN so they coerce to NULL at the boundary.
    - Parses `start_ts` / `end_ts` as UTC-aware pandas Timestamps.
    """
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    skiprows = 1 if first_line.startswith("sep=") else 0

    df = pd.read_csv(path, skiprows=skiprows)
    df = df.rename(columns=_HK_TO_SNAKE)

    missing_required = _REQUIRED_COLUMNS - set(df.columns)
    if missing_required:
        raise ValueError(
            f"{path.name}: missing required columns after rename: {sorted(missing_required)}"
        )

    # Add any missing target columns as NaN so the schema is uniform.
    for col in _HK_TO_SNAKE.values():
        if col not in df.columns:
            df[col] = pd.NA

    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)

    return df[list(_HK_TO_SNAKE.values())]


def load_categories_csv(path: Path, engine: Engine | None = None) -> LoadResult:
    """Load one HK category CSV into raw.categories."""
    engine = engine or create_engine(DATABASE_URL)
    sha = hash_file(path)

    with engine.connect() as conn:
        if _already_loaded(conn, sha):
            logger.info("skip %s (sha=%s already loaded)", path.name, sha[:8])
            return LoadResult(
                path=path, sha256=sha, rows_read=0, rows_inserted=0, skipped=True
            )

    df = parse_categories_csv(path)
    df = df.assign(source_file=path.name, source_sha256=sha)
    df = df[_TARGET_COLUMNS]

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

    Empty DataFrames are a valid no-op — many HK category files are
    header-only for events the user has never recorded.
    """
    if df.empty:
        return 0

    metadata = MetaData()
    categories = Table("categories", metadata, schema="raw", autoload_with=conn)
    stmt = pg_insert(categories).on_conflict_do_nothing(
        index_elements=["category_type", "source_name", "start_ts"]
    )
    records = _records_with_none_for_nan(df)

    count_sql = text("SELECT COUNT(*) FROM raw.categories")
    before = conn.execute(count_sql).scalar_one()
    conn.execute(stmt, records)
    after = conn.execute(count_sql).scalar_one()
    return after - before


def _records_with_none_for_nan(df: pd.DataFrame) -> list[dict]:
    """Coerce pandas NaN to None so TEXT columns land as NULL, not 'NaN'."""
    return [
        {k: (None if pd.isna(v) else v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]


def _main() -> None:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m ingest.loaders.categories <path-to-csv>")
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_categories_csv(Path(sys.argv[1]))
    print(f"file:        {result.path.name}")
    print(f"sha256:      {result.sha256}")
    if result.skipped:
        print("status:      SKIPPED (already loaded)")
    else:
        print(f"rows read:   {result.rows_read}")
        print(f"rows insert: {result.rows_inserted}")


if __name__ == "__main__":
    _main()
