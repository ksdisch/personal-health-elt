-- Daily HRV (SDNN, ms) in America/Chicago. Apple Watch takes multiple
-- HRV samples during the sleep window; we average them to one value per day.

select
    start_ts_local::date                         as day,
    round(avg(value)::numeric, 1)::double precision as hrv_ms,
    count(*)                                     as sample_count,
    max(unit)                                    as unit
from {{ ref('stg_quantities') }}
where metric_name = 'HeartRateVariabilitySDNN'
group by 1
order by 1
