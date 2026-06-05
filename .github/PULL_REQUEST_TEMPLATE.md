<!--
Thanks for the contribution. Keep this PR scoped to one logical change.
Delete any section that genuinely doesn't apply rather than leaving it blank.
-->

## Summary

<!-- One or two sentences: what this PR does and why it exists. -->

## Changes

<!-- Bullet the concrete changes, grouped by area where it helps. -->
- **ingest/**:
- **transform/** (dbt):
- **app/** (Streamlit):
- **docs/tests/**:

## Test plan

<!--
How you verified. For anything data-dependent, prefer the synthetic warehouse
(no real export, no credentials):

    uv run python -m ingest.flows.make_demo_db
    uv run pytest
    uv run dbt build --project-dir transform --profiles-dir transform

Paste the key results (counts, pass/fail), don't just assert "it works".
-->
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] `uv run dbt parse` / `dbt build` (or `make_demo_db` for synthetic verification)
- [ ] (UI changes) launched the app and eyeballed the affected page

## Contract / breaking changes

<!--
Does this touch `mart_recovery_state` (the public-API mart) or change any mart
column / unit / grain that a consumer reads?

  - YES → list the downstream consumers updated IN LOCKSTEP:
          weekly-health-review skill · daily-workout-coach · Tempo Firestore
          feed (scripts/push_recovery_state.py). Note the dbt contract tests
          (unique(day), accepted_values(recovery_signal)) still pass.
  - NO  → write "None — no contract surface touched."
-->
None — no contract surface touched.

## Notes for the reviewer

<!-- Anything non-obvious: a deliberate tradeoff, a follow-up filed in BACKLOG.md,
     a test that legitimately skips, etc. Optional. -->
