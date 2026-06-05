-- Personal causal-inference results: one row per (experiment, target metric).
--
-- The estimates come from ingest/analysis/causal.py (interrupted time series
-- with Newey-West HAC standard errors + a permutation/placebo p-value + a
-- secondary difference-in-differences). This mart joins the experiment metadata
-- (hypothesis / window from the experiments seed) and derives a single,
-- honestly-caveated verdict.
--
-- A verdict of `likely_decrease` / `likely_increase` requires BOTH the HAC p and
-- the placebo p to clear 0.05, at least 10 observations on each side, and a
-- window not confounded by an overlapping experiment — deliberately
-- conservative for n-of-1 data. DiD is reported, never gating.

{{ config(materialized='table') }}

with effects as (
    select * from {{ ref('stg_experiment_effects') }}
),

experiments as (
    select name, start_date, end_date, hypothesis
    from {{ ref('experiments') }}
)

select
    e.experiment_name,
    e.target_metric,
    x.hypothesis,
    x.start_date,
    x.end_date,
    e.cutoff_date,
    e.level_change,
    e.level_ci_low,
    e.level_ci_high,
    e.slope_change,
    e.hac_p_value,
    e.placebo_p_value,
    e.did_estimate,
    e.n_pre,
    e.n_post,
    e.confounded,
    case
        when e.level_change is null then 'insufficient_data'
        when e.confounded then 'confounded'
        when e.hac_p_value < 0.05
            and e.placebo_p_value < 0.05
            and e.n_pre >= 10
            and e.n_post >= 10
            then case when e.level_change < 0 then 'likely_decrease' else 'likely_increase' end
        else 'no_clear_effect'
    end as verdict
from effects e
left join experiments x on x.name = e.experiment_name
order by e.experiment_name, e.target_metric
