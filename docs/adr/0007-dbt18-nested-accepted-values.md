# ADR-0007: Use the dbt 1.8+ nested `arguments:` form for `accepted_values` (and similar) tests

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0005 (the contract these tests enforce), `transform/models/marts/schema.yml`

## Context

The `mart_recovery_state` contract (ADR-0005) is only as strong as the test that
enforces it. The `recovery_signal` enum is guarded by an `accepted_values` test,
and similar enum/range guards exist across the project (`source_priority ∈ {1,2,3}`,
sleep-stage labels, forecast metric sets, horizon ranges).

dbt changed the schema-test argument syntax. In dbt **1.8+**, generic test
arguments belong under a nested `arguments:` key. The **old top-level form** —
`accepted_values:` with `values:` as a sibling — does not error under the new
parser; it **silently no-ops**, parsing as a test with no constraint. This is the
worst failure mode for a contract test: it appears present and green while
checking nothing. The project runs dbt 1.11, so this is a live hazard.

## Decision

All generic schema tests use the **dbt 1.8+ nested `arguments:` form**. For
example:

```yaml
- accepted_values:
    arguments:
      values: [well_recovered, neutral, strained, insufficient_data]
```

and for numeric domains, `quote: false` lives under the same `arguments:` block.
The old top-level `values:` form is prohibited. This is documented in CLAUDE.md as
a project gotcha so it isn't reintroduced.

## Alternatives considered

- **Old top-level `values:` form** — rejected: silently no-ops under dbt 1.8+, so
  the contract test would pass while enforcing nothing. Unacceptable for the
  public-API guard.
- **Custom singular tests instead of generic `accepted_values`** — rejected for the
  enum case: more code to maintain and review for what is a standard generic test;
  reserved for genuinely compound constraints (e.g. the compound-unique
  `(night_date, stage_start)` checks already implemented as singular tests).
- **Pin dbt < 1.8 to keep the old syntax** — rejected: forgoes current dbt fixes
  and features to preserve a deprecated form; the right move is to adopt the
  supported syntax, not freeze the toolchain.

## Consequences

**Positive:**
- Contract tests actually run and actually fail on violation — the enforcement
  ADR-0005 depends on is real, not cosmetic.
- Forward-compatible with the dbt version the project already uses (1.11).

**Negative:**
- The nested form is more verbose than the old one-liner.
- The silent-no-op trap is invisible to a casual reviewer who knows only the old
  syntax — hence the explicit CLAUDE.md note and this ADR.

**Neutral but worth noting:**
- A quick audit guard: every `accepted_values`/`relationships` block in
  `schema.yml` should have an `arguments:` child. A block without one is the
  silent-no-op smell.

## References

- `transform/models/marts/schema.yml` — all `accepted_values` use the nested form.
- CLAUDE.md → "`accepted_values` test syntax".
- dbt docs: generic test `arguments` (1.8+).
