-- Daily VO2 Max (mL/(kg·min)) in America/Chicago. Apple estimates VO2 Max
-- from outdoor walks/runs, so readings are sparse (not every day has one).
-- When multiple readings occur on the same day, we average.

select
    start_ts_local::date                          as day,
    round(avg(value)::numeric, 1)::double precision as vo2max,
    count(*)                                      as sample_count,
    max(unit)                                     as unit
from {{ ref('stg_quantities') }}
where metric_name = 'VO2Max'
group by 1
order by 1
