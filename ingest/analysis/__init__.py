"""Causal-inference analysis layer (Phase 1: the Causal-Inference Lab).

Python-side statistical estimators (statsmodels) that are genuinely beyond SQL —
interrupted-time-series with HAC errors, permutation inference, difference-in-
differences. Results land in ``raw.experiment_effects`` and are read by a new
dbt staging model -> ``mart_experiment_effects``, keeping strict layering intact.
"""

from __future__ import annotations

from ingest.analysis.causal import (
    Experiment,
    ITSResult,
    analyze_experiment,
    did_estimate,
    fit_its,
    hac_maxlags,
    load_experiments,
    permutation_pvalue,
    run,
)

__all__ = [
    "Experiment",
    "ITSResult",
    "analyze_experiment",
    "did_estimate",
    "fit_its",
    "hac_maxlags",
    "load_experiments",
    "permutation_pvalue",
    "run",
]
