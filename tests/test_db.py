"""Unit tests for the unified Postgres connection helper.

DB-free — just exercises the caching contract on `get_engine()`. The
actual Postgres-roundtrip is covered by
`tests/test_idempotency_integration.py`'s `pg_engine` fixture, which
already routes through `get_engine()` after the connection-helper
refactor.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from ingest.db import get_engine


def test_get_engine_returns_same_instance_across_calls() -> None:
    """The `@lru_cache` decorator means repeated calls must return the
    SAME object. If a refactor accidentally drops the cache, the
    connection pool will get re-created on every call, defeating the
    purpose."""
    first = get_engine()
    second = get_engine()
    assert first is second


def test_get_engine_returns_sqlalchemy_engine() -> None:
    """Loaders + queries.py both type their `engine` parameter as
    `sqlalchemy.engine.Engine`. Lock the return type here so a future
    "drop SQLAlchemy" attempt doesn't silently break those signatures."""
    assert isinstance(get_engine(), Engine)
