# ADR-0006: Pure-SQL Holt's-method forecasting (no Python ML dependency)

- **Status:** Accepted
- **Date:** 2026-05-17
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0005 (forecasts read the recovery signals), `transform/macros/holt_forecast.sql`, `transform/models/marts/mart_forecast_bands.sql`, `transform/models/marts/mart_forecast_backtest.sql`

## Context

The Forecast page projects RHR, HRV, and training load 7 days ahead, plus a
derived ACWR projection, with a backtest of accuracy. The modeling need is modest:
a level-plus-trend extrapolation over ~30 days of daily history — not enough data
to justify (or even fit) anything heavier. The question is *where the forecasting
math lives*: in the dbt/SQL layer alongside every other transform, or in a Python
step that pulls data out, fits a model, and writes results back.

Putting it in Python would add a numerical/ML dependency (statsmodels or similar),
a model-fitting step outside `dbt build`, and a second place where "rebuild the
marts" no longer means "run dbt". Keeping it in SQL keeps the entire transform
graph rebuildable with a single `dbt build` and re-tied to the same lineage and
tests as everything else.

## Decision

Forecasting is implemented in **pure SQL** via a `holt_forecast` dbt macro
(Holt's linear method: level + trend exponential smoothing, no seasonality),
using a `WITH RECURSIVE` walk over the daily series with fixed hyperparameters
(α = 0.3, β = 0.1, horizon = 7). It powers `mart_forecast_bands` (history +
7-day forecast + heuristic confidence bands) and `mart_forecast_backtest`
(walk-forward MAE/RMSE/MAPE). No Python ML library enters the dependency set; the
forecast rebuilds with every `dbt build`.

## Alternatives considered

- **Python + statsmodels (ETS/Holt)** — rejected: adds a heavy dependency and a
  fit-and-write-back step outside the dbt graph for a model this simple; breaks the
  "one `dbt build` rebuilds everything" property and splits lineage across two
  systems.
- **Holt-Winters (with seasonality)** — rejected: ~30 days of history cannot fit a
  7-day seasonal cycle; the seasonal term would be noise. Level + trend is the
  honest ceiling for the data on hand.
- **A no-trend moving-average / naïve forecast** — rejected: misses the directional
  signal (a steadily rising training load) that is the whole point of forecasting
  recovery inputs.
- **Rigorous prediction intervals (Monte Carlo / bootstrap)** — rejected for now:
  the bands are an explicit heuristic (±1.96·σ·√h on in-sample residual stddev),
  and ACWR — a deterministic derivation from forecasted training load — carries
  no band rather than fake a propagated one. Honest-about-uncertainty over
  falsely-precise.

## Consequences

**Positive:**
- Zero new runtime dependencies; the forecast is just more dbt models.
- Rebuilds and is tested with the rest of the graph (`dbt build`), under the same
  lineage and `accepted_values` constraints on the metric set.
- The recursive-CTE Holt implementation is a self-contained, reviewable macro.

**Negative:**
- Hyperparameters (α, β) are fixed sane defaults, not tuned; grid-search tuning is
  filed as a follow-up in the backlog.
- `WITH RECURSIVE` smoothing is more intricate to read than a library call — the
  macro is heavily commented to compensate.
- Confidence bands are heuristic, not statistically rigorous prediction intervals
  (surfaced honestly on the page, whose exposure maturity is marked `low`).

**Neutral but worth noting:**
- A future move to a richer model (more history, tuned params, true intervals)
  would be a new ADR superseding this one — not a silent swap.

## References

- `transform/macros/holt_forecast.sql` — the recursive level+trend macro.
- `transform/models/marts/mart_forecast_bands.sql` / `mart_forecast_backtest.sql`.
- `BACKLOG.md` — α/β grid-search tuning follow-up.
