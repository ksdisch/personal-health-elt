"""Query — natural-language → SQL power-user console.

You type a SQL-shaped request ("weeks where Zone 2 minutes topped 90 and
HRV stayed above 60 ms") and Claude writes the literal query against the
`analytics_marts.*` schema. This page is the power-user sibling of the
Ask page (`10_ask.py`):

- **Ask is answer-first.** It hides the SQL in an expander and narrates
  the result in prose. The question is the interface; the query is
  plumbing.
- **Query is query-first.** The SQL is the product — shown next to the
  result table, hand-editable, and refinable across turns. You can take
  the generated query, tweak a predicate, and re-run it; or type "only
  weekdays" and let Claude revise it. It demonstrates the LLM-app pattern
  of treating the database schema as a prompt, and shows the guardrails
  (read-only, schema-restricted, query-budget-limited) explicitly.

Safety architecture (shared with Ask). Every query — generated OR
hand-edited — goes through `validate_sql` (single SELECT, no DDL/DML,
every qualified table in `analytics_marts.*`) and then `execute_safe_sql`
(transaction-scoped `SET LOCAL statement_timeout = '10s'`, `LIMIT 10000`
injected when absent). The gate runs on the editor's current text, so
hand-edits are policed exactly like model output.

Schema + few-shot feed. The prompt carries the compact schema compiled
from `transform/target/manifest.json` plus a curated block of NL→SQL
example pairs (`NL_SQL_FEWSHOT`) that anchor Claude on this warehouse's
idioms. Both sit inside one `cache_control: ephemeral` system block, so
refines within a 5-minute window read the cache at ~0.1x.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import (
    MART_SCHEMA,
    NL_SQL_FEWSHOT,
    compile_schema_summary,
    execute_safe_sql,
    get_anthropic_client,
    render_fewshot_block,
    validate_sql,
)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_RESPONSE_TOKENS = 1024
DEFAULT_LIMIT = 10000
TIMEOUT_SECONDS = 10

# Sidebar starter requests — deliberately DIFFERENT from the few-shot
# anchors so the page is shown generalising, not parroting its examples.
EXAMPLE_REQUESTS = [
    "My 7 most strained days, with HRV and ACWR",
    "Average HRV and resting heart rate per week",
    "Which activity type did I spend the most total minutes on?",
    "Days where ACWR climbed above 1.3 — the injury-risk zone",
    "My best heart-rate recovery (hrr_60s) workouts",
]

# The query-first system rules. Built into a single cached system block by
# `_system_blocks()` (schema + few-shot appended at call time).
SYSTEM_RULES = f"""You are a SQL generator for a personal Apple Health data warehouse.
The user types a request in plain English and you translate it into ONE
read-only SQL query against the `{MART_SCHEMA}.*` schema. The query is the
product — write correct, readable SQL a data analyst would be happy to run.

Hard rules — enforced by a validator that rejects anything else and
re-prompts you:
- Exactly one statement. SELECT (or WITH … SELECT) only.
- No INSERT/UPDATE/DELETE or DDL of any kind.
- Every qualified table reference MUST start with `{MART_SCHEMA}.`. Never
  reference raw.*, analytics_staging.*, analytics_intermediate.*, public.*,
  information_schema.*, or pg_catalog.*.

SQL style:
- Daily marts join on `day`; workout marts use `day_local`; sleep marts use `night_date`.
- Use date_trunc('week', day) / date_trunc('month', day) for "by week/month".
- Prefer aggregations and ORDER BY to raw row dumps; add LIMIT for "top N".
- Round noisy averages, but Postgres has no ROUND(double precision, int) —
  cast first: ROUND(AVG(x)::numeric, 1).

Tools:
- `emit_sql(query, explanation, chart_hint)` — the happy path. `explanation`
  is ONE sentence on what the query computes (do NOT narrate the results —
  the result table speaks for itself). chart_hint: 'line' for a time
  series, 'bar' for a categorical comparison, 'table' otherwise.
- `ask_clarification(question)` — ONLY when the request is genuinely
  ambiguous (unclear timeframe or grouping). Don't use it to dodge hard SQL.

