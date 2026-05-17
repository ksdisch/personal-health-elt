-- Walk-forward backtest of the Holt forecasts in mart_forecast_bands.
--
-- The brilliant property of online exponential smoothing: the level
-- and trend computed for historical day t are already "the model
-- fitted through day t." We don't need to re-fit the model at each
-- cutoff — we just read the existing time series of (level_t,
-- trend_t) and project forward.
--
-- For each (metric, cutoff_day, horizon h ∈ 1..7) we synthesize the
-- forecast that WOULD have been made at end-of-cutoff_day for
-- cutoff_day + h, then left-join the realized value. The result is
-- one row per (metric, cutoff_day, h) with the predicted vs realized
-- values and the absolute error.
--
-- The page computes MAE / RMSE / MAPE from this mart per metric per
-- horizon by simple aggregation.
--
-- Why ACWR is omitted
-- -------------------
-- ACWR in mart_forecast_bands is a deterministic projection from the
-- forecasted training_load (not a fitted Holt series), so a "backtest"
-- against it would just measure the propagation error from training_load
-- — which is already captured by the training_load row of this mart.
-- Adding ACWR would double-count.
--
-- Data sufficiency
-- ----------------
-- With ~30 days of history and a 7-day horizon, the eligible
-- cutoff_days are roughly day_8 through day_(N-7) — call it ~15 cutoffs
-- × 7 horizons × 3 metrics ≈ 300 rows. The page is honest about how
-- thin this is.

{{ config(materialized='table') }}

with rhr_fcst as (
    {{ holt_forecast(ref('mart_daily_rhr'), 'resting_heart_rate') }}
),

hrv_fcst as (
    {{ holt_forecast(ref('mart_daily_hrv'), 'hrv_ms') }}
),

tl_fcst as (
    {{ holt_forecast(ref('mart_training_load'), 'training_load') }}
),

horizons as (select generate_series(1, 7) as h),

-- ------------------------------------------------------------------
-- Per-metric: build walk-forward forecasts. trend_t = one_step_ahead_t
-- − smoothed_t (since one_step_ahead = level + trend and smoothed = level).
-- forecast(cutoff D for D+h) = smoothed_D + h · trend_D.
-- ------------------------------------------------------------------
rhr_backtest as (
    select
        'rhr_bpm'::text                                        as metric,
        f.day                                                  as cutoff_day,
        (f.day + h.h)::date                                    as target_day,
        h.h                                                    as horizon_days,
        (f.smoothed + h.h * (f.one_step_ahead - f.smoothed))::double precision
                                                               as forecast,
        actuals.resting_heart_rate::double precision           as actual,
        abs(actuals.resting_heart_rate
            - (f.smoothed + h.h * (f.one_step_ahead - f.smoothed)))::double precision
                                                               as abs_error
    from rhr_fcst f
    cross join horizons h
    left join {{ ref('mart_daily_rhr') }} actuals
        on actuals.day = (f.day + h.h)::date
    where not f.is_forecast
      and f.one_step_ahead is not null
      and actuals.resting_heart_rate is not null
),

hrv_backtest as (
    select
        'hrv_ms'::text                                         as metric,
        f.day                                                  as cutoff_day,
        (f.day + h.h)::date                                    as target_day,
        h.h                                                    as horizon_days,
        (f.smoothed + h.h * (f.one_step_ahead - f.smoothed))::double precision
                                                               as forecast,
        actuals.hrv_ms::double precision                       as actual,
        abs(actuals.hrv_ms
            - (f.smoothed + h.h * (f.one_step_ahead - f.smoothed)))::double precision
                                                               as abs_error
    from hrv_fcst f
    cross join horizons h
    left join {{ ref('mart_daily_hrv') }} actuals
        on actuals.day = (f.day + h.h)::date
    where not f.is_forecast
      and f.one_step_ahead is not null
      and actuals.hrv_ms is not null
),

tl_backtest as (
    select
        'training_load'::text                                  as metric,
        f.day                                                  as cutoff_day,
        (f.day + h.h)::date                                    as target_day,
        h.h                                                    as horizon_days,
        (f.smoothed + h.h * (f.one_step_ahead - f.smoothed))::double precision
                                                               as forecast,
        actuals.training_load::double precision                as actual,
        abs(actuals.training_load
            - (f.smoothed + h.h * (f.one_step_ahead - f.smoothed)))::double precision
                                                               as abs_error
    from tl_fcst f
    cross join horizons h
    left join {{ ref('mart_training_load') }} actuals
        on actuals.day = (f.day + h.h)::date
    where not f.is_forecast
      and f.one_step_ahead is not null
      and actuals.training_load is not null
)

select metric, cutoff_day, target_day, horizon_days, forecast, actual, abs_error
from rhr_backtest
union all
select metric, cutoff_day, target_day, horizon_days, forecast, actual, abs_error
from hrv_backtest
union all
select metric, cutoff_day, target_day, horizon_days, forecast, actual, abs_error
from tl_backtest
order by metric, cutoff_day, horizon_days
