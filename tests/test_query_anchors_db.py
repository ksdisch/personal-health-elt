"""DB-backed regression test for the Query page's NL→SQL anchors.

The pure tests in ``test_query_page.py`` prove each anchor passes the
``validate_sql`` AST gate — but a query can be structurally valid and still
fail at runtime (e.g. Postgres has no ``ROUND(double precision, int)``, so
``ROUND(AVG(x), 1)`` raises ``UndefinedFunction``). The anchors are few-shot
teaching examples; a runtime-broken anchor teaches Claude a query the page
would reject in production. This module closes that gap by EXECUTING every
anchor against the populated synthetic warehouse.

Preconditions: the ``health_demo`` warehouse must be built first —

    uv run python -m ingest.flows.make_demo_db

Like the golden tests, this SKIPS (not fails) when ``health_demo`` is
unreachable or unbuilt, so a bare ``uv run pytest`` on a fresh clone stays
green; CI builds the demo first.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.lib.queries import MART_SCHEMA, NL_SQL_FEWSHOT, _add_limit_if_missing, validate_sql
from ingest.flows.make_demo_db import DEMO_DB, demo_engine


def _engine_or_skip():
    try:
        engine = demo_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"{DEMO_DB} unreachable: {exc}")


@pytest.fixture(scope="module")
def demo_built():
    """Skip the whole module unless health_demo has marts built."""
    engine = _engine_or_skip()
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {MART_SCHEMA}.mart_recovery_state LIMIT 1"))
    except (OperationalError, ProgrammingError):
        pytest.skip(f"{DEMO_DB} not built — run `uv run python -m ingest.flows.make_demo_db` first")
    return engine


@pytest.mark.parametrize(
    "idx",
    range(len(NL_SQL_FEWSHOT)),
    ids=[nl[:40] for nl, _ in NL_SQL_FEWSHOT],
)
def test_anchor_executes_against_marts(demo_built, idx: int) -> None:
    """Every few-shot anchor validates AND runs against the live mart schema.

    Asserts execution succeeds (raises on the ROUND-on-double bug class) and
    returns the expected shape. We deliberately do NOT assert a row count —
    that would couple the test to the synthetic corpus — only that the query
    runs and yields columns.
    """
    nl, sql = NL_SQL_FEWSHOT[idx]

    validation = validate_sql(sql)
    assert validation.ok, f"anchor {nl!r} failed validate_sql: {validation.error}"

    safe_sql = _add_limit_if_missing(sql)
    with demo_built.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
        df = pd.read_sql(text(safe_sql), conn)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns), f"anchor {nl!r} returned no columns"