When the user asks to refine, modify the previous query to satisfy the new
instruction and emit the FULL revised SQL — never a diff or a fragment."""

TOOLS = [
    {
        "name": "emit_sql",
        "description": (
            "Emit a single read-only SELECT against analytics_marts.* that "
            "answers the user's request. This is the happy path — use it "
            "whenever you can translate the request into one query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The full SQL query. A single SELECT (WITH … SELECT allowed).",
                },
                "explanation": {
                    "type": "string",
                    "description": "One sentence on what the query computes (not the results).",
                },
                "chart_hint": {
                    "type": "string",
                    "enum": ["line", "bar", "table"],
                    "description": (
                        "'line' for a time series, 'bar' for a categorical "
                        "comparison, 'table' for everything else."
                    ),
                },
            },
            "required": ["query", "explanation", "chart_hint"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Ask the user a clarifying question. Use ONLY when the request is "
            "genuinely ambiguous — unclear timeframe, unclear grouping, or "
            "multiple valid interpretations. Not a shortcut around hard SQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The clarifying question to ask the user.",
                },
            },
            "required": ["question"],
        },
    },
]


def _system_blocks() -> list[dict]:
    """Assemble the cached system prompt: rules + few-shot + live schema.

    Rebuilt on each call (string assembly is cheap and `compile_schema_summary`
    is itself Streamlit-cached), so callbacks don't have to capture it from
    an enclosing scope.
    """
    schema = compile_schema_summary()
    fewshot = render_fewshot_block(NL_SQL_FEWSHOT)
    text = (
        f"{SYSTEM_RULES}\n\n"
        f"=== EXAMPLES (natural language → SQL) ===\n{fewshot}\n\n"
        f"=== AVAILABLE SCHEMA ===\n{schema}"
    )
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# --------------------------------------------------------------------- state
ss = st.session_state
_DEFAULTS = {
    "q_messages": [],  # Anthropic conversation history (request → emit_sql turns)
    "q_last_tool_id": None,  # tool_use id of the last turn (for the refine tool_result)
    "q_explanation": "",  # one-liner from the last emit_sql
    "q_chart_hint": "table",
    "q_clarification": "",  # set when Claude asks instead of answering
    "q_error": "",  # surfaced API/handling error
    "q_nl": "",  # the natural-language request behind the current SQL
    "sql_editor": "",  # the editable SQL surface (single source of truth to execute)
}
for _k, _v in _DEFAULTS.items():
    ss.setdefault(_k, _v)


def _apply_response(messages: list[dict], response: object) -> None:
    """Fold a Claude response into session_state. Runs inside a callback,
    so it may freely write the `sql_editor` widget key."""
    tool_uses = [b for b in response.content if b.type == "tool_use"]  # type: ignore[attr-defined]
    if response.stop_reason != "tool_use" or not tool_uses:  # type: ignore[attr-defined]
        text = " ".join(
            b.text
            for b in response.content
            if b.type == "text"  # type: ignore[attr-defined]
        ).strip()
        ss.q_clarification = text or "Claude returned no usable response."
        ss.q_messages = []  # dead-end turn — disable refine
        return

    tool = tool_uses[0]
    if tool.name == "ask_clarification":
        ss.q_clarification = tool.input.get("question", "(no question provided)")
        ss.q_messages = []  # ask the user to re-generate with detail; don't keep this turn
        return

    if tool.name != "emit_sql":
        ss.q_error = f"Unexpected tool: {tool.name}"
        return

    # happy path — record the SQL and persist the turn so refine can build on it
    messages.append({"role": "assistant", "content": response.content})
    ss.q_clarification = ""
    ss["sql_editor"] = tool.input.get("query", "")
    ss.q_explanation = tool.input.get("explanation", "")
    ss.q_chart_hint = tool.input.get("chart_hint", "table")
    ss.q_messages = messages
    ss.q_last_tool_id = tool.id


def _call_and_apply(messages: list[dict]) -> None:
    """Shared turn: call Claude, fold the result into state. Callback-safe."""
    client = get_anthropic_client()
    if client is None:
        ss.q_error = "ANTHROPIC_API_KEY is not set."
        return
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=_system_blocks(),
            tools=TOOLS,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001 — surface to UI
        ss.q_error = f"Claude API call failed: {exc}"
        return
    ss.q_error = ""
    _apply_response(messages, response)


def _do_generate() -> None:
    """Generate callback — fresh conversation from the NL request."""
    request = ss.get("nl_request", "").strip()
    if not request:
        return
    ss.q_nl = request
    _call_and_apply([{"role": "user", "content": request}])


def _do_refine() -> None:
    """Refine callback — append the instruction to the running conversation."""
    instruction = ss.get("refine_box", "").strip()
    if not instruction or not ss.q_messages:
        return
    messages = list(ss.q_messages)
    current_sql = ss.get("sql_editor", "")
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": ss.q_last_tool_id,
                    "content": f"Query recorded. Current SQL in the editor:\n{current_sql}",
                },
                {"type": "text", "text": f"Refine the query: {instruction}"},
            ],
        }
    )
    _call_and_apply(messages)
    ss.refine_box = ""  # clear the box (allowed: we're in a callback)


def _render_chart(df: pd.DataFrame, chart_hint: str) -> None:
    """Best-effort chart. Falls back silently — the table is the source of
    truth, so a bad fit just means no chart, never an error."""
    if chart_hint == "table" or df.empty:
        return
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return
    x_col = df.columns[0]
    y_col = numeric_cols[-1]
    if chart_hint == "line":
        chart = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X(f"{x_col}:T" if pd.api.types.is_datetime64_any_dtype(df[x_col]) else x_col),
                y=alt.Y(y_col, scale=alt.Scale(zero=False)),
                tooltip=list(df.columns),
            )
        )
    else:  # bar
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X(str(x_col), sort="-y"),
                y=alt.Y(y_col),
                tooltip=list(df.columns),
            )
        )
    st.altair_chart(chart, use_container_width=True)


# ---------------------------------------------------------------------- page
st.title("Query")
st.caption(
    "Natural-language → SQL. Type a SQL-shaped request; Claude writes the "
    "query against `analytics_marts.*`; edit it by hand or ask to refine it. "
    "Every query is read-only and schema-restricted."
)

# ----------------------------------------------------- API-key skip path
if get_anthropic_client() is None:
    st.info(
        "**Set `ANTHROPIC_API_KEY` to enable this page.** Get a key at "
        "https://console.anthropic.com/ and add it to your `.env` file. "
        "Until then, here's the kind of SQL this page writes."
    )
    st.subheader("Example: request → SQL")
    nl, sql = NL_SQL_FEWSHOT[0]
    st.markdown(f"**Request:** {nl}")
    st.code(sql, language="sql")
    st.subheader("More requests it can answer")
    for q in EXAMPLE_REQUESTS:
        st.markdown(f"- {q}")
    st.stop()

# ----------------------------------------------------- schema guard
if not compile_schema_summary():
    st.error(
        "No dbt manifest found at `transform/target/manifest.json`. "
        "Run `uv run dbt parse --project-dir transform --profiles-dir transform` "
        "and reload."
    )
    st.stop()

# ----------------------------------------------------- example sidebar
with st.sidebar:
    st.subheader("Starter requests")
    st.caption("Click one to drop it into the box.")
    for q in EXAMPLE_REQUESTS:
        if st.button(q, key=f"ex_{hash(q)}", use_container_width=True):
            ss["nl_request"] = q
            _do_generate()

# ----------------------------------------------------- request input
st.text_input(
    "Describe the query in plain English",
    key="nl_request",
    placeholder="e.g. weeks where Zone 2 minutes topped 90 and HRV stayed above 60 ms",
)
st.button(
    "Generate SQL",
    type="primary",
    on_click=_do_generate,
    disabled=not ss.get("nl_request", "").strip(),
)

if ss.q_error:
    st.error(ss.q_error)

if ss.q_clarification:
    st.info(f"**Clarifying question:** {ss.q_clarification}")
    st.caption("Re-generate with that detail filled in.")

# ----------------------------------------------------- SQL + results
if ss["sql_editor"].strip():
    if ss.q_nl:
        st.caption(f"Request: _{ss.q_nl}_")

    left, right = st.columns([5, 6])

    with left:
        st.markdown("**SQL** — edit and re-run, or refine below")
        st.text_area("SQL", key="sql_editor", height=320, label_visibility="collapsed")
        st.button("Run edited SQL ▸", key="run_sql")
        st.caption(
            f"Read-only · `{MART_SCHEMA}.*` only · statement_timeout "
            f"{TIMEOUT_SECONDS}s · capped at {DEFAULT_LIMIT:,} rows"
        )

    with right:
        st.markdown("**Result**")
        active_sql = ss["sql_editor"].strip()
        validation = validate_sql(active_sql)
        if not validation.ok:
            st.error(f"SQL guard blocked the query: {validation.error}")
            st.caption("The safety gate rejected this before it reached Postgres.")
        else:
            try:
                result_df = execute_safe_sql(
                    active_sql,
                    timeout_seconds=TIMEOUT_SECONDS,
                    default_limit=DEFAULT_LIMIT,
                )
            except Exception as exc:  # noqa: BLE001 — surface to UI
                st.error(f"Query failed: {exc}")
                result_df = None

            if result_df is not None:
                if result_df.empty:
                    st.warning("Query returned 0 rows. Refine it or widen the timeframe.")
                else:
                    _render_chart(result_df, ss.q_chart_hint)
                    st.dataframe(result_df, use_container_width=True, hide_index=True)
                    st.caption(f"{len(result_df):,} row(s) · chart_hint: {ss.q_chart_hint}")
                    st.download_button(
                        "Download CSV",
                        result_df.to_csv(index=False),
                        file_name="query_result.csv",
                        mime="text/csv",
                    )

    if ss.q_explanation:
        st.caption(f"**What this query does:** {ss.q_explanation}")

    # ------------------------------------------------- refine loop
    st.markdown("**Refine**")
    st.text_input(
        "Refine",
        key="refine_box",
        label_visibility="collapsed",
        placeholder="e.g. only weekdays · add a row count · sort descending · last 30 days only",
    )
    st.button("Refine ▸", on_click=_do_refine, disabled=not ss.q_messages)
