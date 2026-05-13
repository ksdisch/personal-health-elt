-- Daily anomaly bands for tracked physiological metrics.
-- (Promoted from int_daily_anomaly_bands when layer inversion was fixed in PR #1 review.)
--
-- For each metric, computes a rolling 28-day mean and sample-std (over the
-- 28 days STRICTLY before today, not including today), then derives a
-- z-score = (value - rolling_mean) / rolling_std. The Anomaly Dashboard
-- flags days with |z| > 2.
--
-- 1 PRECEDING (not CURRENT ROW) — exclude today from its own baseline so
-- a fresh anomaly doesn't dilute the threshold it has to clear. This is
-- the textbook framing for early-warning rolling z-scores.
--
-- Tall format: one row per (metric, day). Streamlit filters by metric.
-- Sleep duration will join here once the categories loader lands and a
-- mart_daily_sleep is built — same window function, just append a third
-- branch to the union.

with combined as (
    select
        day,
        'rhr_bpm'::text       as metric,
        resting_heart_rate    as value
    from {{ ref('mart_daily_rhr') }}

    union all

    select
        day,
        'hrv_ms'::text  as metric,
        hrv_ms          as value
    from {{ ref('mart_daily_hrv') }}
),

bands as (
    select
        day,
        metric,
        value,
        avg(value)
            {{ rolling_trailing(28, partition_by='metric', inclusive=false) }}
            as rolling_mean,
        stddev_samp(value)
            {{ rolling_trailing(28, partition_by='metric', inclusive=false) }}
            as rolling_std
    from combined
)

select
    day,
    metric,
    value,
    rolling_mean,
    rolling_std,
    case
        when rolling_std > 0
            then (value - rolling_mean) / rolling_std
    end as z_score
from bands
order by metric, day
