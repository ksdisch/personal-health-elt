-- Per-nap rollup. One row for each non-main sleep period that contains any
-- actual sleep time.
--
-- "Nap" here means any contiguous sleep period that is not the longest
-- period of the night (see int_sleep_periods.is_main_period). The
-- noon-to-noon night attribution means an afternoon nap on day D rolls
-- into night_date = D + 1 if it started after noon. nap_date below is the
-- calendar date the nap actually happened on (period_start_local::date),
-- which is the more intuitive grain for "naps you took today."
--
-- Sibling to mart_sleep_nights. Together they recover the full picture
-- without polluting either: the nights mart stays clean for composite-score
-- and efficiency analysis, the naps mart keeps napping visible.
--
-- Grain: (night_date, period_seq) from upstream; nap_start_local is also a
-- unique key in practice (two naps can't start at the same instant).

select
    period_start_local::date            as nap_date,
    night_date,
    period_seq,
    period_start_local                  as nap_start_local,
    period_end_local                    as nap_end_local,
    round(period_duration_min::numeric, 1)::double precision as duration_min,
    round(time_asleep_min::numeric, 1)::double precision     as time_asleep_min,
    awakening_count
from {{ ref('int_sleep_periods') }}
where not is_main_period
  and time_asleep_min > 0
order by nap_start_local
