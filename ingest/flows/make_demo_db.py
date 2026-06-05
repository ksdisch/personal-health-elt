"""Stand up an isolated, fully-synthetic demo warehouse in ``health_demo``.

This is the **autonomy substrate**: it lets a fresh agent build the entire
17-mart warehouse from a bare clone with no iOS export and no credentials, so
every downstream verification leg becomes a headless machine assertion.

Pipeline:

1. Create the ``health_demo`` database (if absent) + bootstrap ``raw.*`` from
   ``scripts/init_raw_schema.sql``.
2. Generate a deterministic synthetic corpus (``ingest.synth``).
3. Load the HK CSVs via the **real** loaders, with an **explicit demo engine**
   (never ``get_engine()``) — and insert weather/calendar directly.
4. ``dbt build`` against ``health_demo`` via a subprocess whose only env change
   is ``POSTGRES_DB=health_demo``.

Safety: the dev DB ``health`` holds real data. Loading uses explicit engine
injection (sidestepping the ``@lru_cache`` import-time ``DATABASE_URL``), and a
hard guard refuses to run unless the resolved engine points at ``/health_demo``.
``tests/test_demo_db_safety.py`` pins that guard.

    uv run python -m ingest.flows.make_demo_db            # build it
    uv run python -m ingest.flows.make_demo_db --no-dbt   # load only
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from prefect import flow, get_run_logger
from prefect.exceptions import MissingContextError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ingest.config import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from ingest.loaders._idempotency import record_file, upsert_rows
from ingest.loaders.batch import load_folder
from ingest.synth import generate_corpus

DEMO_DB = "health_demo"
REAL_DB = "health"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_SCHEMA_SQL = PROJECT_ROOT / "scripts" / "init_raw_schema.sql"
_STDERR_TAIL_LINES = 40

logger = logging.getLogger(__name__)


def _logger():
    try:
        return get_run_logger()
    except MissingContextError:
        return logger


# --------------------------------------------------------------------------- #
# Safety guard — the one thing standing between the demo and the real DB
# --------------------------------------------------------------------------- #
def _url_for(dbname: str) -> str:
    return (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{dbname}"
    )


def assert_demo_engine(engine: Engine) -> None:
    """Refuse to proceed unless ``engine`` points at the demo database.

    The whole point of this flow is to never touch the real ``health`` DB. If
    the resolved database name is anything other than ``health_demo`` we raise
    rather than risk writing synthetic rows into real data.
    """
    name = engine.url.database
    if name != DEMO_DB:
        raise RuntimeError(
            f"refusing to run demo load against database {name!r} — "
            f"expected {DEMO_DB!r}. (Never point this flow at {REAL_DB!r}.)"
        )


def demo_engine() -> Engine:
    """An explicit Engine bound to ``health_demo`` (not the cached default)."""
    engine = create_engine(_url_for(DEMO_DB))
    assert_demo_engine(engine)
    return engine


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def ensure_demo_database() -> None:
    """Create ``health_demo`` if it doesn't exist (idempotent)."""
    log = _logger()
    maint = create_engine(_url_for("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with maint.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": DEMO_DB}
            ).first()
            if exists:
                log.info("database %s already exists", DEMO_DB)
                return
            conn.execute(text(f'CREATE DATABASE "{DEMO_DB}" OWNER "{POSTGRES_USER}"'))
            log.info("created database %s", DEMO_DB)
    finally:
        maint.dispose()


def bootstrap_and_reset(engine: Engine, *, reset: bool) -> None:
    """Run the raw-schema bootstrap and (optionally) wipe raw.* for a clean build."""
    assert_demo_engine(engine)
    log = _logger()
    with engine.begin() as conn:
        conn.execute(text(RAW_SCHEMA_SQL.read_text()))
    if reset:
        with engine.begin() as conn:
            # file_inventory CASCADEs to quantities/workouts/categories/calendar.
            conn.execute(text("TRUNCATE raw.file_inventory CASCADE"))
            conn.execute(text("TRUNCATE raw.weather"))
        log.info("reset raw.* in %s", DEMO_DB)


