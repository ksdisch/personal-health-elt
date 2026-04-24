"""Loader for Apple Health workouts (runs, rides, lifts, yoga, ...).

Reads an HKWorkoutActivityType*.csv and lands rows in raw.workouts.

The SimpleHealthExport shape for workouts is gnarly in two spots:
1. Unit-embedded string values — `totalEnergyBurned` is "659.283 kcal",
   `totalDistance` is "9688.1 m", `HKMaximumSpeed` is "4.82924 m/s".
   We parse the numeric prefix; we trust that units are consistent per
   column across the export (they are — HealthKit exports SI-normalized).
2. Some columns are absent in files for activity types that don't record
   them (e.g. Yoga has no distance). The loader tolerates missing columns
   and maps them to NULL.

Idempotency matches the quantities loader: file-hash skip + ON CONFLICT
DO NOTHING at the natural key, both in a single transaction.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from ingest.config import DATABASE_URL
from ingest.file_inventory import hash_file

logger = logging.getLogger(__name__)

# Columns we keep, mapped from HK's camelCase to our snake_case schema.
# Anything not here is dropped; anything missing from a given CSV is NULL.
_HK_TO_SNAKE = {
    "sourceName": "source_name",
    "sourceVersion": "source_version",
    "productType": "product_type",
    "startDate": "start_ts",
    "endDate": "end_ts",
    "activityType": "activity_type",
    "duration": "duration_sec",
    "totalEnergyBurned": "total_energy_kcal",
    "totalDistance": "total_distance_m",
    "HKElevationAscended": "elevation_asc_m",
    "HKElevationDescended": "elevation_desc_m",
    "HKMaximumSpeed": "max_speed_mps",
    "HKIndoorWorkout": "indoor",
}

# Columns whose raw value looks like "659.283 kcal" / "8 m" / "4.82924 m/s".
# We keep only the numeric prefix.
_UNIT_EMBEDDED_COLS = {
    "total_energy_kcal",
    "total_distance_m",
    "elevation_asc_m",
    "elevation_desc_m",
    "max_speed_mps",
}

# Final column order for the insert — matches raw.workouts definition.
_TARGET_COLUMNS = [
    "activity_type",
    "source_name",
    "source_version",
    "product_type",
    "start_ts",
    "end_ts",
    "duration_sec",
    "total_energy_kcal",
    "total_distance_m",
    "elevation_asc_m",
    "elevation_desc_m",
    "max_speed_mps",
    "indoor",
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


_NUMERIC_PREFIX = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def _numeric_prefix(value: object) -> float | None:
    """Return the leading float from a value, or None if not parseable."""
    if pd.isna(value):
        return None
    match = _NUMERIC_PREFIX.match(str(value))
    return float(match.group(1)) if match else None


def parse_workouts_csv(path: Path) -> pd.DataFrame:
    """Read one HK workout CSV into a normalized DataFrame.

    - Strips the optional `sep=,` Excel hint.
    - Renames camelCase columns; drops HK internals we don't use.
    - Parses unit-embedded numeric fields.
    - Coerces `HKIndoorWorkout` (0/1/"") to bool/None.
    - Ensures all target columns exist (missing ones become NaN).
    """
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    skiprows = 1 if first_line.startswith("sep=") else 0

    df = pd.read_csv(path, skiprows=skiprows)
    df = df.rename(columns=_HK_TO_SNAKE)

    # Keep only known target cols; add any missing as NaN.
    for col in _HK_TO_SNAKE.values():
        if col not in df.columns:
            df[col] = pd.NA

    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)

    for col in _UNIT_EMBEDDED_COLS:
        df[col] = df[col].apply(_numeric_prefix)

    df["indoor"] = df["indoor"].apply(_coerce_bool)

    return df[list(_HK_TO_SNAKE.values())]


def _coerce_bool(value: object) -> bool | None:
    if pd.isna(value) or value == "":
        return None
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None


def load_workouts_csv(path: Path, engine: Engine | None = None) -> LoadResult:
    """Load one HK workout CSV into raw.workouts."""
    engine = engine or create_engine(DATABASE_URL)
    sha = hash_file(path)

    with engine.connect() as conn:
        if _already_loaded(conn, sha):
            logger.info("skip %s (sha=%s already loaded)", path.name, sha[:8])
            return LoadResult(
                path=path, sha256=sha, rows_read=0, rows_inserted=0, skipped=True
            )

    df = parse_workouts_csv(path)
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

    Empty DataFrames are a valid no-op — many HK workout files are
    header-only for activity types the user has never done.
    """
    if df.empty:
        return 0

    metadata = MetaData()
    workouts = Table("workouts", metadata, schema="raw", autoload_with=conn)
    stmt = pg_insert(workouts).on_conflict_do_nothing(
        index_elements=["activity_type", "source_name", "start_ts"]
    )
    records = _records_with_none_for_nan(df)

    count_sql = text("SELECT COUNT(*) FROM raw.workouts")
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
        print("usage: python -m ingest.loaders.workouts <path-to-csv>")
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_workouts_csv(Path(sys.argv[1]))
    print(f"file:        {result.path.name}")
    print(f"sha256:      {result.sha256}")
    if result.skipped:
        print("status:      SKIPPED (already loaded)")
    else:
        print(f"rows read:   {result.rows_read}")
        print(f"rows insert: {result.rows_inserted}")


if __name__ == "__main__":
    _main()
