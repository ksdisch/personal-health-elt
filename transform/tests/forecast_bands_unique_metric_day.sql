-- Compound-unique check on mart_forecast_bands grain.
-- 11_forecast.py pivots this mart on (metric, day); a duplicate row would
-- raise pandas ValueError. dbt_utils is not installed in this project, so
-- we enforce the contract with a singular test.

select
    metric,
    day,
    count(*) as n
from {{ ref('mart_forecast_bands') }}
group by 1, 2
having count(*) > 1
