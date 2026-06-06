# Plan — Natural-language → SQL Query page (`14_query`)

**Backlog item:** [Feature] Natural-language → SQL agent over the marts.
**Branch:** `feat/nl-sql-query-page`.
**Status:** built + verified (this doc tracks the sequenced plan and is kept
for the PR trail).

## Goal

A power-user companion to the conversational Ask page (`10_ask.py`). You type
a SQL-shaped request and get the **literal query** against `analytics_marts.*`,
a result table, and the ability to **refine** or **hand-edit** the SQL. It
demonstrates the LLM-app pattern of treating the database schema as a prompt
and makes the guardrails (read-only, schema-restricted, query-budget-limited)
explicit.

## How it differs from `10_ask.py` (so it isn't a clone)

| | Ask (`10_ask`) | Query (`14_query`) |
|---|---|---|
| Framing | answer-first — narrates the result, hides the SQL | query-first — the SQL is the deliverable |
| SQL surface | tucked in an expander, read-only | side-by-side, **hand-editable**, re-runnable |
| Turns | single-shot per question | **multi-turn refine loop** ("only weekdays") |
| Prompt | schema only | schema **+ few-shot NL→SQL anchors** |
| Output | prose explanation | result table + CSV download + 1-line "what it does" |

## Reuse (no new guardrail code)

The safety + schema infra already exists in `app/lib/queries.py` from the Ask
ship and is reused verbatim:

- `validate_sql` — single SELECT, no DDL/DML, every qualified ref in `analytics_marts.*`.
- `execute_safe_sql` — txn-scoped `statement_timeout` + `LIMIT` injection.
- `compile_schema_summary` — schema feed from `transform/target/manifest.json`.
- `get_anthropic_client` — `None` when `ANTHROPIC_API_KEY` unset (skip path).

Page number: the backlog said `13_query`, but `13_experiments` already exists,
so this lands as `14_query`.

## Sequenced steps

1. **Branch + plan doc.** `feat/nl-sql-query-page`; this file. ✅
2. **Verification substrate.** Reuse the already-built synthetic `health_demo`
   warehouse (18 marts, 120 days, credential-free). ✅
3. **`queries.py` additions** (pure, unit-testable):
   - `NL_SQL_FEWSHOT` — curated NL→SQL anchor pairs (every SQL is
     `validate_sql`-clean).
   - `render_fewshot_block(pairs)` — deterministic pairs → prompt text.
4. **`app/pages/14_query.py`** — query-first page: NL input → Claude `emit_sql`
   tool → side-by-side editable SQL + results, multi-turn refine via Streamlit
   `on_click` callbacks (so regenerated SQL can be pushed into the editor
   widget), query-budget caption, CSV download, API-key skip path.
5. **Tests** (`tests/test_query_page.py`, DB-free): every anchor passes
   `validate_sql` + references the marts schema; `render_fewshot_block` shape /
   determinism / ordering.
6. **Verify.** ruff + format + full pytest + `dbt parse` + smoke; then
   end-to-end execute every anchor + simulated generated queries against
   `health_demo`, and confirm the guard blocks malicious SQL against a live DB.
7. **Commit + PR.** Conventional commits; backlog/ROADMAP updates.

## Verification notes / findings

- **Found a real Postgres bug during end-to-end execution:** `ROUND(double
  precision, int)` does not exist, so `ROUND(AVG(x), 1)` raises
  `UndefinedFunction`. Fixed the anchors to cast (`ROUND(AVG(x)::numeric, 1)`)
  and added the same guidance to the system prompt so the live model avoids it.
  Added `tests/test_query_anchors_db.py` (DB-gated, skips when `health_demo`
  unbuilt) that **executes** every anchor against the warehouse — the pure
  AST-level tests could not have caught this.
- **Known gap:** the live NL→SQL generation needs a real `ANTHROPIC_API_KEY`,
  which is blank in this environment, so that leg is verified by parity with the
  proven `10_ask` SDK integration + the executed-anchor evidence, not by a live
  model call. The page renders its skip path without a key.
