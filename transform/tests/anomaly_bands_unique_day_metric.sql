-- Compound-unique check on mart_daily_anomaly_bands grain.
-- 06_anomaly.py pivots this mart on (day, metric); a duplicate row would
-- raise pandas ValueError. dbt_utils is not installed in this project, so
-- we enforce the contract with a singular test.

select
    day,
    metric,
    count(*) as n
from {{ ref('mart_daily_anomaly_bands') }}
group by 1, 2
having count(*) > 1
