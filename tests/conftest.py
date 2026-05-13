"""Shared pytest fixtures.

The `pg_engine` and `raw_test_engine` fixtures spin up against the
project's Postgres (docker compose locally, the CI service container in
GitHub Actions). Tests that depend on them skip gracefully when no
Postgres is reachable, so the existing unit test suite keeps running
on developer machines without docker compose up.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
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
def raw_test_engine(pg_engine: Engine) -> Iterator[Engine]:
    """Engine for integration tests with non-destructive per-test cleanup.

    Snapshots the file_inventory SHAs that exist BEFORE the test, then
    on teardown deletes only the SHAs the test introduced — and the
    dependent rows in raw.quantities/workouts/categories that reference
    those SHAs. Anything that was in the database before the test runs
    is preserved.

    Why this exists: the previous `clean_raw_quantities` fixture did a
    blanket `TRUNCATE raw.file_inventory CASCADE` on every test, which
    silently destroyed real Apple Health export data during routine
    `uv run pytest` runs against a dev's local Postgres. The session-end
    cleanup is already CI-gated; this fixture extends the same safety
    guarantee to per-test setup so integration tests are safe to run
    against a populated local database.
    """
    with pg_engine.connect() as conn:
        before_shas = [
            row[0] for row in conn.execute(text("SELECT sha256 FROM raw.file_inventory"))
        ]

    yield pg_engine

    if not before_shas:
        # Table was empty when the test started, so everything in it
        # now is test-introduced. TRUNCATE CASCADE is the simplest
        # catch-all and avoids passing an empty array to psycopg3
        # (which can't infer the element type without a value).
        with pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE raw.file_inventory CASCADE"))
        return

    with pg_engine.begin() as conn:
        params = {"before": before_shas}
        conn.execute(
            text("DELETE FROM raw.quantities WHERE source_sha256 <> ALL(:before)"),
            params,
        )
        conn.execute(
            text("DELETE FROM raw.workouts WHERE source_sha256 <> ALL(:before)"),
            params,
        )
        conn.execute(
            text("DELETE FROM raw.categories WHERE source_sha256 <> ALL(:before)"),
            params,
        )
        conn.execute(
            text("DELETE FROM raw.file_inventory WHERE sha256 <> ALL(:before)"),
            params,
        )


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
