{#
    holt_forecast — Holt's linear exponential smoothing in pure SQL.

    Implements the level + trend variant (no seasonality — 30 days of
    history isn't enough to fit a 7-day cycle). Hyperparameters are
    fixed at sane defaults; tuning them via a grid search is a separate
    follow-up (see BACKLOG).

    Math
    ----
    For each historical day t with observed value y_t:
      level_t   = α·y_t + (1 - α)·(level_{t-1} + trend_{t-1})
      trend_t   = β·(level_t - level_{t-1}) + (1 - β)·trend_{t-1}

    Initialization (t = 1):
      level_1   = y_1
      trend_1   = 0

    The one-step-ahead in-sample fit is (level_{t-1} + trend_{t-1});
    we expose `smoothed` as the level for charting and as the basis for
    residual std (the σ used to widen the forecast band).

    Forecast (horizon h ≥ 1, starting from the last historical day T):
      forecast_{T+h} = level_T + h·trend_T

    Output grain
    ------------
    One row per day spanning historical + the next `horizon` days:

      | day | value | smoothed | one_step_ahead | forecast | is_forecast |

    Historical rows (is_forecast=false): value is the actual, smoothed
    is level_t, one_step_ahead is (level_t + trend_t) — the forecast
    made AT time t FOR time t+1. Useful for computing in-sample
    residuals (value_t - lag(one_step_ahead, 1) over (order by day))
    which the caller turns into a residual stddev for confidence bands.
    forecast is null.

    Forecast rows (is_forecast=true): value/smoothed/one_step_ahead are
    null. forecast = level_T + h·trend_T where T is the last historical
    day and h ∈ [1, horizon].

    Confidence bands are deliberately NOT in the macro — they depend on
    per-metric residual std, which is easier to compute once at the
    calling mart's level than to thread through the macro's signature.

    Arguments
    ---------
    input_relation : Relation
        The source model / ref. Must produce `(day, value_col)`.
    value_col : str
        Column to forecast. Cast to numeric inside the macro for safe
        arithmetic across float/integer source types.
    day_col : str = 'day'
        Date column on input_relation.
    alpha : float = 0.3
        Level smoothing parameter. Lower = smoother (more weight on
        history); higher = more reactive to recent values.
    beta : float = 0.1
        Trend smoothing parameter. Same intuition as alpha.
    horizon : int = 7
        Number of future days to extend the forecast.

    Implementation notes
    --------------------
    - Postgres `WITH RECURSIVE` must be the first keyword in the CTE
      block; non-recursive CTEs that follow are still fine.
    - The recursive `holt` CTE walks the time series one row at a time
      via the `indexed.i` row number, propagating (level, trend) forward.
    - Nesting `WITH RECURSIVE ... SELECT` inside an outer CTE body is
      valid Postgres — each macro call's internal CTE names live in
      their own subquery scope and never collide.

    Usage
    -----
        with rhr_forecast as (
            {{ holt_forecast(ref('mart_daily_rhr'), 'resting_heart_rate') }}
        )
        select 'rhr_bpm' as metric, * from rhr_forecast
#}
{% macro holt_forecast(input_relation, value_col, day_col='day', alpha=0.3, beta=0.1, horizon=7) %}
with recursive
    source_data as (
        select {{ day_col }} as day, {{ value_col }}::numeric as value
        from {{ input_relation }}
        where {{ value_col }} is not null
    ),

    indexed as (
        select day, value, row_number() over (order by day) as i
        from source_data
    ),

    holt as (
        -- base case: t = 1, level = first observation, trend = 0.
        -- FROM indexed WHERE i = 1 produces exactly 0 or 1 rows, so
        -- when the source has no non-null values the whole recursive
        -- CTE evaluates to zero rows instead of one all-NULL row (the
        -- earlier bareword SELECT always emitted 1 row regardless of
        -- whether indexed had data, which produced garbage downstream).
        select
            1::bigint        as i,
            day              as day,
            value            as value,
            value::numeric   as level,
            0::numeric       as trend
        from indexed
        where i = 1

        union all

        -- recursive case: roll the level + trend forward one row at a time
        select
            h.i + 1,
            n.day,
            n.value,
            {{ alpha }} * n.value
                + (1 - {{ alpha }}) * (h.level + h.trend) as level,
            {{ beta }} * (
                ({{ alpha }} * n.value + (1 - {{ alpha }}) * (h.level + h.trend))
                - h.level
            ) + (1 - {{ beta }}) * h.trend as trend
        from holt h
        join indexed n on n.i = h.i + 1
    ),

    last_state as (
        select day as last_day, level, trend
        from holt
        order by i desc
        limit 1
    ),

    historical as (
        select
            day,
            value::double precision           as value,
            level::double precision           as smoothed,
            (level + trend)::double precision as one_step_ahead,
            null::double precision            as forecast,
            false                             as is_forecast
        from holt
    ),

    forecast_days as (
        select
            (last_day + (gs * interval '1 day'))::date as day,
            null::double precision                     as value,
            null::double precision                     as smoothed,
            null::double precision                     as one_step_ahead,
            (level + gs * trend)::double precision     as forecast,
            true                                       as is_forecast
        from last_state
        cross join generate_series(1, {{ horizon }}) as gs
    )

select day, value, smoothed, one_step_ahead, forecast, is_forecast from historical
union all
select day, value, smoothed, one_step_ahead, forecast, is_forecast from forecast_days
{% endmacro %}
