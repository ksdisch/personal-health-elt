"""Ask — conversational chat-with-your-health agent.

Type a question in plain English; Claude writes a read-only SQL query
against the `analytics_marts.*` schema, this page executes it, renders
the table (plus a chart when sensible), and Claude writes a short
grounded explanation.

Why this page exists. Every other page is fixed: someone picked the
question and the chart in advance. This one inverts the relationship —
the user picks the question, the marts answer. It's the killer
demonstration that the data model is good enough for arbitrary
questions, not just the ones we anticipated.

Safety architecture. SQL goes through `validate_sql` (single SELECT,
no DDL/DML other than SELECT, every qualified table must be in
`analytics_marts.*`) and then `execute_safe_sql` (runs inside a
transaction with `SET LOCAL statement_timeout = '10s'`, wraps in
`LIMIT 10000` if no LIMIT is present). Forbidden requests are blocked
before they hit Postgres; even if validation were bypassed, the
timeout bounds compute and the result-set is capped.

Schema feed. The prompt's schema block is generated from
`transform/target/manifest.json` — every mart description and every
column description flows through verbatim. Run `dbt parse` to refresh.

Caching. The system prompt (rules + schema + tool defs) is identical
across questions, so it gets a `cache_control: ephemeral` breakpoint
on the last system block. First question writes the cache (~1.25×),
subsequent questions in a 5-minute window read it (~0.1×).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import (
    MART_SCHEMA,
    compile_schema_summary,
    execute_safe_sql,
    get_anthropic_client,
    validate_sql,
)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_RESPONSE_TOKENS = 1024
EXAMPLE_QUESTIONS = [
    "What was my average HRV by week over the past month?",
    "Show my recovery state distribution — how many days were green vs yellow vs red?",
    "Which workouts had the most time in Zone 2?",
    "How did my sleep duration compare on workout days vs rest days?",
    "Which days had below-normal HRV based on the anomaly bands?",
    "What's my training load trend over the past 30 days?",
]

st.title("Ask")
st.caption(
    "Plain-English questions over the marts. Claude writes a read-only "
    "SQL query (analytics_marts.* only), this page executes it, and "
    "returns the answer with a chart when one fits."
)

# ----------------------------------------------------- API-key skip path
client = get_anthropic_client()
if client is None:
    st.info(
        "**Set `ANTHROPIC_API_KEY` to enable this page.** Get a key at "
        "https://console.anthropic.com/ and add it to your `.env` file. "
        "Until then, the page is informational only."
    )
    st.subheader("Example questions this page could answer")
    for q in EXAMPLE_QUESTIONS:
        st.markdown(f"- {q}")
    st.stop()

# ----------------------------------------------------- example sidebar
with st.sidebar:
    st.subheader("Example questions")
    st.caption("Click any to drop it into the box.")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, key=f"example_{hash(q)}", use_container_width=True):
            st.session_state["pending_question"] = q

# ----------------------------------------------------- schema summary
schema_summary = compile_schema_summary()
if not schema_summary:
    st.error(
        "No dbt manifest found at `transform/target/manifest.json`. "
        "Run `uv run dbt parse --project-dir transform --profiles-dir transform` "
        "and reload."
    )
    st.stop()

# ----------------------------------------------------- system prompt
SYSTEM_RULES = f"""You are a friendly analytics assistant for a personal Apple Health
data warehouse. Your job is to answer the user's question by writing a
single read-only SQL query against the `{MART_SCHEMA}.*` schema, then,
once results are returned, summarising them in plain English.

Hard rules — these are enforced by a SQL validator that will reject
anything else and re-prompt you:
- Exactly one statement.
- SELECT (or WITH … SELECT) only. No INSERT/UPDATE/DELETE/DDL.
- Every qualified table reference MUST start with `{MART_SCHEMA}.`.
- Do NOT reference `raw.*`, `analytics_staging.*`, `analytics_intermediate.*`,
  `public.*`, `information_schema.*`, or `pg_catalog.*`.

SQL style:
- Add an ORDER BY for time-series questions.
- Daily marts join on `day`; workout marts use `day_local`; sleep marts use `night_date`.
- Prefer aggregations to raw row dumps; use date_trunc('week', day) for "by week".
- If a question is genuinely ambiguous (e.g., timeframe unclear),
  use the `ask_clarification` tool instead of guessing.

Tools:
- `run_sql(query, rationale, chart_hint)` for the happy path. Pick
  chart_hint='line' for time series, 'bar' for categorical comparisons,
  'table' if a chart would not help.
- `ask_clarification(question)` only when guessing risks the wrong answer.

After SQL results come back, write a short paragraph (2-4 sentences)
explaining what the data shows. Reference the actual numbers in the
result, not hypotheticals.

