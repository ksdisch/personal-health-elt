-- Staging for raw.experiment_effects: the Python causal-inference results
-- (ITS level change with HAC errors, permutation p-value, difference-in-
-- differences) re-entering the warehouse so they flow through the normal
-- staging -> marts layering rather than being materialised straight from Python.
-- See docs/adr/0009.
--
-- Responsibilities only: pass-through + convert the computed_at audit stamp from
-- UTC to America/Chicago (TZ normalisation lives in staging, per CLAUDE.md).
-- Verdicts and the experiment-metadata join are business logic -> the mart.

select
    experiment_name,
    target_metric,
    cutoff_date,
    level_change,
    level_ci_low,
    level_ci_high,
    slope_change,
    hac_p_value,
    placebo_p_value,
    did_estimate,
    n_pre,
    n_post,
    confounded,
    (computed_at at time zone 'America/Chicago')::timestamp as computed_at_local
from {{ source('raw', 'experiment_effects') }}
