-- Daily training load with rolling windows.
--
-- One row per day over the observed date range (gaps filled with zero-load
-- days via a generated date spine) so rolling-window functions denominate
-- correctly. Each row is the state "as of that day", trailing inclusive.
--
-- training_load_today uses a simplified Banister TRIMP: sum of zone_N_min
-- weighted by the zone number (Z1=1×, Z2=2×, ..., Z5=5×). It's not as
-- sophisticated as the full Banister equation (which uses HR reserve), but
-- it's defensible, transparent, and only depends on what mart_workout_zones
-- already gives us.
--
-- ACWR = acute (7-day avg) / chronic (28-day avg). A common rule of thumb:
--   ACWR < 0.8  → under-training
--   0.8 .. 1.3  → sweet spot
--   > 1.5       → injury-risk zone
-- During the first 28 days of data, chronic_load is a partial average.

with per_day as (
    select
        day_local as day,
        sum(zone_1_sec) / 60.0 as zone_1_min,
        sum(zone_2_sec) / 60.0 as zone_2_min,
        sum(zone_3_sec) / 60.0 as zone_3_min,
        sum(zone_4_sec) / 60.0 as zone_4_min,
        sum(zone_5_sec) / 60.0 as zone_5_min,
        sum(case when activity_type = 'TraditionalStrengthTraining' then 1 else 0 end) as strength_sessions,
        sum(case when activity_type = 'TraditionalStrengthTraining'
                 then duration_sec else 0 end) / 60.0 as strength_min
    from {{ ref('mart_workout_zones') }}
    group by 1
),

date_spine as (
    select generate_series(
        (select min(day) from per_day),
        (select max(day) from per_day),
        '1 day'::interval
    )::date as day
),

filled as (
    select
        d.day,
        coalesce(p.zone_1_min, 0)        as zone_1_min,
        coalesce(p.zone_2_min, 0)        as zone_2_min,
        coalesce(p.zone_3_min, 0)        as zone_3_min,
        coalesce(p.zone_4_min, 0)        as zone_4_min,
        coalesce(p.zone_5_min, 0)        as zone_5_min,
        coalesce(p.strength_sessions, 0) as strength_sessions,
        coalesce(p.strength_min, 0)      as strength_min,
        coalesce(
            p.zone_1_min * 1
            + p.zone_2_min * 2
            + p.zone_3_min * 3
            + p.zone_4_min * 4
            + p.zone_5_min * 5,
            0
        ) as training_load
    from date_spine d
    left join per_day p using (day)
),

rolled as (
    select
        day,
        zone_2_min,
        training_load,
        strength_sessions,
        strength_min,
        sum(zone_2_min)         {{ rolling_trailing(7) }}  as zone_2_min_7d,
        sum(strength_sessions)  {{ rolling_trailing(7) }}  as strength_sessions_7d,
        sum(strength_min)       {{ rolling_trailing(7) }}  as strength_min_7d,
        avg(training_load)      {{ rolling_trailing(7) }}  as acute_load,
        avg(training_load)      {{ rolling_trailing(28) }} as chronic_load
    from filled
)

select
    day,
    round(zone_2_min::numeric, 1)::double precision      as zone_2_min,
    round(zone_2_min_7d::numeric, 1)::double precision   as zone_2_min_7d,
    strength_sessions_7d,
    round(strength_min_7d::numeric, 1)::double precision as strength_min_7d,
    round(training_load::numeric, 1)::double precision   as training_load,
    round(acute_load::numeric, 1)::double precision      as acute_load_7d,
    round(chronic_load::numeric, 1)::double precision    as chronic_load_28d,
    case
        when chronic_load > 0
        then round((acute_load / chronic_load)::numeric, 2)::double precision
    end as acwr
from rolled
order by day
