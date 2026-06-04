# Reliability: data-freshness SLO

- **Scope:** `personal-health-elt` data pipeline (single-user).
- **Owner:** Kyle Disch (solo).
- **Last reviewed:** 2026-06-04.

> This is a **single-user personal pipeline** — there is no external SLA, no
> uptime obligation, and "escalation" is a notification to one person. So the one
> reliability property worth formalizing is the one that fails *silently*: **data
> freshness**. A dead loader or a missed weekly run produces no error on its own —
> the marts just quietly stop advancing, and a Streamlit page renders stale numbers
> that *look* fine. This note turns the already-configured `dbt source freshness`
> check into an explicit SLI/SLO so "stale" has a definition.

## SLI — what we measure

**Raw data freshness** = `now() − max(loaded_at)` for each ingested raw source.

It's measured by **`dbt source freshness`**, configured at the source level in
[`transform/models/sources.yml`](../../transform/models/sources.yml)
(`loaded_at_field: loaded_at`). Freshness is set on the `raw` source as a whole
because all three primary tables share one ingest cadence (the weekly Sunday
`weekly_load`).

In scope (the primary signals that feed `mart_recovery_state`):

- `raw.quantities` — HR, HRV, RHR, weight, sleep, VO2 max, energy, steps
- `raw.categories` — sleep stages, mindfulness, symptoms
- `raw.workouts` — workout sessions

Explicitly **out of scope:** `raw.weather` and `raw.calendar_daily` have
`freshness: null`. They're optional cross-source enrichment that may be legitimately
empty (no API key configured), and an empty table would otherwise trip a false
"no rows returned" error. They are not part of the freshness objective.

## SLO — the objective

Tied to the **weekly Sunday 06:00 CT** refresh cadence (see
[`../automation.md`](../automation.md)):

| State | Threshold | Meaning |
|---|---|---|
| 🟢 **Target** | data **≤ 2 days** old | Healthy. The day after a Sunday load, freshness is ~1 day. `dbt source freshness` **warns** past this (`warn_after: 2 days`). |
| 🟡 **Degraded** | 2–7 days old | A weekly run was missed or skipped, but the data is merely *late*, not *gone*. Self-healing — the next idempotent run re-covers the gap. |
| 🔴 **Breach** | data **> 7 days** old | A loader is effectively dead or the schedule hasn't fired in over a week. `dbt source freshness` **errors** (`error_after: 7 days`). Investigate. |

The thresholds are the existing `warn_after: {2, day}` / `error_after: {7, day}`
config — this note just gives them an objective and a name. There is no formal error
budget; the practical budget is "don't let it go red."

## How it's checked

```bash
uv run dbt source freshness --project-dir transform --profiles-dir transform
# or: just freshness
```

**Not run in CI** — CI's `dbt build` executes against an empty `raw.*` schema where
freshness would always error. This is a check against the **real** local warehouse.
Today it's a manual / on-demand canary; alerting on breach is a known gap (see below).

## On breach — what to do

- **Stale because a run failed or didn't fire** → [flow-failure runbook](../runbooks/weekly-load-failure.md).
  Re-running `weekly_load` is idempotent and safe.
- **Stale because new data never reached the drop folder** (export not tapped, iCloud
  didn't sync) → [playbook: export didn't sync from iCloud](../playbooks/export-didnt-sync.md).

## Known gap

Freshness is **not alerted** — nothing pushes when the SLI goes red. This is the same
gap the flow-failure runbook flags: Pushover only fires on recovery-state *anomalies*
after a successful build, not on staleness or flow failure. Closing it (a
freshness/failure alert hook) is the natural reliability follow-up.

## Mart freshness & correctness (related)

Marts are rebuilt by `weekly_load`'s `dbt build` step immediately after each load, so
mart freshness tracks raw freshness. Mart *correctness* is a separate contract:
`mart_recovery_state` carries `unique(day)` + `accepted_values(recovery_signal)` tests
(its public-API contract — see [ADR-0005](../adr/0005-mart-recovery-state-public-api.md)
and the [data dictionary](../reference/data-dictionary.md)). Those guard *shape*, not
*recency* — this SLO covers recency.

## References

- [`transform/models/sources.yml`](../../transform/models/sources.yml) — the freshness config
- [flow-failure runbook](../runbooks/weekly-load-failure.md) ·
  [export-didn't-sync playbook](../playbooks/export-didnt-sync.md)
- [`../automation.md`](../automation.md) — the weekly schedule & known laptop-bound tradeoff
- [ADR-0005 — `mart_recovery_state` public API](../adr/0005-mart-recovery-state-public-api.md)
