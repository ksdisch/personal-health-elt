-- PUBLIC API: consumed by the `weekly-health-review` Claude skill.
--
-- Schema changes here require updating that skill in lockstep. Treat this
-- like a versioned interface — never break it silently.
--
-- One row per day combining the three signals the skill needs to reason
-- about recovery and prescribe the next workout:
--
--   Sleep-adjacent physiology  → rhr_bpm, hrv_ms (from daily marts)
--   Training load              → training_load_7d, acwr (from mart_training_load)
--   Context                    → day, is_today, days_since_last_workout
--
-- The `recovery_signal` is a simple rule-based bucket (well_recovered /
-- neutral / strained) derived from ACWR + HRV trend. The skill can still
-- reason about the raw inputs — this column is a convenience, not a gate.

with daily_signals as (
    select
        coalesce(rhr.day, hrv.day, tl.day) as day,
        rhr.resting_heart_rate             as rhr_bpm,
        hrv.hrv_ms,
        tl.zone_2_min                      as zone_2_min_today,
        tl.zone_2_min_7d,
        tl.strength_sessions_7d,
        tl.training_load                   as training_load_today,
        tl.acute_load_7d,
        tl.chronic_load_28d,
        tl.acwr
    from {{ ref('mart_daily_rhr') }} rhr
    full outer join {{ ref('mart_daily_hrv') }} hrv using (day)
    full outer join {{ ref('mart_training_load') }} tl using (day)
),

with_hrv_trend as (
    select
        *,
        avg(hrv_ms) over (
            order by day rows between 7 preceding and 1 preceding
        ) as hrv_ms_7d_prior_avg
    from daily_signals
),

with_workout_gap as (
    select
        *,
        -- distance (in days) from this row back to the last day with a workout
        day - max(case when training_load_today > 0 then day end) over (
            order by day rows between unbounded preceding and current row
        ) as days_since_last_workout
    from with_hrv_trend
),

with_signal as (
    select
        *,
        case
            -- Not enough history to judge
            when hrv_ms is null or hrv_ms_7d_prior_avg is null or acwr is null
                then 'insufficient_data'
            -- Red flags: ACWR spiking OR HRV well below baseline
            when acwr > 1.5
                then 'strained'
            when hrv_ms < hrv_ms_7d_prior_avg * 0.85
                then 'strained'
            -- Green: recent load stable, HRV at or above baseline
            when acwr between 0.8 and 1.3
                and hrv_ms >= hrv_ms_7d_prior_avg * 0.95
                then 'well_recovered'
            else 'neutral'
        end as recovery_signal
    from with_workout_gap
)

select
    day,
    (day = current_date) as is_today,
    rhr_bpm,
    hrv_ms,
    round(hrv_ms_7d_prior_avg::numeric, 1)::double precision as hrv_ms_7d_prior_avg,
    zone_2_min_today,
    zone_2_min_7d,
    strength_sessions_7d,
    training_load_today,
    acute_load_7d,
    chronic_load_28d,
    acwr,
    days_since_last_workout,
    recovery_signal
from with_signal
order by day
