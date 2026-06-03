<!--
  Postmortem template for personal-health-elt.

  HOW TO USE
  ----------
  1. Copy this file to docs/postmortems/YYYY-MM-DD-<incident-slug>.md
     (use the date the incident STARTED, kebab-case slug — sorts chronologically).
  2. Delete this comment block and fill in every section. Replace [bracketed]
     placeholders; the *italic guidance* lines tell you what belongs in each
     section — delete them once written.
  3. Blameless: aim every "what went poorly" / action item at a system or
     process, never a person (even though "the team" here is one person).

  REAL FAILURE SURFACES THIS PIPELINE HAS (use as examples / sanity check):
    - Scheduled weekly_load never fired (Mac asleep at 06:00 Sun) → stale marts.
      Recovery: docs/runbooks/weekly-load-failure.md (re-run is idempotent).
    - dbt build drift — a model or contract test (accepted_values on
      recovery_signal, unique(day)) starts failing on real data the synthetic
      CI fixtures didn't cover.
    - Notification pipeline — Pushover outage / bad rules file (non-fatal by
      design, but a silent miss means no anomaly alert went out).
    - DATA LOSS (the real one): a test/cleanup path running
      `TRUNCATE raw.file_inventory CASCADE` against the live DB wiped 286,770
      rows of real Apple Health data. This is the canonical S1 to write up if it
      recurs — see CHANGELOG v0.3.0 for the root-cause fix.
-->

# Postmortem: [Incident name]

- **Date:** YYYY-MM-DD *(incident start date)*
- **Duration:** [start → end, total time the system was degraded]
- **Severity:** [S1 | S2 | S3]
- **Author:** Kyle Disch
- **Status:** Draft | Under review | Final
- **Related:** [links to the runbook used, the offending PR/commit, the
  CHANGELOG entry, relevant ADRs]

> **Severity scale** (single-user pipeline — no external SLA, so severity tracks
> *data integrity* and *consumer impact*, not uptime):
> - **S1 — Data loss / corruption.** Real Apple Health rows destroyed, duplicated,
>   or the `mart_recovery_state` contract silently broken (a consumer read wrong
>   data). Highest urgency; usually irreversible without re-ingest.
> - **S2 — Stale / missing data.** Marts didn't refresh — a missed or failed
>   `weekly_load`, a failed `dbt build`. Consumers read *old* but *correct* data.
>   Self-healing via idempotent re-run.
> - **S3 — Enrichment / notification degradation.** A non-fatal leg degraded
>   (weather/calendar backfill, Pushover anomaly alert, Tempo Firestore push).
>   Core marts unaffected.

## Summary

*2–4 sentences, readable standalone: what happened, the impact, the root cause,
and how it was resolved. Someone scanning postmortems six months from now should
get the gist without scrolling.*

## Impact

- **Data integrity:** *Any rows lost / duplicated / corrupted? Did the
  `mart_recovery_state` contract (`unique(day)`, `accepted_values` on
  `recovery_signal`) hold throughout? State "none" explicitly if so.*
- **Mart freshness:** *How stale did the marts get — which day was the latest
  `mart_recovery_state` row during the incident vs. expected?*
- **Consumer impact:** *Which of the three `mart_recovery_state` consumers read
  degraded/stale data — the `weekly-health-review` skill, the Tempo PWA Firestore
  feed, the `daily-workout-coach`? Did a Sunday-evening briefing go out wrong?*
- **Personal / operational impact:** *Manual re-runs needed, re-ingest required,
  time spent, any decision made on bad data.*

## Timeline

*America/Chicago (CT) times — the pipeline's own timezone. One line per material
event: first signal, first response, root cause identified, mitigation applied,
all clear. Skip the noise.*

- **HH:MM** — [Scheduled `weekly_load` fires / the change that introduced the issue]
- **HH:MM** — [First signal — stale marts noticed, `dbt source freshness` warning,
  failed Prefect run, error in `/tmp/health-weekly-load.err.log`]
- **HH:MM** — [Investigation begins]
- **HH:MM** — [Root cause identified]
- **HH:MM** — [Mitigation applied — re-run, model fix, re-ingest]
- **HH:MM** — [All clear — marts fresh, contract tests green, consumers reconciled]

## Root cause

*The real "why," not just the proximate trigger — the underlying systems/process
gap. Five-whys is useful when the cause isn't obvious. Two paragraphs max; if it
takes more, you may be conflating several incidents.*

## Data-integrity verification

*Pipeline-specific — do not skip on any S1/S2. Record the actual checks you ran
to confirm the warehouse is sound after mitigation. Paste the real numbers.*

- [ ] `raw.file_inventory` row count intact / grew as expected (not truncated):
      `select count(*) from raw.file_inventory;` → [N]
- [ ] No duplicate rows introduced (idempotency held):
      `raw.quantities` / `raw.workouts` / `raw.categories` counts → [N]
- [ ] `mart_recovery_state` contract green — `dbt test --select mart_recovery_state`
      (`unique(day)` + `accepted_values(recovery_signal)`) → [pass/fail]
- [ ] Latest `mart_recovery_state.day` matches the expected most-recent date → [date]
- [ ] All three consumers reconciled (weekly-review / Tempo Firestore / coach read
      the corrected state) → [confirmed?]

## What went well

*Be generous — reinforce what worked. "Idempotency meant the re-run was a no-op
and cost me nothing" is worth recording.*

- ...

## What went poorly

*Be honest, aim at systems/process. "There's no push alert on flow failure, so I
only noticed the stale data days later" is uncomfortable but actionable.*

- ...

## Where we got lucky

*Surfaces fragility this incident didn't fully test. "If the truncate had run the
day before a fresh export instead of after, the data would have been
unrecoverable." That's a future S1 if you don't write it down now.*

- ...

## Action items

*Concrete, owned, dated. Balance the types — all "Prevent" and no "Detect"
suggests you're papering over a deeper gap. File each as a `BACKLOG.md` entry and
link it.*

| # | Action | Owner | Due | Type |
|---|--------|-------|-----|------|
| 1 | ... | Kyle Disch | YYYY-MM-DD | Prevent / Detect / Mitigate / Process |
| 2 | ... | Kyle Disch | YYYY-MM-DD | ... |
| 3 | ... | Kyle Disch | YYYY-MM-DD | ... |

## Lessons

*Patterns to remember, not item-level fixes. What does this teach about the
pipeline, the idempotency contract, or how you operate it solo?*

- ...

## References

- **Runbook used:** [e.g. `../runbooks/weekly-load-failure.md`]
- **Offending change:** [PR # / commit SHA]
- **CHANGELOG entry:** [`../../CHANGELOG.md`]
- **Related ADRs:** [e.g. `../adr/0003-two-level-idempotency.md`,
  `../adr/0005-mart-recovery-state-public-api.md`]
- **Backlog follow-ups:** [links to the action-item entries in `../../BACKLOG.md`]
