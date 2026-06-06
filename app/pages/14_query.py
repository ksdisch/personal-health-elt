"""Query — natural-language → SQL, power-user mode.

State a SQL-shaped request ("weeks where Zone 2 minutes exceeded 90 and
HRV stayed above 50ms"); Claude writes a single read-only query against
`analytics_marts.*`; this page shows the **literal SQL and the result
side-by-side**, lets you **edit the SQL and re-run it**, and supports a
**refine loop** (multi-turn: "now only March", "add the RHR column").

Why this page exists, distinct from Ask. The Ask page (10_ask) is
conversational — it answers a question and explains the result in prose,
hiding the SQL. This page inverts that for the power user: the SQL is the
product. You see it, you can hand-edit it, you can re-run it, and you can
iterate on it in plain English. It demonstrates the "schema-as-prompt"
LLM-app pattern with the guardrails (read-only, schema-restricted,
timeout- and row-bounded) made first-class.

Safety architecture. Both Claude-written and hand-edited SQL flow through
the SAME gate — `validate_sql` (single SELECT, no DDL/DML, every qualified
table in `analytics_marts.*`) then `execute_safe_sql` (transaction with
`SET LOCAL statement_timeout='10s'`, `LIMIT 10000` injection). The guard is
on the execution boundary, so editing the SQL cannot escape it.

Refine-loop message protocol. Anthropic requires a `tool_use` to be answered
by a `tool_result` in the next user turn, and forbids consecutive same-role
turns. So we stash the last `tool_use_id` and, on the next refine, send one
user message = `[tool_result, text(refine request)]`. The first turn is plain
text; the same mechanism closes `ask_clarification`.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import (
    MART_SCHEMA,
    QUERY_EXAMPLE_REQUESTS,
    QUERY_FEWSHOT,
    compile_schema_summary,
    execute_safe_sql,
    format_fewshot_block,
    get_anthropic_client,
    validate_sql,
)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_RESPONSE_TOKENS = 1024

st.title("Query")
st.caption(
    "Power-user mode: describe the query you want, get the literal SQL "
    "(editable + re-runnable) next to the result, and refine it in plain "
    "English. Read-only, `analytics_marts.*` only, 10s timeout."
)

# ----------------------------------------------------- API-key skip path
client = get_anthropic_client()
if client is None:
    st.info(
        "**Set `ANTHROPIC_API_KEY` to enable this page.** Get a key at "
        "https://console.anthropic.com/ and add it to your `.env` file. "
        "Until then, the page is informational only."
    )
    st.subheader("Example requests this page could turn into SQL")
    for r in QUERY_EXAMPLE_REQUESTS:
        st.markdown(f"- {r}")
    st.stop()

# ----------------------------------------------------- schema summary
schema_summary = compile_schema_summary()
if not schema_summary:
    st.error(
        "No dbt manifest found at `transform/target/manifest.json`. "
        "Run `uv run dbt parse --project-dir transform --profiles-dir transform` "
        "and reload."
    )
    st.stop()

# ----------------------------------------------------- session state
ss = st.session_state
ss.setdefault("qs_messages", [])  # the Anthropic conversation (with tool turns)
ss.setdefault("qs_pending_tool_id", None)  # tool_use awaiting a tool_result
ss.setdefault("qs_sql", "")  # current SQL shown in the editor
ss.setdefault("qs_chart_hint", "table")
ss.setdefault("qs_turns", [])  # [(request, note)] transcript for the UI
ss.setdefault("qs_result_df", None)  # last result (DataFrame or None)
ss.setdefault("qs_error", None)  # last execution/guard error (str or None)


def _reset_session() -> None:
    for k in (
        "qs_messages",
        "qs_pending_tool_id",
        "qs_sql",
        "qs_chart_hint",
        "qs_turns",
        "qs_result_df",
        "qs_error",
    ):
        ss.pop(k, None)


# ----------------------------------------------------- system prompt
FEWSHOT_BLOCK = format_fewshot_block(QUERY_FEWSHOT)

SYSTEM_RULES = f"""You are a SQL-writing assistant for a personal Apple Health data
warehouse. The user states a query-shaped request; you translate it into a
single read-only SQL query against the `{MART_SCHEMA}.*` schema. The user is
technical — they want the query and the data, not a prose essay. Do NOT explain
the results unless asked; just write the best query.

