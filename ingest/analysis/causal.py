"""Personal N-of-1 causal-inference engine.

For each (experiment, target metric) the engine estimates whether a logged
intervention actually moved a daily physiological series, using three methods:

1. **Interrupted Time Series (segmented regression)** with **Newey-West HAC**
   standard errors — the load-bearing estimate. Daily RHR/HRV are strongly
   autocorrelated, which makes a naive OLS/t-test understate the standard error;
   HAC corrects it. The model is

       y_t = b0 + b1*t + b2*D_t + b3*(t - t0)*D_t + e_t

   where ``D_t`` is the post-intervention indicator. ``b2`` is the level change
   at the intervention (the headline effect); ``b3`` is the slope change.

2. **Permutation / placebo-in-time test** — re-estimate the level change at many
   random fake cutoffs and compute an empirical p-value. Trustworthy at the
   n~30-60 days a personal experiment yields, where parametric p-values are
   fragile.

3. **Difference-in-Differences** vs a control metric — secondary / reported
   only (a single subject rarely has a truly unaffected control), so it never
   gates a conclusion.

Design notes:
* ADR-0006 rejected statsmodels for *forecasting* (kept pure-SQL Holt). This
  module is the deliberate, scoped exception for *causal* inference — HAC and
  permutation are beyond SQL. See docs/adr/0008.
* Results are written to ``raw.experiment_effects`` and read by
  ``stg_experiment_effects`` -> ``mart_experiment_effects`` so the Python output
  re-enters the warehouse through the normal staging->marts layering, not as a
  Python-materialised mart. See docs/adr/0009.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.config import PROJECT_ROOT
from ingest.db import get_engine
from ingest.loaders._idempotency import upsert_rows

logger = logging.getLogger(__name__)

SEEDS_DIR = PROJECT_ROOT / "transform" / "seeds"
EXPERIMENTS_CSV = SEEDS_DIR / "experiments.csv"

# Metric name -> (mart, column) so an experiment can target a friendly metric.
METRIC_SOURCES: dict[str, tuple[str, str]] = {
    "rhr_bpm": ("mart_daily_rhr", "resting_heart_rate"),
    "hrv_ms": ("mart_daily_hrv", "hrv_ms"),
}

# Default pre-intervention window pulled in front of the cutoff for the ITS fit.
_PRE_WINDOW_DAYS = 28
# Minimum observations on each side to attempt a fit.
_MIN_SIDE = 4


# --------------------------------------------------------------------------- #
# Estimators
# --------------------------------------------------------------------------- #
def hac_maxlags(n: int) -> int:
    """Newey-West truncation lag. ``floor(n**0.25)`` (min 1) is a standard
    rule-of-thumb that grows slowly with the series length."""
    return max(1, int(np.floor(n**0.25)))


@dataclass(frozen=True)
class ITSResult:
    level_change: float
    slope_change: float
    level_ci_low: float
    level_ci_high: float
    hac_p_value: float
    n_pre: int
    n_post: int
    hac_maxlags: int


def _design(n: int, post: np.ndarray) -> np.ndarray:
    t = np.arange(n, dtype=float)
    t0 = int(np.argmax(post)) if post.any() else n
    t_since = np.where(post == 1, t - t0, 0.0)
    return np.column_stack([np.ones(n), t, post.astype(float), t_since])


def _ols_level_change(y: np.ndarray, post: np.ndarray) -> float:
    """Plain-OLS level-change coefficient (no HAC) — used inside permutation."""
    x = _design(len(y), post)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return float(beta[2])


def _post_from_cut(n: int, cut: int) -> np.ndarray:
    post = np.zeros(n, dtype=int)
    post[cut:] = 1
    return post


def fit_its(values: np.ndarray, post: np.ndarray, *, maxlags: int | None = None) -> ITSResult:
    """Segmented-regression ITS with Newey-West HAC standard errors."""
    y = np.asarray(values, dtype=float)
    post = np.asarray(post, dtype=int)
    n = len(y)
    x = _design(n, post)
    if maxlags is None:
        maxlags = hac_maxlags(n)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    ci = model.conf_int()
    return ITSResult(
        level_change=float(model.params[2]),
        slope_change=float(model.params[3]),
        level_ci_low=float(ci[2][0]),
        level_ci_high=float(ci[2][1]),
        hac_p_value=float(model.pvalues[2]),
        n_pre=int((post == 0).sum()),
        n_post=int((post == 1).sum()),
        hac_maxlags=int(maxlags),
    )


def permutation_pvalue(
    values: np.ndarray, post: np.ndarray, *, n_perm: int = 999, seed: int = 0, buffer: int = 5
) -> float:
    """Empirical two-sided p-value: how often does a RANDOM cutoff produce a
    level change as large as the real one? Robust where parametric p's aren't."""
    y = np.asarray(values, dtype=float)
    post = np.asarray(post, dtype=int)
    n = len(y)
    t0 = int(np.argmax(post)) if post.any() else n
    observed = abs(_ols_level_change(y, post))
    rng = np.random.default_rng(seed)
    valid = [c for c in range(buffer, n - buffer) if abs(c - t0) > buffer]
    if not valid:
        return float("nan")
    extreme = 0
    for _ in range(n_perm):
        cut = int(rng.choice(valid))
        placebo = abs(_ols_level_change(y, _post_from_cut(n, cut)))
        if placebo >= observed:
            extreme += 1
    return (extreme + 1) / (n_perm + 1)


def did_estimate(treated: np.ndarray, control: np.ndarray, post: np.ndarray) -> float:
    """2x2 difference-in-differences: (treated post-pre) - (control post-pre)."""
    post = np.asarray(post, dtype=bool)
    treated = np.asarray(treated, dtype=float)
    control = np.asarray(control, dtype=float)
    d_treated = treated[post].mean() - treated[~post].mean()
    d_control = control[post].mean() - control[~post].mean()
    return float(d_treated - d_control)


# --------------------------------------------------------------------------- #
# Experiments + warehouse glue
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Experiment:
    name: str
    start_date: date
    end_date: date
    target_metrics: tuple[str, ...]
    control_metric: str | None
    hypothesis: str


@dataclass(frozen=True)
class EffectRow:
    experiment_name: str
    target_metric: str
    cutoff_date: date
    level_change: float | None
    level_ci_low: float | None
    level_ci_high: float | None
    slope_change: float | None
    hac_p_value: float | None
    placebo_p_value: float | None
    did_estimate: float | None
    n_pre: int
    n_post: int
    confounded: bool


def load_experiments(path: Path = EXPERIMENTS_CSV) -> list[Experiment]:
    """Read the experiments seed. ``target_metrics`` is pipe-delimited."""
    df = pd.read_csv(path)
    out: list[Experiment] = []
    for r in df.itertuples(index=False):
        control = getattr(r, "control_metric", None)
        control = None if pd.isna(control) or str(control).strip() == "" else str(control)
        out.append(
            Experiment(
                name=str(r.name),
                start_date=pd.to_datetime(r.start_date).date(),
                end_date=pd.to_datetime(r.end_date).date(),
                target_metrics=tuple(
                    m.strip() for m in str(r.target_metrics).split("|") if m.strip()
                ),
                control_metric=control,
                hypothesis=str(getattr(r, "hypothesis", "")),
            )
        )
    return out


def _load_series(engine: Engine, metric: str, start: date, end: date) -> pd.DataFrame:
    mart, col = METRIC_SOURCES[metric]
    win_start = start - timedelta(days=_PRE_WINDOW_DAYS)
    sql = text(
        f"SELECT day, {col} AS value FROM analytics_marts.{mart} "
        f"WHERE day >= :a AND day <= :b AND {col} IS NOT NULL ORDER BY day"
    )
    df = pd.read_sql(sql, engine, params={"a": win_start, "b": end})
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


def _overlaps(a: Experiment, b: Experiment) -> bool:
    return a.start_date <= b.end_date and b.start_date <= a.end_date


def analyze_experiment(
    engine: Engine, exp: Experiment, *, all_experiments: list[Experiment], seed: int = 0
) -> list[EffectRow]:
    """Estimate effects for every target metric of one experiment."""
    confounded = any(o.name != exp.name and _overlaps(exp, o) for o in all_experiments)
    control_df = (
        _load_series(engine, exp.control_metric, exp.start_date, exp.end_date)
        if exp.control_metric in METRIC_SOURCES
        else None
    )
    rows: list[EffectRow] = []
    for metric in exp.target_metrics:
        if metric not in METRIC_SOURCES:
            logger.warning("experiment %s: unknown metric %s — skipping", exp.name, metric)
            continue
        df = _load_series(engine, metric, exp.start_date, exp.end_date)
        post = (df["day"] >= exp.start_date).to_numpy().astype(int)
        n_pre, n_post = int((post == 0).sum()), int((post == 1).sum())

        its: ITSResult | None = None
        placebo: float | None = None
        did: float | None = None
        if n_pre >= _MIN_SIDE and n_post >= _MIN_SIDE:
            y = df["value"].to_numpy(dtype=float)
            its = fit_its(y, post)
            placebo = permutation_pvalue(y, post, seed=seed)
            if control_df is not None and len(control_df) == len(df):
                cpost = (control_df["day"] >= exp.start_date).to_numpy().astype(int)
                if (cpost == post).all():
                    did = did_estimate(y, control_df["value"].to_numpy(dtype=float), post)

        rows.append(
            EffectRow(
                experiment_name=exp.name,
                target_metric=metric,
                cutoff_date=exp.start_date,
                level_change=None if its is None else its.level_change,
                level_ci_low=None if its is None else its.level_ci_low,
                level_ci_high=None if its is None else its.level_ci_high,
                slope_change=None if its is None else its.slope_change,
                hac_p_value=None if its is None else its.hac_p_value,
                placebo_p_value=placebo,
                did_estimate=did,
                n_pre=n_pre,
                n_post=n_post,
                confounded=confounded,
            )
        )
    return rows


def run(
    engine: Engine | None = None,
    experiments: list[Experiment] | None = None,
    *,
    seed: int = 0,
) -> int:
    """Analyze every experiment and upsert results into raw.experiment_effects.

    Idempotent: ON CONFLICT on (experiment_name, target_metric). Returns the
    number of effect rows computed (not necessarily newly inserted).
    """
    engine = engine or get_engine()
    experiments = experiments if experiments is not None else load_experiments()
    rows: list[EffectRow] = []
    for exp in experiments:
        rows.extend(analyze_experiment(engine, exp, all_experiments=experiments, seed=seed))

    if not rows:
        logger.info("no experiment effects computed")
        return 0

    df = pd.DataFrame([r.__dict__ for r in rows])
    names = sorted({r.experiment_name for r in rows})
    with engine.begin() as conn:
        # Effects are RECOMPUTED, not appended — delete prior rows for these
        # experiments first so the latest fit wins (ON CONFLICT DO NOTHING alone
        # would keep stale values). Then insert via the shared helper.
        conn.execute(
            text("DELETE FROM raw.experiment_effects WHERE experiment_name = ANY(:names)"),
            {"names": names},
        )
        upsert_rows(
            conn,
            df,
            table="experiment_effects",
            index_elements=["experiment_name", "target_metric"],
        )
    logger.info("wrote %d experiment-effect rows", len(rows))
    return len(rows)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Compute personal causal-inference effects.")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    n = run(seed=args.seed)
    print(f"computed {n} experiment-effect rows")


if __name__ == "__main__":
    _main()
