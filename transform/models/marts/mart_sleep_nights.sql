-- Per-night sleep rollup with a composite sleep score.
--
-- Inputs:
--   int_sleep_segments    — per-segment stages attributed to a night
--   sleep_score_weights   — single-row seed with composite-score parameters
--
-- Output:
--   One row per night_date. Columns include total time in bed, time asleep,
--   sleep_efficiency_pct (asleep / in_bed), per-stage minutes, REM and deep
--   percentages of time asleep, awakening_count, bed/wake clock times, and
--   a composite_score in [0, 100].
--
-- Composite score formula (weights from sleep_score_weights seed):
--   composite_score = max(0, round(
--     w_eff   * min(100, 100 * eff_pct  / target_eff)
--   + w_rem   * min(100, 100 * rem_pct  / target_rem)
--   + w_deep  * min(100, 100 * deep_pct / target_deep)
--   - w_fragmentation * awakening_count
--   , 1))
-- Positive weights sum to 1.0, so the maximum of the three weighted terms
-- is 100. Fragmentation deducts points directly (1.5 per awakening with the
-- default weight).

with per_night as (
    select
        night_date,
        sum(case when sleep_stage = 'asleepREM'         then duration_min else 0 end) as rem_min,
        sum(case when sleep_stage = 'asleepDeep'        then duration_min else 0 end) as deep_min,
        sum(case when sleep_stage = 'asleepCore'        then duration_min else 0 end) as core_min,
        sum(case when sleep_stage = 'asleepUnspecified' then duration_min else 0 end) as unspecified_asleep_min,
        sum(case when sleep_stage = 'awake'             then duration_min else 0 end) as awake_min,
        sum(case when sleep_stage = 'inBed'             then duration_min else 0 end) as in_bed_explicit_min,
        sum(case when sleep_stage = 'awake'             then 1 else 0 end)            as awakening_count,
        min(start_ts_local) as bedtime_local,
        max(end_ts_local)   as wake_time_local
    from {{ ref('int_sleep_segments') }}
    group by 1
),

derived as (
    select
        night_date,
        rem_min,
        deep_min,
        core_min,
        unspecified_asleep_min,
        awake_min,
        in_bed_explicit_min,
        awakening_count,
        bedtime_local,
        wake_time_local,
        (rem_min + deep_min + core_min + unspecified_asleep_min) as time_asleep_min,
        case
            when in_bed_explicit_min > 0 then in_bed_explicit_min
            else extract(epoch from (wake_time_local - bedtime_local)) / 60.0
        end as time_in_bed_min
    from per_night
),

with_pcts as (
    select
        *,
        round(100.0 * time_asleep_min / nullif(time_in_bed_min, 0), 1) as sleep_efficiency_pct,
        round(100.0 * rem_min          / nullif(time_asleep_min, 0), 1) as rem_pct_of_sleep,
        round(100.0 * deep_min         / nullif(time_asleep_min, 0), 1) as deep_pct_of_sleep
    from derived
),

with_composite as (
    select
        p.*,
        greatest(0, round(
            s.weight_efficiency * least(100, 100 * coalesce(p.sleep_efficiency_pct, 0) / s.target_efficiency_pct) +
            s.weight_rem        * least(100, 100 * coalesce(p.rem_pct_of_sleep,    0) / s.target_rem_pct) +
            s.weight_deep       * least(100, 100 * coalesce(p.deep_pct_of_sleep,   0) / s.target_deep_pct) -
            s.weight_fragmentation * p.awakening_count
        , 1)) as composite_score
    from with_pcts p
    cross join {{ ref('sleep_score_weights') }} s
)

select
    night_date,
    round(time_in_bed_min::numeric, 1)::double precision      as time_in_bed_min,
    round(time_asleep_min::numeric, 1)::double precision      as time_asleep_min,
    sleep_efficiency_pct::double precision                    as sleep_efficiency_pct,
    round(rem_min::numeric, 1)::double precision              as rem_min,
    round(deep_min::numeric, 1)::double precision             as deep_min,
    round(core_min::numeric, 1)::double precision             as core_min,
    round(awake_min::numeric, 1)::double precision            as awake_min,
    rem_pct_of_sleep::double precision                        as rem_pct_of_sleep,
    deep_pct_of_sleep::double precision                       as deep_pct_of_sleep,
    awakening_count,
    bedtime_local,
    wake_time_local,
    composite_score::double precision                         as composite_score
from with_composite
order by night_date