def load_corpus(engine: Engine, *, seed: int, scenario: str) -> dict:
    """Generate + load a synthetic corpus into the demo DB. Returns a summary."""
    assert_demo_engine(engine)
    log = _logger()
    with tempfile.TemporaryDirectory(prefix="health_synth_") as tmp:
        manifest = generate_corpus(tmp, seed=seed, scenario=scenario)

        batch = load_folder(manifest.csv_dir, engine=engine)

        # Weather / calendar loaders are credential-gated and not routed by
        # batch.py, so insert their rows directly — via the same ON CONFLICT
        # upsert helper the real loaders use, so re-running the flow is a no-op
        # (the idempotency contract holds for enrichment too). Calendar rows FK
        # to file_inventory, so record the synthetic SHA first.
        with engine.begin() as conn:
            record_file(conn, manifest.calendar_sha, "synthetic_calendar.ics")
            weather_inserted = upsert_rows(
                conn,
                manifest.weather,
                table="weather",
                index_elements=["obs_date", "lat", "lon"],
            )
            calendar_inserted = upsert_rows(
                conn,
                manifest.calendar,
                table="calendar_daily",
                index_elements=["day", "source_sha256"],
            )

        summary = {
            "scenario": manifest.scenario,
            "date_range": [str(manifest.start_date), str(manifest.end_date)],
            "csv_rows_inserted": batch.total_rows_inserted,
            "files_loaded": batch.files_loaded,
            "files_already_loaded": batch.files_already_loaded,
            "files_errored": len(batch.errors),
            "weather_rows_inserted": weather_inserted,
            "calendar_rows_inserted": calendar_inserted,
        }
        log.info("loaded synthetic corpus: %s", summary)
        if batch.errors:
            raise RuntimeError(f"loader errors: {batch.errored_metric_types()}")
        return summary


def run_dbt_build_demo() -> int:
    """``dbt build`` against ``health_demo`` (subprocess; only env change is the DB)."""
    log = _logger()
    env = os.environ.copy()
    env["POSTGRES_DB"] = DEMO_DB
    cmd = [
        "uv",
        "run",
        "dbt",
        "build",
        "--project-dir",
        str(PROJECT_ROOT / "transform"),
        "--profiles-dir",
        str(PROJECT_ROOT / "transform"),
    ]
    log.info("Running (POSTGRES_DB=%s): %s", DEMO_DB, " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=PROJECT_ROOT, env=env, check=False, capture_output=True, text=True
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-_STDERR_TAIL_LINES:])
        err = "\n".join((proc.stderr or "").splitlines()[-_STDERR_TAIL_LINES:])
        log.error(
            "dbt build failed (rc=%s).\nstdout tail:\n%s\nstderr tail:\n%s",
            proc.returncode,
            tail,
            err,
        )
        raise RuntimeError(f"dbt build (health_demo) failed with rc={proc.returncode}")
    log.info("dbt build (health_demo) succeeded")
    return 0


# --------------------------------------------------------------------------- #
# Flow
# --------------------------------------------------------------------------- #
@flow(name="make_demo_db")
def make_demo_db(
    *, seed: int = 0, scenario: str = "full", reset: bool = True, run_dbt: bool = True
) -> dict:
    """Build the isolated synthetic demo warehouse end to end."""
    log = _logger()
    ensure_demo_database()
    engine = demo_engine()
    try:
        bootstrap_and_reset(engine, reset=reset)
        summary = load_corpus(engine, seed=seed, scenario=scenario)
    finally:
        engine.dispose()
    if run_dbt:
        run_dbt_build_demo()
        summary["dbt_build"] = "ok"
    log.info("demo warehouse ready: %s", summary)
    return summary


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build the synthetic health_demo warehouse.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scenario", default="full")
    parser.add_argument("--no-reset", action="store_true", help="don't wipe raw.* first")
    parser.add_argument("--no-dbt", action="store_true", help="load only; skip dbt build")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    make_demo_db(
        seed=args.seed, scenario=args.scenario, reset=not args.no_reset, run_dbt=not args.no_dbt
    )


if __name__ == "__main__":
    _main()
