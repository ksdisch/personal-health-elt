# ADR-0005: Treat `mart_recovery_state` as a versioned public API with lockstep consumers

- **Status:** Accepted
- **Date:** 2026-05-17
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0007 (the `accepted_values` test form that enforces the contract), `transform/models/marts/mart_recovery_state.sql`, `transform/models/marts/schema.yml`, `docs/reference/data-dictionary.md`

## Context

`mart_recovery_state` is the apex daily-grain mart: one row per day combining RHR,
HRV, training load, ACWR, and a rule-based `recovery_signal`. It started with one
consumer (the `weekly-health-review` Claude skill) and has since grown to **three**:

1. `weekly-health-review` skill (Markdown briefing via `scripts/weekly_health_review.py`),
2. the Tempo PWA Firestore feed (`scripts/push_recovery_state.py`),
3. the `daily-workout-coach` skill (`scripts/daily_workout_coach.py`).

These consumers live partly outside this repo (a separate skills directory, a
separate PWA repo). A silent schema change here — renaming a column, dropping a
field, changing a unit, or altering the `recovery_signal` vocabulary — breaks them
without warning, and the break surfaces far from its cause (a wrong Firestore
readiness band, a skill that errors mid-briefing).

## Decision

We treat `mart_recovery_state` as a **versioned public API**, not an internal
model. Specifically:

- Its schema is a **contract**, documented in `docs/reference/data-dictionary.md`
  (14 columns + the `recovery_signal` enum + the Firestore document shape). This
  repo is the canonical source of truth for all three consumers.
- The contract is **machine-enforced** by dbt tests in `schema.yml`:
  `unique(day)`, `not_null(day/is_today/recovery_signal)`, and
  `accepted_values(recovery_signal)` (see ADR-0007 for the test syntax).
- Any contract change requires updating, **in the same change**, the data
  dictionary and all three consumer scripts — "lockstep". The dbt test fails
  before any consumer does, giving an in-repo early warning.
- The model file carries a header comment marking it contract-protected, and
  CLAUDE.md flags it off-limits to casual edits.

## Alternatives considered

- **Treat it as a normal internal mart** — rejected: that's the status quo that
  makes silent breakage possible; the consumers have no other contract surface.
- **Version the mart by name** (`mart_recovery_state_v2`) — rejected as premature:
  no breaking change has been needed yet, and additive columns don't break the
  Firestore feed (it serializes whatever columns the query returns) or the skills
  (they read named columns). We adopt name-versioning only if/when a true breaking
  change arrives.
- **Document the contract in each consumer repo** — rejected: three copies drift.
  One canonical doc here, linked from the others, is the single source of truth.
- **A formal schema registry / data contract tool** — rejected as overkill for a
  solo project; the dbt tests + the data dictionary already provide enforcement +
  documentation.

## Consequences

**Positive:**
- A breaking change cannot land green: the `accepted_values`/`unique` tests fail
  in CI/`dbt build` before a consumer ever sees bad data.
- One documented contract; the two external consumers link back to it.
- Additive evolution (new columns) is safe and propagates automatically to the
  Firestore feed.

**Negative:**
- Real coordination cost: a genuine contract change is a multi-file, multi-repo
  edit (data dictionary + three scripts). This friction is the point, but it is
  friction.

**Neutral but worth noting:**
- dbt `exposures` for `weekly_health_review` and `daily_workout_coach` are declared
  in `schema.yml`, making the dependency visible in the dbt DAG.

## References

- `transform/models/marts/mart_recovery_state.sql` — the contract-protected model.
- `transform/models/marts/schema.yml` — the enforcing tests + exposures.
- `docs/reference/data-dictionary.md` — the human-readable contract (§1–§3).
- CLAUDE.md → "`mart_recovery_state` is a public API".
