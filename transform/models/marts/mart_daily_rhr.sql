-- Daily resting heart rate, one row per calendar day (America/Chicago).
-- Apple emits one RHR value per day, so no aggregation is needed — we
-- just filter and project.

select
    start_ts_local::date as day,
    value                as resting_heart_rate,
    source_name,
    unit
from {{ ref('stg_quantities') }}
where metric_name = 'RestingHeartRate'
order by day
