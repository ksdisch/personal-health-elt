-- Forward-looking forecast bands for the daily recovery signals.
--
-- Tall format mirroring `mart_daily_anomaly_bands`: one row per
-- (metric, day) covering both historical days (so a chart can show
-- actuals → forecast continuously) and the next 7 days. Pivot in the
-- consumer page.
--
-- Method
-- ------
-- Three metrics get fitted forecasts via Holt's linear method (pure
-- SQL via the `holt_forecast` macro): rhr_bpm, hrv_ms, training_load.
-- Hyperparameters fixed at α=0.3, β=0.1 — sane defaults; grid-search
-- tuning is filed as a follow-up. Confidence bands are a sensible
-- heuristic, not a rigorous prediction interval: ±1.96·σ·sqrt(h)
-- where σ is the in-sample residual stddev and h is the forecast
-- horizon (band widens with distance).
--
-- The fourth metric, `acwr`, is NOT fitted as a time series. It's
-- derived deterministically from the forecasted training_load via
-- the same rolling-window math as `mart_training_load`: assume the
-- next 7 days follow the projected training_load trajectory, then
-- compute acute_load_7d / chronic_load_28d for each future day. This
-- is a "continuation projection" — it answers "where does ACWR land
-- if my recent training pattern continues?", which is the question
-- the daily-workout-coach actually needs. Confidence bands are NULL
-- for derived ACWR (the underlying uncertainty is in training_load
-- and would require Monte Carlo to propagate cleanly).
--
-- Honest constraints
-- ------------------
-- The available history is currently ~30 days. Forecasts will be
-- uncertain. The page surfaces this; this mart just computes them.

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

-- ------------------------------------------------------------------
-- per-metric residual stddev for ±1.96·σ·sqrt(h) confidence bands
-- residual_t = value_t − (level_{t-1} + trend_{t-1})
--            = value_t − lag(one_step_ahead) over (order by day)
-- ------------------------------------------------------------------
rhr_with_residual as (
    select
        *,
        value - lag(one_step_ahead) over (order by day) as residual
    from rhr_fcst
),
rhr_sigma as (
    select coalesce(stddev_samp(residual), 0)::double precision as sigma
    from rhr_with_residual
    where not is_forecast and residual is not null
),

hrv_with_residual as (
    select
        *,
        value - lag(one_step_ahead) over (order by day) as residual
    from hrv_fcst
),
hrv_sigma as (
    select coalesce(stddev_samp(residual), 0)::double precision as sigma
    from hrv_with_residual
    where not is_forecast and residual is not null
),

tl_with_residual as (
    select
        *,
        value - lag(one_step_ahead) over (order by day) as residual
    from tl_fcst
),
tl_sigma as (
    select coalesce(stddev_samp(residual), 0)::double precision as sigma
    from tl_with_residual
    where not is_forecast and residual is not null
),

-- last historical day per metric — used for horizon_day_offset
rhr_last as (select max(day) as last_day from rhr_fcst where not is_forecast),
hrv_last as (select max(day) as last_day from hrv_fcst where not is_forecast),
tl_last  as (select max(day) as last_day from tl_fcst  where not is_forecast),

-- ------------------------------------------------------------------
-- assemble tall-format rows for the 3 fitted metrics
-- ------------------------------------------------------------------
rhr_rows as (
    select
        'rhr_bpm'::text as metric,
        f.day,
        f.value,
        f.smoothed,
        f.forecast,
        case
            when f.is_forecast
            then f.forecast - 1.96 * s.sigma * sqrt((f.day - rl.last_day)::numeric)
        end as forecast_lower,
        case
            when f.is_forecast
            then f.forecast + 1.96 * s.sigma * sqrt((f.day - rl.last_day)::numeric)
        end as forecast_upper,
        f.is_forecast,
        case when f.is_forecast then (f.day - rl.last_day) end as horizon_day_offset
    from rhr_fcst f
    cross join rhr_sigma s
    cross join rhr_last rl
),

