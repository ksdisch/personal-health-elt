"""Shared helpers for the loader idempotency contract.

The contract is two levels:

  1. File-level — `already_loaded` + `record_file`. A file whose SHA256
     is already in `raw.file_inventory` is skipped entirely on re-run.
  2. Row-level — `upsert_rows`. `ON CONFLICT (natural_key) DO NOTHING`
     drops duplicate rows when two different files carry overlapping
     samples (different SHAs, same natural-key tuple).

Each loader (quantities / categories / workouts) used to carry its own
copy of these four helpers; this module is their shared home. The
integration tests in `tests/test_idempotency_integration.py` pin the
contract end-to-end against a real Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection


def already_loaded(conn: Connection, sha: str) -> bool:
    """True iff a row with this SHA256 exists in `raw.file_inventory`."""
    row = conn.execute(
        text("SELECT 1 FROM raw.file_inventory WHERE sha256 = :sha"),
        {"sha": sha},
    ).first()
    return row is not None


def record_file(conn: Connection, sha: str, file_name: str) -> None:
    """Insert a `raw.file_inventory` row, `ON CONFLICT DO NOTHING`."""
    conn.execute(
        text(
            "INSERT INTO raw.file_inventory (sha256, file_name) "
            "VALUES (:sha, :file_name) "
            "ON CONFLICT (sha256) DO NOTHING"
        ),
        {"sha": sha, "file_name": file_name},
    )


def upsert_rows(
    conn: Connection,
    df: pd.DataFrame,
    *,
    table: str,
    index_elements: Sequence[str],
    schema: str = "raw",
) -> int:
    """`ON CONFLICT DO NOTHING` upsert on `schema.table`, keyed by
    `index_elements`. Returns the count of rows actually inserted.

    Empty DataFrames are a valid no-op — the enclosing transaction
    still records the file in `raw.file_inventory` so an empty CSV
    isn't re-parsed on every run.

    psycopg's executemany returns `rowcount=-1` for
    `ON CONFLICT DO NOTHING`, so we compute the delta via before/after
    `COUNT(*)`. Two extra small queries; the truthful count is worth it.

    Note: `schema` / `table` are interpolated into the COUNT SQL via
    f-string because `text()` can't parameterize identifiers. Both are
    only ever passed by trusted internal callers — never user input.
    """
    if df.empty:
        return 0

    metadata = MetaData()
    target = Table(table, metadata, schema=schema, autoload_with=conn)
    stmt = pg_insert(target).on_conflict_do_nothing(index_elements=list(index_elements))
    records = records_with_none_for_nan(df)

    count_sql = text(f"SELECT COUNT(*) FROM {schema}.{table}")
    before = conn.execute(count_sql).scalar_one()
    conn.execute(stmt, records)
    after = conn.execute(count_sql).scalar_one()
    return int(after - before)


def records_with_none_for_nan(df: pd.DataFrame) -> list[dict]:
    """Coerce pandas NaN to Python None so TEXT columns land as NULL,
    not the literal string 'NaN'."""
    return [
        {k: (None if pd.isna(v) else v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]
