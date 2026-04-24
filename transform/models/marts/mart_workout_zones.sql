-- Per-workout zone breakdown: how much time each workout spent in each
-- of the 5 HR zones (defined by seeds/hr_zones.csv). Zero means "no HR
-- samples in that zone"; NULL never appears for zone_*_sec (coalesced).
--
-- Consumer: Streamlit workouts view + the weekly mart_training_load,
-- which sums zone_2_sec across the trailing 7 days.

with per_workout as (
    select
        workout_day_local                      as day_local,
        activity_type,
        workout_start_ts_local                 as start_ts_local,
        workout_duration_sec                   as duration_sec,
        coalesce(sum(sample_duration_sec) filter (where zone_number = 1), 0) as zone_1_sec,
        coalesce(sum(sample_duration_sec) filter (where zone_number = 2), 0) as zone_2_sec,
        coalesce(sum(sample_duration_sec) filter (where zone_number = 3), 0) as zone_3_sec,
        coalesce(sum(sample_duration_sec) filter (where zone_number = 4), 0) as zone_4_sec,
        coalesce(sum(sample_duration_sec) filter (where zone_number = 5), 0) as zone_5_sec,
        count(*)                               as hr_sample_count,
        round(avg(hr_bpm)::numeric, 1)::double precision as avg_hr_bpm,
        max(hr_bpm)                            as max_hr_bpm
    from {{ ref('int_workout_hr_samples') }}
    group by 1, 2, 3, 4
)

select * from per_workout
order by start_ts_local
