# ADR-0009: Python causal results re-enter the warehouse via raw → staging → mart

- **Status:** Accepted
- **Date:** 2026-06-05
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0008 (statsmodels for causal inference), ADR-0001 (TZ at staging), `ingest/analysis/causal.py`, `transform/models/staging/stg_experiment_effects.sql`, `transform/models/marts/mart_experiment_effects.sql`

## Context

The causal engine (ADR-0008) computes effect estimates in Python. Those results
must become a queryable mart (`mart_experiment_effects`) consumed by the
`13_experiments` Streamlit page. The project enforces strict dbt layering:
`staging → intermediate → marts`, marts never select from `source()` directly,
and TZ normalisation happens in exactly one layer (staging, ADR-0001). The
question is *how Python-computed results enter that graph* without violating it.

A naive option — have Python write `analytics_marts.mart_experiment_effects`
directly — would create a mart that dbt doesn't own, isn't tested by dbt, and
sits outside lineage. That breaks the layering contract and the "marts are dbt's"
invariant.

## Decision

Python writes only to a **raw source table**, `raw.experiment_effects`, declared
in `sources.yml`. dbt then owns everything downstream:

1. `ingest/analysis/causal.py` upserts effect rows into `raw.experiment_effects`
   (delete-then-insert per experiment so the latest fit wins; the table is
   declared with `freshness: null` because it is optional/computed).
2. `stg_experiment_effects` reads `source('raw','experiment_effects')`, does only
   cleaning + the UTC→America/Chicago stamp conversion (TZ lives in staging).
3. `mart_experiment_effects` joins the `experiments` seed (hypothesis/window) and
   derives the conservative verdict; it carries the grain test + `accepted_values`.

The orchestration order is: `dbt build` (daily marts) → causal step (reads marts,
writes raw) → `dbt build --select stg_experiment_effects+` (rebuild the causal
models on populated raw). This mirrors the existing pattern where
`push_recovery_state` reads marts after the build.

## Alternatives considered

- **Python materialises the mart directly** — rejected: a mart dbt doesn't own,
  outside lineage and dbt tests; violates strict layering.
- **A dbt Python model** — rejected: dbt-postgres has no first-class Python-model
  runtime (that's a Snowflake/BigQuery/Databricks feature); not available here.
- **A single mega-flow that interleaves Python and SQL ad hoc** — rejected: the
  raw→staging→mart boundary keeps the contract legible and testable.

## Consequences

**Positive:**
- Strict layering and the "marts are dbt's" invariant are preserved; the causal
  mart is lineage-tracked and dbt-tested like every other mart.
- The two-pass build (daily marts → causal → causal models) is explicit and
  reproducible; the demo flow and CI both run it.

**Negative:**
- A two-pass `dbt build` for the causal models (small cost; the second pass is
  `--select`-scoped). The dependency "daily marts must exist before the causal
  step" is an ordering constraint the flow encodes rather than dbt's DAG.

**Neutral but worth noting:**
- Any future Python-derived dataset (e.g. an ML model's scores) should follow the
  same pattern: write to a `raw.*` source, let dbt stage + mart it.

## References

- `ingest/analysis/causal.py` (`run()` — delete-then-insert into raw).
- `transform/models/staging/stg_experiment_effects.sql`, `transform/models/marts/mart_experiment_effects.sql`.
- `ingest/flows/make_demo_db.py` — the two-pass build order.
