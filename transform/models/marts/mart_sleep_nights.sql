-- Per-night sleep rollup with a composite sleep score.
--
-- Inputs:
--   int_sleep_periods     — per-period rollup, with is_main_period flag
--   sleep_score_weights   — single-row seed with composite-score parameters
--
-- Scope: rolls up the MAIN sleep period only. A same-day nap is a separate
-- period (gap > 2h from the main run, by definition of int_sleep_periods)
-- and lands in mart_sleep_naps instead. This keeps time-in-bed honest and
-- prevents the composite score from being punished for napping. Before
-- this split a nap+main collision could inflate time_in_bed to 14h and
-- crater sleep_efficiency_pct.
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

with main_period as (
    select
        night_date,
        period_start_local as bedtime_local,
        period_end_local   as wake_time_local,
        period_duration_min,
        time_asleep_min,
        rem_min,
        deep_min,
        core_min,
        unspecified_asleep_min,
        awake_min,
        in_bed_explicit_min,
        awakening_count
    from {{ ref('int_sleep_periods') }}
    where is_main_period
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
        time_asleep_min,
        case
            when in_bed_explicit_min > 0 then in_bed_explicit_min
            else period_duration_min
        end as time_in_bed_min
    from main_period
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
