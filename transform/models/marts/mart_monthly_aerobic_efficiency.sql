-- Monthly aerobic efficiency: time-weighted avg HR within Zone 2 plus total
-- Zone 2 minutes per calendar month.
--
-- The slow-moving fitness signal: as the aerobic base builds, average HR
-- *within* Zone 2 drifts toward the low bound of the zone — a fitness
-- improvement that's invisible in raw HR or pace numbers.
--
-- Time-weighting (sum(hr * sample_duration) / sum(sample_duration))
-- prevents periods with denser HR sampling from skewing the mean. The
-- sample_duration_sec column is precomputed in int_workout_hr_samples via
-- LEAD over the workout's neighbouring samples.
--
-- Zone 2 = zone_number 2 = 'aerobic_base' = 136–153 bpm (per hr_zones.csv,
-- the user's measured Zone 2). Filtering by zone_number rather than
-- zone_name keeps the join arithmetic; the seed is the source of truth.

with z2_samples as (
    select
        date_trunc('month', workout_start_ts_local)::date as month,
        hr_bpm,
        sample_duration_sec
    from {{ ref('int_workout_hr_samples') }}
    where zone_number = 2
      and sample_duration_sec > 0
)

select
    month,
    (sum(hr_bpm * sample_duration_sec) / nullif(sum(sample_duration_sec), 0))
        ::double precision                         as avg_z2_hr,
    (sum(sample_duration_sec) / 60.0)::double precision as z2_minutes,
    count(*)                                       as sample_count
from z2_samples
group by 1
order by 1
