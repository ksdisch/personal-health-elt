-- Intermediate: one row per Apple sleep-stage segment, attributed to a night.
--
-- Apple Health emits SleepAnalysis category rows as contiguous segments
-- (asleepCore / asleepDeep / asleepREM / asleepUnspecified / awake / inBed)
-- that together describe a single night's sleep. We attribute each segment
-- to a "night" using a noon-to-noon partition: a segment that starts before
-- noon belongs to that calendar date's night (the morning you wake up); a
-- segment that starts after noon belongs to the NEXT calendar date's night.
-- So an 11pm Sunday segment and a 1am Monday segment both roll up to Monday.
--
-- Filters out null / point-in-time rows; only true SleepAnalysis intervals
-- with both endpoints flow through.
--
-- Used by mart_sleep_stages (hypnogram) and mart_sleep_nights (per-night
-- rollup with composite score).

with segments as (
    select
        case
            when extract(hour from start_ts_local) < 12
                then start_ts_local::date
            else (start_ts_local + interval '1 day')::date
        end as night_date,
        category_value as sleep_stage,
        start_ts_local,
        end_ts_local,
        extract(epoch from (end_ts_local - start_ts_local)) / 60.0 as duration_min,
        category_value in ('asleepCore', 'asleepDeep', 'asleepREM', 'asleepUnspecified') as is_asleep,
        source_name,
        source_priority
    from {{ ref('stg_categories') }}
    where category_name = 'SleepAnalysis'
      and category_value is not null
      and end_ts_local is not null
)

select
    night_date,
    sleep_stage,
    start_ts_local,
    end_ts_local,
    duration_min,
    is_asleep,
    source_name,
    source_priority
from segments