hrv_rows as (
    select
        'hrv_ms'::text as metric,
        f.day,
        f.value,
        f.smoothed,
        f.forecast,
        case
            when f.is_forecast
            then f.forecast - 1.96 * s.sigma * sqrt((f.day - hl.last_day)::numeric)
        end as forecast_lower,
        case
            when f.is_forecast
            then f.forecast + 1.96 * s.sigma * sqrt((f.day - hl.last_day)::numeric)
        end as forecast_upper,
        f.is_forecast,
        case when f.is_forecast then (f.day - hl.last_day) end as horizon_day_offset
    from hrv_fcst f
    cross join hrv_sigma s
    cross join hrv_last hl
),

tl_rows as (
    select
        'training_load'::text as metric,
        f.day,
        f.value,
        f.smoothed,
        f.forecast,
        case
            when f.is_forecast
            then f.forecast - 1.96 * s.sigma * sqrt((f.day - tll.last_day)::numeric)
        end as forecast_lower,
        case
            when f.is_forecast
            then f.forecast + 1.96 * s.sigma * sqrt((f.day - tll.last_day)::numeric)
        end as forecast_upper,
        f.is_forecast,
        case when f.is_forecast then (f.day - tll.last_day) end as horizon_day_offset
    from tl_fcst f
    cross join tl_sigma s
    cross join tl_last tll
),

-- ------------------------------------------------------------------
-- derived ACWR: deterministic projection from forecasted training_load.
-- For each day in (history ∪ forecast horizon), recompute acute_load_7d
-- and chronic_load_28d via the SAME windows as mart_training_load, then
-- divide. Historical days here equal the actual ACWR; forecast-horizon
-- days are the "if-you-continue" projection.
-- ------------------------------------------------------------------
tl_combined as (
    -- actuals (historical only — non-zero forecast rows in tl_fcst
    -- replace, not add to, these via the is_forecast=true union)
    select day, training_load::double precision as training_load, false as is_forecast
    from {{ ref('mart_training_load') }}
    union all
    -- forecasts (forecast horizon only)
    select day, forecast as training_load, true as is_forecast
    from tl_fcst
    where is_forecast
),

tl_combined_with_windows as (
    select
        day,
        training_load,
        is_forecast,
        avg(training_load) over (
            order by day rows between 6 preceding and current row
        ) as acute_load_7d,
        avg(training_load) over (
            order by day rows between 27 preceding and current row
        ) as chronic_load_28d
    from tl_combined
),

acwr_projected as (
    select
        day,
        is_forecast,
        case
            when chronic_load_28d > 0
            then (acute_load_7d / chronic_load_28d)::double precision
        end as projected_acwr
    from tl_combined_with_windows
),

acwr_actuals as (
    -- the actual historical ACWR from the mart (not the projection),
    -- so we charts match the single source of truth
    select day, acwr::double precision as value
    from {{ ref('mart_training_load') }}
),

acwr_last as (
    select max(day) as last_day from acwr_actuals where value is not null
),

acwr_rows as (
    select
        'acwr'::text as metric,
        p.day,
        a.value,                                            -- actual when historical
        null::double precision  as smoothed,                -- no Holt smoothing for derived ACWR
        case when p.is_forecast then p.projected_acwr end   as forecast,
        null::double precision  as forecast_lower,          -- bands omitted for derived
        null::double precision  as forecast_upper,
        p.is_forecast,
        case when p.is_forecast then (p.day - al.last_day) end as horizon_day_offset
    from acwr_projected p
    left join acwr_actuals a on a.day = p.day
    cross join acwr_last al
)

-- ------------------------------------------------------------------
-- final tall rollup, deterministic ordering for downstream consumers
-- ------------------------------------------------------------------
select metric, day, value, smoothed, forecast, forecast_lower, forecast_upper,
       is_forecast, horizon_day_offset
from rhr_rows
union all
select metric, day, value, smoothed, forecast, forecast_lower, forecast_upper,
       is_forecast, horizon_day_offset
from hrv_rows
union all
select metric, day, value, smoothed, forecast, forecast_lower, forecast_upper,
       is_forecast, horizon_day_offset
from tl_rows
union all
select metric, day, value, smoothed, forecast, forecast_lower, forecast_upper,
       is_forecast, horizon_day_offset
from acwr_rows
order by metric, day
