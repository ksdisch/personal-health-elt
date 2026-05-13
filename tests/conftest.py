"""Shared pytest fixtures.

The `pg_engine` and `clean_raw_quantities` fixtures spin up against the
project's Postgres (docker compose locally, the CI service container in
GitHub Actions). Tests that depend on them skip gracefully when no
Postgres is reachable, so the existing unit test suite keeps running
on developer machines without docker compose up.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from ingest.config import DATABASE_URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_SCHEMA_SQL = PROJECT_ROOT / "scripts" / "init_raw_schema.sql"


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """Engine pointing at the test Postgres. Skips the test if unreachable.

    Also runs `scripts/init_raw_schema.sql` once per session so the raw
    schema and the three source tables exist before any integration
    test touches them. The script is idempotent (`IF NOT EXISTS`).
    """
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    with engine.begin() as conn:
        conn.execute(text(RAW_SCHEMA_SQL.read_text()))
    return engine


@pytest.fixture
def clean_raw_quantities(pg_engine: Engine) -> Engine:
    """Truncate the file ledger (CASCADE drops dependent raw.* rows too)
    before each test so integration tests start from a known state."""
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE raw.file_inventory CASCADE"))
    return pg_engine
