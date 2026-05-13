"""Shared pytest fixtures.

The `pg_engine` and `clean_raw_quantities` fixtures spin up against the
project's Postgres (docker compose locally, the CI service container in
GitHub Actions). Tests that depend on them skip gracefully when no
Postgres is reachable, so the existing unit test suite keeps running
on developer machines without docker compose up.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from ingest.db import get_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_SCHEMA_SQL = PROJECT_ROOT / "scripts" / "init_raw_schema.sql"


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """Engine pointing at the test Postgres. Skips the test if unreachable.

    Also runs `scripts/init_raw_schema.sql` once per session so the raw
    schema and the three source tables exist before any integration
    test touches them. The script is idempotent (`IF NOT EXISTS`).
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable: {exc}")

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


@pytest.fixture(scope="session", autouse=True)
def _cleanup_raw_at_session_end(pg_engine: Engine):
    """Wipe raw.* once the whole session finishes — CI ONLY.

    CI runs `pytest` and `dbt build` in the same job against the same
    Postgres service container. Without cleanup, the last integration
    test's data would leak into dbt build and the marts would process
    a tiny synthetic dataset instead of an empty one. Keeps the dbt
    build step honest as a smoke test of model SQL compilation.

    Gated on the `CI` env var (set automatically by GitHub Actions) so
    a developer running `uv run pytest` locally against their docker
    compose Postgres does NOT have their real export data wiped at the
    end of every test session. Local devs who genuinely want the wipe
    can opt in with `CI=true uv run pytest`.
    """
    yield
    if os.environ.get("CI", "").lower() != "true":
        return
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE raw.file_inventory CASCADE"))