=== AVAILABLE SCHEMA ===
{schema_summary}"""

TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "Execute a single read-only SELECT against analytics_marts.* and "
            "return the result. Use this for the happy path — when you can "
            "translate the user's question into one query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The full SQL query. Single SELECT statement.",
                },
                "rationale": {
                    "type": "string",
                    "description": ("One sentence on how this query answers the question."),
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
            "required": ["query", "rationale", "chart_hint"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Ask the user a clarifying question. Use ONLY when the question is "
            "genuinely ambiguous (unclear timeframe, unclear grouping, multiple "
            "valid interpretations). Do not use this as a shortcut around hard "
            "SQL."
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


# ----------------------------------------------------- question input
question = st.text_input(
    "Your question",
    value=st.session_state.pop("pending_question", ""),
    placeholder="e.g. What was my average HRV by week over the past month?",
)
submitted = st.button("Ask", type="primary", disabled=not question.strip())

if not submitted:
    st.stop()


def _render_chart(df: pd.DataFrame, chart_hint: str) -> None:
    """Best-effort chart rendering. Falls back silently if the data
    doesn't fit the hint — the table next to it is the source of truth."""
    if chart_hint == "table" or df.empty:
        return
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return
    x_col = df.columns[0]
    y_col = numeric_cols[-1]  # last numeric — usually the metric of interest
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
                x=alt.X(x_col, sort="-y"),
                y=alt.Y(y_col),
                tooltip=list(df.columns),
            )
        )
    st.altair_chart(chart, use_container_width=True)


# ----------------------------------------------------- Claude call
# System prompt as a single text block with cache_control on it. The
# Anthropic SDK renders order is `tools` → `system` → `messages`, so the
# breakpoint on the last (only) system block caches tools + system
# together. Subsequent questions in the 5-min TTL window pay ~0.1×.
system_blocks = [
    {
        "type": "text",
        "text": SYSTEM_RULES,
        "cache_control": {"type": "ephemeral"},
    }
]
messages: list[dict] = [{"role": "user", "content": question}]

with st.spinner("Asking Claude…"):
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system_blocks,
            tools=TOOLS,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001 — surface to UI
        st.error(f"Claude API call failed: {exc}")
        st.stop()

# ----------------------------------------------------- handle tool use
tool_uses = [b for b in response.content if b.type == "tool_use"]
text_blocks = [b.text for b in response.content if b.type == "text"]

if response.stop_reason != "tool_use" or not tool_uses:
    # Plain text response — Claude didn't pick a tool. Render and exit.
    if text_blocks:
        st.write("\n".join(text_blocks))
    else:
        st.warning("Claude returned no usable response.")
    st.stop()

tool = tool_uses[0]

if tool.name == "ask_clarification":
    st.info(f"**Clarifying question:** {tool.input['question']}")
    st.caption("Re-ask the question with that detail filled in.")
    st.stop()

if tool.name != "run_sql":
    st.error(f"Unexpected tool: {tool.name}")
    st.stop()

sql = tool.input.get("query", "")
rationale = tool.input.get("rationale", "")
chart_hint = tool.input.get("chart_hint", "table")

# ----------------------------------------------------- validate + execute
with st.expander("SQL", expanded=False):
    if rationale:
        st.caption(rationale)
    st.code(sql, language="sql")

validation = validate_sql(sql)
if not validation.ok:
    st.error(f"SQL guard blocked the query: {validation.error}")
    st.caption(
        "This is the safety gate working — Claude's query was rejected before hitting Postgres."
    )
    st.stop()

try:
    result_df = execute_safe_sql(sql)
except Exception as exc:  # noqa: BLE001 — surface to UI
    st.error(f"Query failed: {exc}")
    st.stop()

if result_df.empty:
    st.warning("Query returned 0 rows. Try a different question or widen the timeframe.")
    st.stop()

# ----------------------------------------------------- render
_render_chart(result_df, chart_hint)
st.dataframe(result_df, use_container_width=True, hide_index=True)
st.caption(f"{len(result_df):,} row(s) · chart_hint: {chart_hint}")

# ----------------------------------------------------- explanation
result_preview = result_df.head(50).to_csv(index=False)
messages.append({"role": "assistant", "content": response.content})
messages.append(
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool.id,
                "content": (
                    f"Query returned {len(result_df)} rows. First "
                    f"{min(50, len(result_df))} rows as CSV:\n\n{result_preview}"
                ),
            }
        ],
    }
)

with st.spinner("Summarising…"):
    try:
        followup = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system_blocks,
            tools=TOOLS,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001 — surface to UI
        st.error(f"Summarisation call failed: {exc}")
        st.stop()

summary_text = "\n".join(b.text for b in followup.content if b.type == "text").strip()
if summary_text:
    st.subheader("Explanation")
    st.write(summary_text)

# ----------------------------------------------------- caching footer
total_cache_read = (response.usage.cache_read_input_tokens or 0) + (
    followup.usage.cache_read_input_tokens or 0
)
total_cache_write = (response.usage.cache_creation_input_tokens or 0) + (
    followup.usage.cache_creation_input_tokens or 0
)
total_input = response.usage.input_tokens + followup.usage.input_tokens
total_output = response.usage.output_tokens + followup.usage.output_tokens
st.caption(
    f"Tokens — input: {total_input:,} (uncached) · "
    f"cache write: {total_cache_write:,} · cache read: {total_cache_read:,} · "
    f"output: {total_output:,}"
)
