-- Intermediate: every heart-rate sample that occurred INSIDE a workout.
--
-- This is the range-join at the heart of training-load analysis. For each
-- workout in stg_workouts, we pull every HeartRate sample whose local
-- timestamp falls inside [workout.start_ts_local, workout.end_ts_local],
-- tag it with a zone_number from the hr_zones seed, and compute
-- sample_duration_sec via a LEAD() over the sample's neighbours — so we
-- know how long each sample "covers" rather than just counting them.
--
-- The last sample of a workout extends to the workout's end. Samples are
-- never attributed past the workout window because the join filters first.
--
-- Materialized as a table (override of the intermediate default view)
-- because the range join across 43k HR samples × 78 workouts is expensive
-- and every downstream mart + test re-executes it. Table turns it from
-- O(downstream_reads) into O(1).
--
-- Used by mart_workout_zones (per-workout zone minutes) and, next up,
-- mart_training_load (weekly Zone 2 minutes, ACWR).
{{ config(materialized='table') }}

with joined as (
    select
        w.activity_type,
        w.start_ts_local as workout_start_ts_local,
        w.end_ts_local   as workout_end_ts_local,
        w.day_local      as workout_day_local,
        w.duration_sec   as workout_duration_sec,
        hr.start_ts_local as hr_ts_local,
        hr.value         as hr_bpm
    from {{ ref('stg_workouts') }} w
    inner join {{ ref('stg_quantities') }} hr
        on hr.metric_name = 'HeartRate'
        and hr.start_ts_local >= w.start_ts_local
        and hr.start_ts_local <= w.end_ts_local
),

with_zones as (
    select
        j.*,
        z.zone_number
    from joined j
    left join {{ ref('hr_zones') }} z
        on j.hr_bpm between z.hr_low and z.hr_high
),

with_durations as (
    select
        activity_type,
        workout_start_ts_local,
        workout_end_ts_local,
        workout_day_local,
        workout_duration_sec,
        hr_ts_local,
        hr_bpm,
        zone_number,
        extract(epoch from
            coalesce(
                lead(hr_ts_local) over (
                    partition by activity_type, workout_start_ts_local
                    order by hr_ts_local
                ),
                workout_end_ts_local
            ) - hr_ts_local
        )::double precision as sample_duration_sec
    from with_zones
)

select * from with_durations
