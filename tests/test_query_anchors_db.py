"""DB-backed regression test for the Query page's NL→SQL few-shot anchors.

The pure tests in ``test_query.py`` prove each ``QUERY_FEWSHOT`` anchor passes
the ``validate_sql`` AST gate — but a query can be structurally valid and still
fail at runtime. The classic trap on this warehouse is Postgres having no
``ROUND(double precision, int)``, so ``round(AVG(x), 1)`` raises
``UndefinedFunction`` unless the argument is cast (``round(AVG(x)::numeric, 1)``).
The anchors are few-shot teaching examples fed into the prompt; a runtime-broken
anchor teaches Claude a query the page would reject in production. This module
closes that gap by EXECUTING every anchor against the populated synthetic
warehouse.

We assert the query executes and returns columns — NOT a row count. That keeps
the test decoupled from the synthetic corpus: e.g. ``mart_sleep_nights`` is empty
in ``health_demo`` (the synth corpus carries no sleep), so the sleep-efficiency
anchor legitimately returns 0 rows while still proving the SQL is valid against
the live schema.

Preconditions: the ``health_demo`` warehouse must be built first —

    uv run python -m ingest.flows.make_demo_db

Like the golden tests, this SKIPS (not fails) when ``health_demo`` is unreachable
or unbuilt, so a bare ``uv run pytest`` on a fresh clone stays green; CI builds
the demo first.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.lib.queries import MART_SCHEMA, QUERY_FEWSHOT, _add_limit_if_missing, validate_sql
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
    range(len(QUERY_FEWSHOT)),
    ids=[req[:40] for req, _ in QUERY_FEWSHOT],
)
def test_anchor_executes_against_marts(demo_built, idx: int) -> None:
    """Every few-shot anchor validates AND runs against the live mart schema.

    Asserts execution succeeds (raises on the ROUND-on-double bug class) and
    returns the expected shape. We deliberately do NOT assert a row count —
    that would couple the test to the synthetic corpus — only that the query
    runs and yields columns.
    """
    request, sql = QUERY_FEWSHOT[idx]

    validation = validate_sql(sql)
    assert validation.ok, f"anchor {request!r} failed validate_sql: {validation.error}"

    safe_sql = _add_limit_if_missing(sql)
    with demo_built.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
        df = pd.read_sql(text(safe_sql), conn)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns), f"anchor {request!r} returned no columns"
