"""Golden-snapshot regression tests for the marts, over synthetic data.

This is warehouse regression testing — not unit-testing a function, but
freezing the *output* of every mart built from the deterministic synthetic
corpus and asserting it never drifts unexpectedly. A behaviour-changing edit to
any mart's SQL flips the relevant golden RED; an intended change is re-baselined
explicitly with ``UPDATE_GOLDEN=1``.

Preconditions: the ``health_demo`` warehouse must be built first —

    uv run python -m ingest.flows.make_demo_db

The tests SKIP (not fail) when ``health_demo`` is unreachable or unbuilt, so a
bare ``uv run pytest`` on a fresh clone stays green; CI builds the demo first.

Determinism: the corpus is anchored to fixed 2024 dates, so ``current_date``-
relative logic is stable; we additionally EXCLUDE explicitly time-dependent
columns (e.g. ``mart_recovery_state.is_today``) from each snapshot, and round
floats to 6 dp to avoid representation drift.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ingest.flows.make_demo_db import DEMO_DB, demo_engine

GOLDEN_DIR = Path(__file__).parent / "golden"
MARTS_SCHEMA = "analytics_marts"

# Per-mart snapshot config. `order_by` makes the row order deterministic;
# `exclude` drops columns whose value is time-dependent (not data-dependent).
GOLDEN_MARTS: dict[str, dict] = {
    "mart_recovery_state": {"order_by": ["day"], "exclude": ["is_today"]},
    "mart_daily_rhr": {"order_by": ["day"], "exclude": []},
    "mart_daily_hrv": {"order_by": ["day"], "exclude": []},
    "mart_daily_vo2max": {"order_by": ["day"], "exclude": []},
    "mart_daily_weight": {"order_by": ["day"], "exclude": []},
    "mart_training_load": {"order_by": ["day"], "exclude": []},
    "mart_daily_signals": {"order_by": ["day"], "exclude": ["is_today"]},
    "mart_workout_zones": {"order_by": ["start_ts_local"], "exclude": []},
    # The causal mart's continuous columns come from host-side numpy/statsmodels,
    # whose last-digit results can differ across BLAS backends (macOS vs CI Linux).
    # Freeze only the deterministic columns (ids, verdict, integer counts, cutoff);
    # the float estimates are covered by tolerance-based tests
    # (test_causal_engine_recovers_planted_effect + tests/test_causal.py).
    "mart_experiment_effects": {
        "order_by": ["experiment_name", "target_metric"],
        "exclude": [
            "level_change",
            "level_ci_low",
            "level_ci_high",
            "slope_change",
            "hac_p_value",
            "placebo_p_value",
            "did_estimate",
        ],
    },
}


def _engine_or_skip():
    try:
        engine = demo_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except OperationalError as exc:
        pytest.skip(f"{DEMO_DB} unreachable: {exc}")


def _canon(v: object):
    """JSON-serialisable, drift-free representation of a cell value."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, dt.datetime | dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 6)
    return v


def _columns(conn, mart: str, exclude: list[str]) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            "ORDER BY ordinal_position"
        ),
        {"s": MARTS_SCHEMA, "t": mart},
    ).fetchall()
    return [r[0] for r in rows if r[0] not in exclude]


def snapshot_mart(engine, mart: str, order_by: list[str], exclude: list[str]) -> dict:
    """Return a canonical, order-stable snapshot of a mart."""
    with engine.connect() as conn:
        cols = _columns(conn, mart, exclude)
        if not cols:
            raise ProgrammingError(f"no columns for {mart}", None, None)  # type: ignore[arg-type]
        col_sql = ", ".join(f'"{c}"' for c in cols)
        order_sql = ", ".join(f'"{c}"' for c in order_by)
        result = conn.execute(
            text(f"SELECT {col_sql} FROM {MARTS_SCHEMA}.{mart} ORDER BY {order_sql}")
        )
        rows = [[_canon(v) for v in row] for row in result.fetchall()]
    return {
        "mart": mart,
        "columns": cols,
        "order_by": order_by,
        "row_count": len(rows),
        "rows": rows,
    }


def _golden_path(mart: str) -> Path:
    return GOLDEN_DIR / f"{mart}.json"


@pytest.fixture(scope="session")
def demo_built():
    """Skip the whole module unless health_demo has the flagship mart built."""
    engine = _engine_or_skip()
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {MARTS_SCHEMA}.mart_recovery_state LIMIT 1"))
    except ProgrammingError:
        pytest.skip(f"{DEMO_DB} not built — run `uv run python -m ingest.flows.make_demo_db` first")
    return engine


@pytest.mark.parametrize("mart", sorted(GOLDEN_MARTS))
def test_golden_mart(demo_built, mart: str) -> None:
    cfg = GOLDEN_MARTS[mart]
    current = snapshot_mart(demo_built, mart, cfg["order_by"], cfg["exclude"])

    path = _golden_path(mart)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=False) + "\n")
        n = current["row_count"]
        pytest.skip(f"UPDATE_GOLDEN=1 — re-baselined {mart} ({n} rows)")

    assert path.exists(), f"missing golden {path} — run UPDATE_GOLDEN=1 to create it"
    golden = json.loads(path.read_text())

    assert current["columns"] == golden["columns"], (
        f"{mart}: column set changed.\n"
        f"  golden:  {golden['columns']}\n  current: {current['columns']}"
    )
    assert current["row_count"] == golden["row_count"], (
        f"{mart}: row count {current['row_count']} != golden {golden['row_count']}"
    )
    if current["rows"] != golden["rows"]:
        pairs = zip(current["rows"], golden["rows"], strict=False)
        first = next((i for i, (a, b) in enumerate(pairs) if a != b), None)
        detail = ""
        if first is not None:
            detail = (
                f"\n  first diff @row {first}:\n"
                f"    golden:  {golden['rows'][first]}\n    current: {current['rows'][first]}"
            )
        pytest.fail(f"{mart}: row data drifted from golden.{detail}")


def test_recovery_signal_branch_coverage(demo_built) -> None:
    """The synthetic corpus must exercise EVERY recovery_signal branch — that is
    the point of the scenario timeline and the contract mart's only SQL branch
    coverage."""
    with demo_built.connect() as conn:
        seen = {
            r[0]
            for r in conn.execute(
                text(f"SELECT DISTINCT recovery_signal FROM {MARTS_SCHEMA}.mart_recovery_state")
            )
        }
    expected = {"well_recovered", "neutral", "strained", "insufficient_data"}
    missing = expected - seen
    assert not missing, f"synthetic corpus failed to cover recovery_signal branches: {missing}"


def test_causal_engine_recovers_planted_effect(demo_built) -> None:
    """End-to-end Phase-1 oracle: the generator plants a -3 bpm RHR step at the
    magnesium experiment's cutoff; the causal engine, run through the warehouse,
    must recover it as a significant decrease — while the no-effect cold_plunge
    control stays 'no_clear_effect'."""
    with demo_built.connect() as conn:
        rows = {
            (r[0], r[1]): {"level": r[2], "verdict": r[3]}
            for r in conn.execute(
                text(
                    "SELECT experiment_name, target_metric, level_change, verdict "
                    f"FROM {MARTS_SCHEMA}.mart_experiment_effects"
                )
            )
        }

    mag = rows[("magnesium_glycinate", "rhr_bpm")]
    assert mag["verdict"] == "likely_decrease", mag
    assert -4.0 <= mag["level"] <= -2.0, mag["level"]  # planted -3, generous band

    cold = rows[("cold_plunge", "rhr_bpm")]
    assert cold["verdict"] == "no_clear_effect", cold  # negative control
