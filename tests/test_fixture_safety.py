"""Regression test for the `raw_test_engine` safety contract.

The fixture promises: a row that existed in `raw.file_inventory` BEFORE
the test runs (and any dependent rows in raw.{quantities,workouts,
categories} that reference it) MUST survive the fixture's teardown.

If this test ever fails, real Apple Health export data is at risk of
being silently wiped during routine `uv run pytest` runs — exactly the
regression that motivated the original fix (BACKLOG "[Bug]
clean_raw_quantities ... wipes user's local Postgres", 2026-05-13).

The test calls `cleanup_introduced_shas` directly rather than going
through the fixture, because asserting `state-after-teardown` from
inside a yield fixture's test body isn't possible — the teardown runs
after the test function returns.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.conftest import cleanup_introduced_shas

# Synthetic 64-hex SHAs so they cannot collide with a real CSV's SHA256.
_PRE_EXISTING_SHA = "1" * 64
_TEST_INTRODUCED_SHA = "2" * 64


def test_cleanup_preserves_pre_existing_rows(pg_engine: Engine) -> None:
    """Plant a pre-existing SHA + dependent row, simulate the fixture
    lifecycle by capturing a snapshot and then introducing more rows,
    run the cleanup, and assert the pre-existing data survived while
    the test-introduced data was removed.
    """
    engine = pg_engine

    try:
        # Plant "pre-existing" data (as if a real Apple Health load had
        # populated these tables before the test session started).
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw.file_inventory (sha256, file_name) "
                    "VALUES (:s, :n) ON CONFLICT DO NOTHING"
                ),
                {"s": _PRE_EXISTING_SHA, "n": "sentinel_pre_existing.csv"},
            )
            conn.execute(
                text(
                    "INSERT INTO raw.quantities "
                    "(metric_type, source_name, start_ts, value, "
                    " source_file, source_sha256) "
                    "VALUES (:mt, :sn, :ts, :v, :sf, :sha) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "mt": "HKSentinelPreExisting",
                    "sn": "fixture-safety-test",
                    "ts": "2098-01-01 00:00:00+0000",
                    "v": 42.0,
                    "sf": "sentinel_pre_existing.csv",
                    "sha": _PRE_EXISTING_SHA,
                },
            )

        # Snapshot SHAs — this is what `raw_test_engine` does on setup.
        # The pre-existing sha is in the snapshot, so the cleanup should
        # treat it as "already there" and leave it alone.
        with engine.connect() as conn:
            before_shas = [
                row[0] for row in conn.execute(text("SELECT sha256 FROM raw.file_inventory"))
            ]
        assert _PRE_EXISTING_SHA in before_shas, (
            "test setup failed: pre-existing sha was not staged"
        )

        # Now plant "test-introduced" data — what a real integration
        # test would insert via the loader.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw.file_inventory (sha256, file_name) "
                    "VALUES (:s, :n) ON CONFLICT DO NOTHING"
                ),
                {"s": _TEST_INTRODUCED_SHA, "n": "sentinel_test_introduced.csv"},
            )
            conn.execute(
                text(
                    "INSERT INTO raw.quantities "
                    "(metric_type, source_name, start_ts, value, "
                    " source_file, source_sha256) "
                    "VALUES (:mt, :sn, :ts, :v, :sf, :sha) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "mt": "HKSentinelTestIntroduced",
                    "sn": "fixture-safety-test",
                    "ts": "2099-01-01 00:00:00+0000",
                    "v": 99.0,
                    "sf": "sentinel_test_introduced.csv",
                    "sha": _TEST_INTRODUCED_SHA,
                },
            )

        # Trigger the teardown logic.
        cleanup_introduced_shas(engine, before_shas)

        # Pre-existing rows MUST survive.
        with engine.connect() as conn:
            pre_file = conn.execute(
                text("SELECT COUNT(*) FROM raw.file_inventory WHERE sha256 = :s"),
                {"s": _PRE_EXISTING_SHA},
            ).scalar_one()
            pre_rows = conn.execute(
                text("SELECT COUNT(*) FROM raw.quantities WHERE source_sha256 = :s"),
                {"s": _PRE_EXISTING_SHA},
            ).scalar_one()
        assert pre_file == 1, "pre-existing file_inventory row was wiped — fixture is destructive"
        assert pre_rows == 1, "pre-existing raw.quantities row was wiped — dependent rows lost"

        # Test-introduced rows MUST have been cleaned up.
        with engine.connect() as conn:
            tmi_file = conn.execute(
                text("SELECT COUNT(*) FROM raw.file_inventory WHERE sha256 = :s"),
                {"s": _TEST_INTRODUCED_SHA},
            ).scalar_one()
            tmi_rows = conn.execute(
                text("SELECT COUNT(*) FROM raw.quantities WHERE source_sha256 = :s"),
                {"s": _TEST_INTRODUCED_SHA},
            ).scalar_one()
        assert tmi_file == 0, "test-introduced file_inventory row leaked"
        assert tmi_rows == 0, "test-introduced raw.quantities row leaked"

    finally:
        # Always remove the sentinel data so subsequent tests start
        # clean. Order matters: dependent rows first (no ON DELETE
        # CASCADE on the FK).
        with engine.begin() as conn:
            for sha in (_PRE_EXISTING_SHA, _TEST_INTRODUCED_SHA):
                conn.execute(
                    text("DELETE FROM raw.quantities WHERE source_sha256 = :s"),
                    {"s": sha},
                )
                conn.execute(
                    text("DELETE FROM raw.file_inventory WHERE sha256 = :s"),
                    {"s": sha},
                )


def test_cleanup_empty_snapshot_truncates(pg_engine: Engine) -> None:
    """When `before_shas` is empty, cleanup TRUNCATEs everything.

    This is the CI-equivalent path — CI starts each session with an
    empty `raw.file_inventory` (`init_raw_schema.sql` is idempotent
    and creates the tables but inserts nothing). When a test runs in
    that environment, every row in the tables at teardown time is
    test-introduced and should be wiped. The branch also sidesteps
    psycopg3's empty-array element-type-inference issue.

    SAFETY: this test exercises the TRUNCATE branch of
    `cleanup_introduced_shas`. Running it against a populated local
    Postgres would silently wipe the developer's real Apple Health
    export data — exactly the failure mode the snapshot/restore design
    is supposed to prevent. We skip when the table isn't already empty.
    CI satisfies the precondition naturally (init script creates empty
    tables); a dev who wants the assertion can wipe their local raw.*
    explicitly first.
    """
    engine = pg_engine

    with engine.connect() as conn:
        existing_rows = conn.execute(text("SELECT count(*) FROM raw.file_inventory")).scalar_one()
    if existing_rows > 0:
        pytest.skip(
            f"raw.file_inventory has {existing_rows} rows; refusing to TRUNCATE "
            "in a test against a populated local database. Run in CI or wipe "
            "raw.* manually first if you need this assertion."
        )

    sentinel_sha = "3" * 64
    try:
        # Stage one row, then run cleanup with an empty snapshot.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw.file_inventory (sha256, file_name) "
                    "VALUES (:s, :n) ON CONFLICT DO NOTHING"
                ),
                {"s": sentinel_sha, "n": "empty_snapshot_sentinel.csv"},
            )

        cleanup_introduced_shas(engine, before_shas=[])

        # TRUNCATE wipes everything — sentinel included.
        with engine.connect() as conn:
            remaining = conn.execute(
                text("SELECT COUNT(*) FROM raw.file_inventory WHERE sha256 = :s"),
                {"s": sentinel_sha},
            ).scalar_one()
        assert remaining == 0, "empty-snapshot cleanup should TRUNCATE the sentinel away"

    finally:
        # Defensive: in case TRUNCATE missed (it can't, but cheap).
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM raw.file_inventory WHERE sha256 = :s"),
                {"s": sentinel_sha},
            )
