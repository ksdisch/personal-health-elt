-- Staging layer for raw.workouts.
--
-- Responsibilities (and ONLY these):
--   1. Convert UTC timestamps to America/Chicago.
--   2. Derive day_local for easy daily aggregation downstream.
--   3. Tag rows with source_priority and keep the winning source per
--      (activity_type, start_ts_local). Per CLAUDE.md:
--        Apple Watch > iPhone > everything else.
--
-- No business logic lives here — intermediate joins workouts to HR
-- samples, marts summarize. This layer just cleans.

with ranked as (
    select
        activity_type,
        source_name,
        source_version,
        product_type,
        (start_ts at time zone 'America/Chicago')::timestamp as start_ts_local,
        (end_ts   at time zone 'America/Chicago')::timestamp as end_ts_local,
        (start_ts at time zone 'America/Chicago')::date      as day_local,
        duration_sec,
        total_energy_kcal,
        total_distance_m,
        elevation_asc_m,
        elevation_desc_m,
        max_speed_mps,
        indoor,
        case
            when source_name ilike '%apple watch%' then 1
            when source_name ilike '%iphone%'      then 2
            else 3
        end as source_priority,
        source_file,
        source_sha256,
        row_number() over (
            partition by activity_type, start_ts
            order by
                case
                    when source_name ilike '%apple watch%' then 1
                    when source_name ilike '%iphone%'      then 2
                    else 3
                end,
                source_name
        ) as source_rank
    from {{ source('raw', 'workouts') }}
)

select
    activity_type,
    source_name,
    source_version,
    product_type,
    start_ts_local,
    end_ts_local,
    day_local,
    duration_sec,
    total_energy_kcal,
    total_distance_m,
    elevation_asc_m,
    elevation_desc_m,
    max_speed_mps,
    indoor,
    source_priority,
    source_file,
    source_sha256
from ranked
where source_rank = 1
