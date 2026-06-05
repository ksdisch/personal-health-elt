# ADR-0008: statsmodels for causal inference (scoped exception to ADR-0006)

- **Status:** Accepted
- **Date:** 2026-06-05
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0006 (pure-SQL forecasting), ADR-0009 (causal results re-enter via raw→staging→mart), `ingest/analysis/causal.py`, `transform/models/marts/mart_experiment_effects.sql`

## Context

The Causal-Inference Lab estimates whether a logged intervention actually moved a
daily physiological series (RHR, HRV) using interrupted-time-series (ITS) with
Newey-West **HAC** standard errors, a **permutation/placebo** p-value, and a
secondary difference-in-differences. ADR-0006 deliberately kept *forecasting* in
pure SQL and **rejected statsmodels** to preserve the "one `dbt build` rebuilds
everything" property. This milestone needs exactly the dependency ADR-0006 turned
away — so the tension must be resolved explicitly, not silently reversed.

The key difference from forecasting: HAC covariance estimation and permutation
inference are genuinely **beyond SQL**. A `WITH RECURSIVE` Holt smoother is a
reasonable SQL exercise; a heteroskedasticity-and-autocorrelation-consistent
covariance matrix and a 999-iteration placebo distribution are not. Daily HRV/RHR
are strongly autocorrelated, which makes a naive OLS/t-test understate the
standard error — getting the *uncertainty* right is the whole point, and that is
what statsmodels provides correctly and SQL does not.

## Decision

Adopt **statsmodels** (+ scipy, pulled transitively) as a dependency, used
**only** in `ingest/analysis/causal.py` for causal estimation. ADR-0006 stands
unchanged: forecasting remains pure-SQL. The two coexist by scope —

- **Forecasting** (level+trend extrapolation, modest math) → pure SQL, rebuilds
  with `dbt build`.
- **Causal inference** (HAC errors, permutation, DiD) → Python/statsmodels,
  computed in a step *outside* `dbt build`, whose results re-enter the warehouse
  through `raw.experiment_effects` → staging → mart (see ADR-0009).

## Alternatives considered

- **Force causal inference into SQL** — rejected: HAC covariance and permutation
  resampling are impractical and error-prone in SQL; the result would be either
  wrong (naive SEs on autocorrelated data) or unreadable.
- **Keep ADR-0006's no-Python-stats rule and drop the causal layer** — rejected:
  the descriptive→predictive→**causal** maturity step is the point of the
  milestone, and "what actually moved the needle" is the highest-value question.
- **A lighter pure-Python implementation (hand-rolled OLS + bootstrap)** —
  rejected: re-implementing HAC correctly is exactly the kind of subtle numerical
  work a vetted library should own; statsmodels is the standard.

## Consequences

**Positive:**
- Correct, autocorrelation-robust inference (HAC) with honest small-n p-values
  (permutation) — the methodologically right tool.
- Validated the gold-standard way: a planted synthetic effect is recovered by the
  engine end to end (`tests/test_causal.py`, `tests/test_golden_marts.py`).

**Negative:**
- A numerical dependency (statsmodels/scipy ~30 MB) enters the lockfile, and the
  causal step runs **outside** `dbt build` — the exact property ADR-0006 protected,
  now accepted for this one bounded use.
- Two systems touch the causal path (Python computes, dbt models). Mitigated by
  ADR-0009's strict raw→staging→mart re-entry.

**Neutral but worth noting:**
- This does **not** reopen forecasting. Any future move of forecasting to Python
  would be its own ADR superseding 0006.

## References

- `ingest/analysis/causal.py` — ITS (HAC), permutation, DiD.
- `tests/test_causal.py` — planted-effect recovery + HAC-vs-OLS-SE proof.
- ADR-0006, ADR-0009.
