# Phase brief — `<phase number>: <phase name>`

> Fill in every field. Pass the completed brief as the worker's prompt
> verbatim. Workers stay strictly inside "Files in scope" and surface
> anything else as OPEN QUESTIONS.

## Goal
<One sentence. What this dispatch accomplishes. e.g. "Lift schema.yml
rigor on the three new dbt artifacts to match the public-API mart pattern."

## Worker
<`dbt-modeler` | `streamlit-page-wright` | `verifier` | `loader-engineer`>

## Files in scope (worker MAY read AND edit)
- <absolute or repo-relative path>
- <path>

## Files OUT of scope (worker MUST NOT touch, even if it sees a bug)
- <path>
- <path>
<Always list `transform/models/marts/mart_recovery_state.sql` here unless
the task is explicitly an authorized contract change.>

## Constraints
- <e.g. "No new dependencies — uv.lock must not change.">
- <e.g. "Existing dbt tests must still pass — do not loosen any test to
  make a new one pass.">
- <e.g. "Do not run `dbt seed` — hr_zones already loaded.">

## Inputs the worker can rely on
- <e.g. "Postgres is running and reachable via `transform/profiles.yml`.">
- <e.g. "Previous phase's worker confirmed `dbt parse` is clean.">

## Success criteria (each item must be testable / observable)
- <e.g. "`uv run dbt parse` exits 0">
- <e.g. "`mart_daily_signals.recovery_signal` has an `accepted_values`
  test matching `mart_recovery_state.recovery_signal`'s value list">
- <e.g. "All three new dbt models build without errors">

## Return format (worker pastes this back)

```
WORKER: <agent name>
DONE: <one sentence>
CHANGED FILES:
  - <path>
COMMANDS RUN:
  - <cmd> → exit <n>
<task-specific lines from the worker's agent definition>
OPEN QUESTIONS:
  - <or "none">
```

## Escalation
If two attempts at the same fix fail, STOP and return OPEN QUESTIONS
describing what you tried and what blocked you. Do not loosen tests,
disable hooks, or push to git to make a check pass.
