# ADR-0001: Normalize timezones to America/Chicago at the staging layer only

- **Status:** Accepted
- **Date:** 2026-04-24
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0002 (dedup, same staging window), `transform/models/staging/stg_quantities.sql`, `docs/reference/data-dictionary.md`

## Context

Apple HealthKit exports land timestamps as UTC (`TIMESTAMPTZ`) in `raw.*`. Every
downstream question this project answers is a *local* question: "what was my
resting HR **on Tuesday**", "how many Zone 2 minutes **this week**", "which
**night** did I sleep poorly". A sample taken at 02:00 UTC belongs to the
previous local evening; getting the day boundary wrong silently misattributes
data to the wrong day, which corrupts every daily-grain mart and the rolling
windows built on them.

The user is single-timezone (America/Chicago), so this is not a
multi-tenant/per-user-TZ problem — it is a "convert once, correctly, in one
place" problem. The failure mode to avoid is TZ conversion scattered across
staging, intermediate, and marts, where it's impossible to audit whether a given
timestamp is UTC or local, and where two models can disagree.

## Decision

We convert UTC → `America/Chicago` exactly once, at the **staging** layer
(`stg_quantities`, `stg_workouts`, `stg_categories`, `stg_weather`,
`stg_calendar`), producing `*_local` columns. Intermediate and marts treat local
time as authoritative and never call `at time zone` again. If anything downstream
sees a UTC timestamp, that is by definition a staging bug — not a "fix it
everywhere" situation.

## Alternatives considered

- **Convert at the marts layer (as late as possible)** — rejected: every mart
  would re-implement the same conversion, day-boundary logic would be duplicated
  across 17 marts, and a single inconsistency would be invisible until a chart
  looked wrong.
- **Keep everything UTC, convert only in the Streamlit/skill presentation layer**
  — rejected: day-grain aggregation (`group by day`) happens *in SQL*, upstream
  of presentation. You cannot defer the day boundary to the app without pushing
  grouping logic into the app too.
- **Store a generated local-time column in `raw.*`** — rejected: `raw.*` is a
  faithful landing zone owned by the loaders; putting transformation logic there
  violates the ELT boundary and couples the loader to a presentation timezone.

## Consequences

**Positive:**
- One auditable conversion point. "Is this UTC or local?" has a one-word answer
  keyed on the layer.
- Day-grain marts and rolling windows denominate against correct local days.
- Loaders stay timezone-agnostic; `raw.*` remains a literal mirror of the export.

**Negative:**
- The timezone is currently hardcoded to `America/Chicago` in staging. Supporting
  a second timezone (travel, relocation, multi-user) would require parameterizing
  staging — a deliberate future cost, accepted because the tool is single-user.

**Neutral but worth noting:**
- `*_local` columns are `timestamp without time zone` holding local wall-clock
  time. This is intentional: once normalized, the offset is no longer carried,
  which is what makes "never convert again downstream" enforceable.

## References

- `transform/models/staging/stg_quantities.sql` — the canonical conversion.
- CLAUDE.md → "Timezones normalized at staging".
- `docs/reference/data-dictionary.md` → all `date`/`timestamp` columns are local.
