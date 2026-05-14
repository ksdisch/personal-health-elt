-- Compound-unique check on int_sleep_periods grain.
-- One row per (night_date, period_seq). dbt-utils is not installed in this
-- project, so we enforce the contract with a singular test.

select
    night_date,
    period_seq,
    count(*) as n
from {{ ref('int_sleep_periods') }}
group by 1, 2
having count(*) > 1
