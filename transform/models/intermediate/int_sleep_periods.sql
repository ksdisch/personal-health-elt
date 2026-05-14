-- Intermediate: contiguous-sleep periods within a night.
--
-- Within a night_date (already attributed by int_sleep_segments via the
-- noon-to-noon partition), the time between two consecutive ASLEEP segments
-- defines the gap. Gaps longer than 120 minutes split the night into
-- separate periods. Critically, a long single `awake` segment in the
-- middle of a night counts as a gap — what matters is "time since last
-- sleep," not "time since last segment." (A 5-hour awake stage between
-- a brief afternoon nap and the main night sleep would otherwise look
-- like a non-gap since the segments are contiguous in time.)
--
-- Period bounds are defined by the first and last ASLEEP segment in the
-- period. awake / inBed segments are then range-joined back to the
-- period whose bounds enclose their start — so a 3am-3:30am bathroom
-- awakening counts toward its surrounding period, but a 5-hour
-- between-periods awake stage belongs to no period.
--
-- A "main sleep" + an afternoon nap therefore produce two rows rather
-- than one bloated rollup. is_main_period flags the longest period per
-- night (tiebreaker: earliest start). Periods shorter than 5 minutes of
-- total span are filtered out as watch-misfire noise. mart_sleep_nights
-- filters to is_main_period = true; mart_sleep_naps takes the rest.
--
-- Grain: (night_date, period_seq). period_seq is a 1-indexed within-night
-- identifier; for stable cross-run joins use (night_date, period_start_local).

{% set gap_threshold_min = 120 %}
{% set min_period_span_min = 5 %}

with asleep_with_gap as (
    select
        night_date,
        start_ts_local,
        end_ts_local,
        extract(epoch from (
            start_ts_local
            - lag(end_ts_local) over (partition by night_date order by start_ts_local)
        )) / 60.0 as gap_from_prev_asleep_min
    from {{ ref('int_sleep_segments') }}
    where is_asleep
),

asleep_with_period_seq as (
    select
        night_date,
        start_ts_local,
        end_ts_local,
        1 + sum(case when gap_from_prev_asleep_min > {{ gap_threshold_min }} then 1 else 0 end)
            over (
                partition by night_date
                order by start_ts_local
                rows between unbounded preceding and current row
            ) as period_seq
    from asleep_with_gap
),

period_bounds as (
    select
        night_date,
        period_seq,
        min(start_ts_local) as period_start_local,
        max(end_ts_local)   as period_end_local
    from asleep_with_period_seq
    group by 1, 2
),

segments_in_period as (
    select
        pb.night_date,
        pb.period_seq,
        pb.period_start_local,
        pb.period_end_local,
        s.sleep_stage,
        s.duration_min
    from {{ ref('int_sleep_segments') }} s
    join period_bounds pb
        on  s.night_date = pb.night_date
        and s.start_ts_local >= pb.period_start_local
        and s.start_ts_local <  pb.period_end_local
),

per_period as (
    select
        night_date,
        period_seq,
        period_start_local,
        period_end_local,
        sum(case when sleep_stage = 'asleepREM'  then duration_min else 0 end) as rem_min,
        sum(case when sleep_stage = 'asleepDeep' then duration_min else 0 end) as deep_min,
        sum(case when sleep_stage = 'asleepCore' then duration_min else 0 end) as core_min,
        sum(case when sleep_stage in ('asleepUnspecified', 'asleep') then duration_min else 0 end) as unspecified_asleep_min,
        sum(case when sleep_stage = 'awake'      then duration_min else 0 end) as awake_min,
        sum(case when sleep_stage = 'inBed'      then duration_min else 0 end) as in_bed_explicit_min,
        sum(case when sleep_stage = 'awake'      then 1 else 0 end)            as awakening_count
    from segments_in_period
    group by 1, 2, 3, 4
),

with_durations as (
    select
        *,
        (rem_min + deep_min + core_min + unspecified_asleep_min) as time_asleep_min,
        extract(epoch from (period_end_local - period_start_local)) / 60.0 as period_duration_min
    from per_period
),

filtered as (
    select *
    from with_durations
    where period_duration_min >= {{ min_period_span_min }}
),

with_main_flag as (
    select
        *,
        row_number() over (
            partition by night_date
            order by period_duration_min desc, period_start_local asc
        ) = 1 as is_main_period
    from filtered
)

select
    night_date,
    period_seq,
    period_start_local,
    period_end_local,
    period_duration_min,
    time_asleep_min,
    rem_min,
    deep_min,
    core_min,
    unspecified_asleep_min,
    awake_min,
    in_bed_explicit_min,
    awakening_count,
    is_main_period
from with_main_flag
order by night_date, period_start_local
