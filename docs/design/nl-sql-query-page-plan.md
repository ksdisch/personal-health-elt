# Plan — Natural-language → SQL agent (`14_query` Querysmith page)

Status: in progress · Branch: `claude/autonomous-milestone-skill-z9mio`
Backlog: *[Feature] Natural-language → SQL agent over the marts* · ROADMAP "Next".

## What this is

A power-user companion to the conversational **Ask** page (`10_ask.py`). The
user types a *SQL-shaped* request ("weeks where Zone 2 minutes exceeded 90 and
HRV stayed above 50ms"); Claude emits a single read-only query against
`analytics_marts.*`; the page shows the **literal SQL and the result table
side-by-side**, lets the user **edit the SQL and re-run** it, and supports a
**refine loop** (multi-turn: "now only March", "add the RHR column"). CSV export
for the result.

### Ask vs Query — the deliberate split

| | Ask (`10_ask`) | Query (`14_query`) |
|---|---|---|
| Mental model | conversational Q&A | power-user query builder |
| Output | answer + prose **explanation** | **editable SQL** + result table, no prose |
| SQL surface | hidden in an expander | first-class, editable, re-runnable |
| Iteration | re-ask | **refine loop** + hand-edit |
| Prompt | "answer the question" | few-shot **NL→SQL pairs** |

## Why page `14`, not `13`

The backlog entry predates the Causal-Inference Lab, which shipped
`13_experiments.py`. Slot 13 is taken; the new page is `14_query.py`.

## Guardrails — reuse, don't reinvent

The Ask page already built and unit-tested the entire safety surface in
`app/lib/queries.py`. The Query page reuses it verbatim:

- `validate_sql` — single SELECT, no DDL/DML, every qualified ref in
  `analytics_marts.*`, at least one such ref.
- `execute_safe_sql` — `SET LOCAL statement_timeout='10s'` + `LIMIT 10000`
  injection, inside a transaction.
- `compile_schema_summary` — manifest-derived schema feed (cache-stable).
- `get_anthropic_client` — returns `None` when `ANTHROPIC_API_KEY` is unset →
  page renders an informational skip, never crashes.

Hand-edited SQL goes through the **same** `validate_sql` → `execute_safe_sql`
path — the guard is on the execution boundary, not the LLM, so editing can't
escape it.

## Files in scope

1. `app/lib/queries.py` — add three pure, testable units:
   - `QUERY_FEWSHOT: list[tuple[str, str]]` — NL→SQL few-shot pairs.
   - `QUERY_EXAMPLE_REQUESTS: list[str]` — sidebar click-to-fill requests.
   - `format_fewshot_block(examples) -> str` — deterministic prompt renderer.
2. `app/pages/14_query.py` — the page (Claude orchestration + side-by-side UI +
   refine loop + editable SQL + CSV download).
3. `tests/test_query.py` — DB-free / API-free unit tests:
   - Every `QUERY_FEWSHOT` SQL passes `validate_sql` (invariant: we never teach
     Claude a query our own guard rejects).
   - `format_fewshot_block` renders deterministically and contains each pair.
   - Example requests are non-empty / unique.

No dbt model changes → no `schema.yml` edit, no new exposure (matches the Ask
page, which declares none). The smoke test auto-covers the new page via glob.

## Refine-loop message protocol

Anthropic requires a `tool_use` to be answered by a `tool_result` in the *next*
user turn, and forbids consecutive same-role turns. So we stash the last
`tool_use_id` and, on the next refine, send ONE user message = `[tool_result,
text(refine request)]`. First turn is plain text. Same mechanism closes
`ask_clarification`.

## Verification

- `ruff check` + `ruff format` clean.
- `pytest` green (new `test_query.py` + smoke compiles `14_query.py`).
- **Data path against the populated `health_demo` warehouse**: every
  `QUERY_FEWSHOT` SQL is run through `validate_sql` → `execute_safe_sql` and must
  execute without error (proves the example columns/tables match the real mart
  schemas — catches mart drift).
- Live Claude call: `ANTHROPIC_API_KEY` is not in this env, so the LLM turn is
  verified by simulation (fake tool-use response) exactly as the Ask page
  shipped; the deterministic + data paths are verified for real.
