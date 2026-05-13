-- Per-workout heart-rate recovery (HRR).
--
-- For each workout, computes:
--   peak_hr_bpm  — the maximum HR sample observed inside the workout.
--   hrr_30s     — peak_hr minus the HR sample closest to 30s after end
--   hrr_60s     — peak_hr minus the HR sample closest to 60s after end
--   hrr_120s    — peak_hr minus the HR sample closest to 120s after end
--
-- "Closest sample" guarded by a tolerance window — if the actual closest
-- sample sits e.g. 95s after end_ts_local, hrr_60s stays NULL rather than
-- silently mislabeling it. Apple Watch streams HR every ~5s during the
-- workout but post-workout sampling thins out, so we want explicit NULLs
-- where the data isn't there.
--
-- HRR is a leading aerobic-capacity signal — a 60s drop of 30+ bpm is
-- well-conditioned, <15 bpm is poor. Trended over months, HRR shifts
-- before resting HR does, so this mart is the early-warning version of
-- the RHR baseline.

{{ config(materialized='table') }}

with peaks as (
    -- Max HR reached during the workout. Using the in-workout HR samples
    -- mart rather than re-joining stg_quantities so we get the same
    -- deduplication (Apple Watch > iPhone) and zone-tagged source.
    select
        activity_type,
        workout_start_ts_local,
        workout_end_ts_local,
        workout_day_local,
        max(hr_bpm) as peak_hr_bpm
    from {{ ref('int_workout_hr_samples') }}
    group by 1, 2, 3, 4
),

post_samples as (
    -- HR samples that fell in the 3-minute window after each workout.
    -- The 3-minute cap is the outer bound; the per-target tolerance
    -- gates below decide what actually counts as a 30/60/120s sample.
    select
        w.activity_type,
        w.start_ts_local as workout_start_ts_local,
        w.end_ts_local   as workout_end_ts_local,
        hr.value         as hr_bpm,
        extract(epoch from (hr.start_ts_local - w.end_ts_local)) as secs_after_end
    from {{ ref('stg_workouts') }} w
    inner join {{ ref('stg_quantities') }} hr
        on hr.metric_name = 'HeartRate'
        and hr.start_ts_local >  w.end_ts_local
        and hr.start_ts_local <= w.end_ts_local + interval '180 seconds'
),

at_targets as (
    -- For each workout pick the post-workout HR sample closest to each
    -- target offset. `(array_agg(... order by abs(secs_after - target)))[1]`
    -- is Postgres's idiomatic "argmin" without window functions.
    select
        activity_type,
        workout_start_ts_local,
        workout_end_ts_local,
        (array_agg(hr_bpm order by abs(secs_after_end - 30)))[1]         as hr_at_30s,
        (array_agg(secs_after_end order by abs(secs_after_end - 30)))[1] as offset_at_30s,
        (array_agg(hr_bpm order by abs(secs_after_end - 60)))[1]         as hr_at_60s,
        (array_agg(secs_after_end order by abs(secs_after_end - 60)))[1] as offset_at_60s,
        (array_agg(hr_bpm order by abs(secs_after_end - 120)))[1]        as hr_at_120s,
        (array_agg(secs_after_end order by abs(secs_after_end - 120)))[1] as offset_at_120s
    from post_samples
    group by 1, 2, 3
)

select
    p.activity_type,
    p.workout_day_local                                       as day_local,
    p.workout_start_ts_local                                  as workout_start_local,
    p.workout_end_ts_local                                    as workout_end_local,
    round(p.peak_hr_bpm::numeric, 0)::int                     as peak_hr_bpm,
    round(a.hr_at_30s::numeric, 0)::int                       as hr_at_30s,
    round(a.offset_at_30s::numeric, 1)::double precision      as offset_at_30s,
    case
        when a.hr_at_30s is not null and abs(a.offset_at_30s - 30) <= 15
        then round((p.peak_hr_bpm - a.hr_at_30s)::numeric, 0)::int
    end                                                        as hrr_30s,
    round(a.hr_at_60s::numeric, 0)::int                       as hr_at_60s,
    round(a.offset_at_60s::numeric, 1)::double precision      as offset_at_60s,
    case
        when a.hr_at_60s is not null and abs(a.offset_at_60s - 60) <= 15
        then round((p.peak_hr_bpm - a.hr_at_60s)::numeric, 0)::int
    end                                                        as hrr_60s,
    round(a.hr_at_120s::numeric, 0)::int                      as hr_at_120s,
    round(a.offset_at_120s::numeric, 1)::double precision     as offset_at_120s,
    case
        when a.hr_at_120s is not null and abs(a.offset_at_120s - 120) <= 30
        then round((p.peak_hr_bpm - a.hr_at_120s)::numeric, 0)::int
    end                                                        as hrr_120s
from peaks p
left join at_targets a
    on  a.activity_type           = p.activity_type
    and a.workout_start_ts_local  = p.workout_start_ts_local
    and a.workout_end_ts_local    = p.workout_end_ts_local
order by p.workout_day_local desc, p.workout_start_ts_local desc