Hard rules — enforced by a SQL validator that rejects anything else and
re-prompts you:
- Exactly one statement.
- SELECT (or WITH … SELECT) only. No INSERT/UPDATE/DELETE/DDL.
- Every qualified table reference MUST start with `{MART_SCHEMA}.`.
- Do NOT reference `raw.*`, `analytics_staging.*`, `analytics_intermediate.*`,
  `public.*`, `information_schema.*`, or `pg_catalog.*`.

SQL style:
- Add ORDER BY for time-series and "top N" requests.
- Daily marts join on `day`; workout marts use `day_local`; sleep marts use `night_date`.
- Use date_trunc('week'|'month', day) for "by week"/"by month".
- round(...) numeric aggregates to a sensible precision for readability.
- Cast to ::numeric before round() on double-precision columns (e.g. hrv_ms, acwr).

Refining: when the user follows up ("now only March", "add the RHR column"),
modify your PREVIOUS query rather than starting over, unless they clearly want a
new query.

Tools:
- `write_sql(query, note, chart_hint)` — the happy path. `note` is a SHORT
  one-line label (not a paragraph). chart_hint='line' for time series, 'bar' for
  categorical comparisons, 'table' otherwise.
- `ask_clarification(question)` — ONLY when the request is genuinely ambiguous
  (unclear timeframe/grouping/metric). Not a shortcut around hard SQL.

=== EXAMPLE REQUESTS → SQL ===
{FEWSHOT_BLOCK}

=== AVAILABLE SCHEMA ===
{schema_summary}"""

TOOLS = [
    {
        "name": "write_sql",
        "description": (
            "Emit a single read-only SELECT against analytics_marts.* that "
            "satisfies the user's request. Use this for the happy path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The full SQL query. Single SELECT statement.",
                },
                "note": {
                    "type": "string",
                    "description": "A short one-line label for this query (not a paragraph).",
                },
                "chart_hint": {
                    "type": "string",
                    "enum": ["line", "bar", "table"],
                    "description": (
                        "Visualization preference: 'line' for time series, 'bar' "
                        "for categorical comparison, 'table' for everything else."
                    ),
                },
            },
            "required": ["query", "note", "chart_hint"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Ask the user a clarifying question. Use ONLY when the request is "
            "genuinely ambiguous. Do not use this as a shortcut around hard SQL."
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

system_blocks = [{"type": "text", "text": SYSTEM_RULES, "cache_control": {"type": "ephemeral"}}]


# ----------------------------------------------------- helpers
def _run_and_store(sql: str) -> None:
    """Validate + execute `sql`, storing the result (or error) in session
    state. The single execution path for BOTH Claude-written and hand-edited
    SQL — the guard sits here, so editing can't escape it."""
    sql = sql.strip()
    ss["qs_sql"] = sql
    validation = validate_sql(sql)
    if not validation.ok:
        ss["qs_error"] = f"SQL guard blocked the query: {validation.error}"
        ss["qs_result_df"] = None
        return
    try:
        ss["qs_result_df"] = execute_safe_sql(sql)
        ss["qs_error"] = None
    except Exception as exc:  # noqa: BLE001 — surface to UI
        ss["qs_error"] = f"Query failed: {exc}"
        ss["qs_result_df"] = None


def _ask_claude(request: str) -> object:
    """Append the user turn (closing any pending tool_use with a tool_result),
    call Claude, append the assistant turn, and return the response."""
    content: list[dict] = []
    if ss["qs_pending_tool_id"]:
        content.append(
            {
                "type": "tool_result",
                "tool_use_id": ss["qs_pending_tool_id"],
                "content": "Acknowledged. The user's next instruction follows.",
            }
        )
    content.append({"type": "text", "text": request})
    ss["qs_messages"].append({"role": "user", "content": content})
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_RESPONSE_TOKENS,
        system=system_blocks,
        tools=TOOLS,
        messages=ss["qs_messages"],
    )
    ss["qs_messages"].append({"role": "assistant", "content": response.content})
    return response


