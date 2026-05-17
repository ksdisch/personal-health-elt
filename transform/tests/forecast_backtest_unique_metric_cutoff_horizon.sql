-- Compound-unique check on mart_forecast_backtest grain.
-- The mart is keyed on (metric, cutoff_day, horizon_days); the page
-- aggregates by these. A duplicate row would inflate sample counts and
-- pull MAE / RMSE silently.

select
    metric,
    cutoff_day,
    horizon_days,
    count(*) as n
from {{ ref('mart_forecast_backtest') }}
group by 1, 2, 3
having count(*) > 1
