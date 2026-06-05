-- Grain check on mart_experiment_effects: one row per (experiment, target
-- metric). 13_experiments.py and any consumer assume this grain. dbt_utils is
-- not installed in this project, so we enforce the contract with a singular test.

select
    experiment_name,
    target_metric,
    count(*) as n
from {{ ref('mart_experiment_effects') }}
group by 1, 2
having count(*) > 1