def _render_chart(df: pd.DataFrame, chart_hint: str) -> None:
    """Best-effort chart. Falls back silently when the data doesn't fit the
    hint — the table beside it is the source of truth."""
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
            .encode(x=alt.X(x_col, sort="-y"), y=alt.Y(y_col), tooltip=list(df.columns))
        )
    st.altair_chart(chart, use_container_width=True)


# ----------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Example requests")
    st.caption("Click any to drop it into the box.")
    for r in QUERY_EXAMPLE_REQUESTS:
        if st.button(r, key=f"qs_example_{hash(r)}", use_container_width=True):
            ss["qs_pending_request"] = r
    st.divider()
    if st.button("↺ Start over", use_container_width=True):
        _reset_session()
        st.rerun()

# ----------------------------------------------------- request input
is_refine = bool(ss["qs_turns"])
label = "Refine the query" if is_refine else "Describe the query you want"
placeholder = (
    "e.g. now only weeks in March"
    if is_refine
    else "e.g. weeks where Zone 2 minutes exceeded 90 and average HRV stayed above 50ms"
)
request = st.text_input(label, value=ss.pop("qs_pending_request", ""), placeholder=placeholder)
submitted = st.button(
    "Refine" if is_refine else "Write SQL",
    type="primary",
    disabled=not request.strip(),
)

if submitted:
    with st.spinner("Asking Claude to write SQL…"):
        try:
            response = _ask_claude(request)
        except Exception as exc:  # noqa: BLE001 — surface to UI
            st.error(f"Claude API call failed: {exc}")
            st.stop()

    tool_uses = [b for b in response.content if b.type == "tool_use"]
    if not tool_uses:
        text_out = "\n".join(b.text for b in response.content if b.type == "text").strip()
        st.warning(text_out or "Claude returned no SQL. Try rephrasing the request.")
        ss["qs_pending_tool_id"] = None
    else:
        tool = tool_uses[0]
        ss["qs_pending_tool_id"] = tool.id  # must be closed on the next turn
        if tool.name == "ask_clarification":
            st.info(f"**Claude needs a detail:** {tool.input['question']}")
            st.caption("Answer it in the box above and submit again to continue.")
        elif tool.name == "write_sql":
            ss["qs_chart_hint"] = tool.input.get("chart_hint", "table")
            note = tool.input.get("note", "")
            ss["qs_turns"].append((request, note))
            _run_and_store(tool.input.get("query", ""))
        else:
            st.error(f"Unexpected tool: {tool.name}")

# ----------------------------------------------------- side-by-side SQL + result
if ss["qs_sql"]:
    col_sql, col_res = st.columns([0.44, 0.56], gap="large")

    with col_sql:
        st.subheader("SQL")
        edited = st.text_area(
            "Editable SQL",
            value=ss["qs_sql"],
            height=300,
            key="qs_editor",
            label_visibility="collapsed",
        )
        if st.button("▶ Run query", use_container_width=True):
            _run_and_store(edited)
        st.caption("Edit the query and re-run — it goes through the same safety gate.")

    with col_res:
        st.subheader("Result")
        if ss["qs_error"]:
            st.error(ss["qs_error"])
            if "guard blocked" in ss["qs_error"]:
                st.caption(
                    "This is the safety gate working — the query was rejected "
                    "before hitting Postgres."
                )
        elif ss["qs_result_df"] is None:
            st.caption("Run the query to see results.")
        else:
            df = ss["qs_result_df"]
            if df.empty:
                st.warning("Query returned 0 rows. Widen the filter or timeframe.")
            else:
                _render_chart(df, ss["qs_chart_hint"])
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption(f"{len(df):,} row(s) · chart_hint: {ss['qs_chart_hint']}")
                st.download_button(
                    "⬇ Download CSV",
                    df.to_csv(index=False),
                    file_name="query_result.csv",
                    mime="text/csv",
                )

# ----------------------------------------------------- refinement transcript
if ss["qs_turns"]:
    with st.expander(f"Refinement history ({len(ss['qs_turns'])})", expanded=False):
        for i, (req, note) in enumerate(ss["qs_turns"], start=1):
            st.markdown(f"**{i}.** {req}")
            if note:
                st.caption(note)
