"""Safety regression for the ``make_demo_db`` isolation guard.

The demo flow exists to build a fully-synthetic warehouse in ``health_demo``
WITHOUT ever touching the dev's real ``health`` database (676k+ real rows).
``assert_demo_engine`` is the hard guard that enforces this: every step of the
flow calls it before writing. If this test fails, the guard has regressed and
synthetic data could be written into real Apple Health data — the same class
of bug as the original ``clean_raw_quantities`` wipe.

These checks construct Engines but never connect, so they run anywhere (no
Postgres required).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from ingest.flows.make_demo_db import (
    DEMO_DB,
    REAL_DB,
    _url_for,
    assert_demo_engine,
    demo_engine,
)


def test_demo_url_targets_health_demo() -> None:
    assert _url_for(DEMO_DB).endswith("/health_demo")
    assert DEMO_DB != REAL_DB
    assert demo_engine().url.database == DEMO_DB


def test_guard_rejects_real_database() -> None:
    """The guard MUST refuse an engine pointed at the real ``health`` DB."""
    real = create_engine(_url_for(REAL_DB))
    with pytest.raises(RuntimeError, match="refusing to run demo load"):
        assert_demo_engine(real)


@pytest.mark.parametrize("dbname", ["health", "postgres", "prod", "analytics"])
def test_guard_rejects_any_non_demo_database(dbname: str) -> None:
    engine = create_engine(_url_for(dbname))
    with pytest.raises(RuntimeError):
        assert_demo_engine(engine)


def test_guard_accepts_demo_database() -> None:
    assert_demo_engine(create_engine(_url_for(DEMO_DB)))  # must not raise
