# Design doc: forecasting marts (Holt's method + backtest)

- **Status:** Implemented (shipped 2026-05-17)
- **Last updated:** 2026-06-04
- **Decision record:** [ADR-0006 — Pure-SQL Holt's-method forecasting](../adr/0006-pure-sql-holt-forecasting.md)
- **Code:** [`holt_forecast` macro](../../transform/macros/holt_forecast.sql) ·
  [`mart_forecast_bands`](../../transform/models/marts/mart_forecast_bands.sql) ·
  [`mart_forecast_backtest`](../../transform/models/marts/mart_forecast_backtest.sql) ·
  [`app/pages/11_forecast.py`](../../app/pages/11_forecast.py) (consumer)

> This doc explains **how** the forecasting layer works and **why** it's built the
> way it is. The *decision* to do it in pure SQL (vs. a Python ML dependency) is
> recorded separately in [ADR-0006](../adr/0006-pure-sql-holt-forecasting.md) —
> read that first for the trade-off. This is the implementation companion.

## Goal

Every other mart looks backward. This layer looks **forward**: project the next
7 days of the daily recovery inputs — **resting HR (`rhr_bpm`)**, **HRV (`hrv_ms`)**,
**training load** — plus a derived **ACWR** projection, with a **walk-forward
backtest** that's honest about how good (or not) the forecasts are. The whole thing
rebuilds with a single `dbt build`, under the same lineage and tests as everything
else.

## Model: Holt's linear method

Holt's linear exponential smoothing — **level + trend, no seasonality**. ~30 days of
daily history can't fit a 7-day seasonal cycle (the seasonal term would be noise),
so level+trend is the honest ceiling for the data on hand. For each historical day
*t* with observed value *yₜ*:

```
level_t = α·y_t + (1 − α)·(level_{t−1} + trend_{t−1})
trend_t = β·(level_t − level_{t−1}) + (1 − β)·trend_{t−1}
```

Initialization (*t = 1*): `level₁ = y₁`, `trend₁ = 0`. The *h*-step-ahead forecast
from the last historical day *T* is `forecast_{T+h} = level_T + h·trend_T`.

Hyperparameters are **fixed** at α = 0.3, β = 0.1 (sane defaults: lower α = smoother,
more weight on history; higher = more reactive). Per-metric grid-search tuning is a
filed follow-up — see [Open follow-ups](#open-follow-ups).

## Implementation: the `holt_forecast` macro

[`transform/macros/holt_forecast.sql`](../../transform/macros/holt_forecast.sql) is a
self-contained dbt macro that takes `(input_relation, value_col, day_col='day',
alpha=0.3, beta=0.1, horizon=7)` and returns one row per day spanning **history +
the next `horizon` days**:

| column | historical rows | forecast rows |
|---|---|---|
| `day` | the date | future date |
| `value` | the actual *yₜ* | null |
| `smoothed` | `level_t` (for charting) | null |
| `one_step_ahead` | `level_t + trend_t` — the forecast made *at t* for *t+1* | null |
| `forecast` | null | `level_T + h·trend_T` |
| `is_forecast` | false | true |

It's a Postgres `WITH RECURSIVE` walk: `indexed` numbers the series by `row_number()
over (order by day)`, and the recursive `holt` CTE rolls `(level, trend)` forward one
row at a time. The base case is `SELECT … FROM indexed WHERE i = 1` — deliberately
**not** a bareword `SELECT 1, …`, because a bareword base case emits one all-NULL row
even when the source is empty, which contaminated the downstream mart (the fix is
documented inline). `one_step_ahead` is exposed precisely so the calling mart can
compute in-sample residuals for the confidence bands.

## `mart_forecast_bands` — history + forecast + bands

Tall format (one row per `(metric, day)`), mirroring `mart_daily_anomaly_bands` so a
chart can render actuals → forecast continuously. Columns: `metric, day, value,
smoothed, forecast, forecast_lower, forecast_upper, is_forecast, horizon_day_offset`.

- **Three fitted metrics** (`rhr_bpm`, `hrv_ms`, `training_load`) each call
  `holt_forecast` against their daily mart (`mart_daily_rhr`, `mart_daily_hrv`,
  `mart_training_load`).
- **Confidence bands** are a deliberate *heuristic*, **not** a rigorous prediction
  interval: `forecast ± 1.96·σ·√h`, where σ is the in-sample residual standard
  deviation (`residual_t = value_t − lag(one_step_ahead)`, computed per metric) and
  *h* = `day − last_historical_day`. The band widens with distance, which reads
  correctly even though it isn't a calibrated PI. (Page exposure maturity is `low`
  to flag this.)
- **Derived ACWR is not a fitted series.** It's a *continuation projection*: take
  actuals ∪ forecasted `training_load`, recompute `acute_load_7d` and
  `chronic_load_28d` with the **same windows as `mart_training_load`** (rows between
  6 / 27 preceding and current), and divide. This answers "where does ACWR land **if
  my recent pattern continues**?" — exactly the question `daily-workout-coach` needs.
  Bands are **null** for ACWR: the uncertainty lives in `training_load` and
  propagating it cleanly would require Monte Carlo.

## `mart_forecast_backtest` — walk-forward accuracy

The key insight that makes this cheap: with **online** exponential smoothing,
`(level_t, trend_t)` *is* "the model fitted through day t" — so there's **no need to
re-fit** at each cutoff. We read the existing series and project forward. Since
`one_step_ahead = level + trend` and `smoothed = level`, then `trend_t =
one_step_ahead_t − smoothed_t`, and the forecast made at cutoff *D* for *D+h* is
`smoothed_D + h·(one_step_ahead_D − smoothed_D)`. Left-join the realized value, take
`abs_error`.

Grain: one row per `(metric, cutoff_day, horizon 1..7)` — roughly day_8 … day_(N−7)
as eligible cutoffs, ≈ 15 cutoffs × 7 horizons × 3 metrics ≈ **300 rows**. The page
aggregates MAE / RMSE / MAPE per metric per horizon. **ACWR is omitted** from the
backtest: it's derived from forecasted `training_load`, so backtesting it would just
re-measure training_load's propagation error (double-counting).

## Results (real data, ~30 nights)

| metric | MAE @ h=1 | MAE @ h=7 | read |
|---|---|---|---|
| `rhr_bpm` | ~5.2 bpm | ~9.1 bpm | ~8–15% of mean — **usable** |
| `hrv_ms` | ~9.2 ms | ~10.6 ms | ~26–30% of mean — high day-to-day volatility; **trust the band, not the point** |
| `training_load` | ~67 TRIMP | ~70 TRIMP | MAE > mean — **Holt struggles with bursty workout/rest**; a baseline signal, not a session predictor |

The most useful finding is the last one, and the page surfaces it explicitly rather
than pretending the training-load point forecast is actionable.

## Honest constraints

- **~30 days of history.** Forecasts are inherently uncertain; the page says so.
- **Heuristic bands**, not calibrated prediction intervals (see above).
- **Fixed α/β**, not tuned per metric.

## Open follow-ups

- **Per-metric α/β grid search** — walk-forward MAE-minimizing sweep, params written
  back to a seed. → [BACKLOG: Fit Holt's hyperparameters](../../BACKLOG.md#improvement-fit-holts-hyperparameters-per-metric-via-grid-search)
- **Sleep-duration as a 4th forecast signal.** → [BACKLOG: Add sleep-duration to mart_forecast_bands](../../BACKLOG.md#improvement-add-sleep-duration-time-series-to-mart_forecast_bands)
- **True prediction intervals** (Monte Carlo / bootstrap) and/or a richer model would
  **supersede [ADR-0006](../adr/0006-pure-sql-holt-forecasting.md)** with a new ADR —
  not a silent swap.

## References

- [ADR-0006 — Pure-SQL Holt's-method forecasting](../adr/0006-pure-sql-holt-forecasting.md)
- Mart contracts & columns: [data dictionary](../reference/data-dictionary.md)
- Lineage: [dbt DAG diagram](../diagrams/dbt-lineage.mmd)
- Code: [`holt_forecast.sql`](../../transform/macros/holt_forecast.sql),
  [`mart_forecast_bands.sql`](../../transform/models/marts/mart_forecast_bands.sql),
  [`mart_forecast_backtest.sql`](../../transform/models/marts/mart_forecast_backtest.sql)
