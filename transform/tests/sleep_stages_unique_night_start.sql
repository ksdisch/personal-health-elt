-- Compound-unique check on mart_sleep_stages grain.
-- The hypnogram is one row per (night_date, stage_start_local). A duplicate
-- would mean two stages claim to start at the same instant on the same
-- night, which breaks ordered rendering. dbt_utils is not installed in this
-- project, so we enforce the contract with a singular test.

select
    night_date,
    stage_start_local,
    count(*) as n
from {{ ref('mart_sleep_stages') }}
group by 1, 2
having count(*) > 1
