"""Shared SQL helpers for Streamlit pages.

Any query that touches raw HR samples will scan millions of rows — those
functions MUST be wrapped in @st.cache_data at the function boundary. Apply
the decorator here, not inside page files.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import anthropic
import pandas as pd
import sqlparse
import streamlit as st
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.db import get_engine

# Path to the dbt manifest. Regenerate via:
#   uv run dbt parse --project-dir transform --profiles-dir transform
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = _REPO_ROOT / "transform" / "target" / "manifest.json"
MART_SCHEMA = "analytics_marts"

# Mirror of ingest.analysis.causal.METRIC_SOURCES — kept local so the Streamlit
# import path doesn't pull in statsmodels just for this two-entry map.
_EXPERIMENT_METRIC_SOURCE = {
    "rhr_bpm": ("mart_daily_rhr", "resting_heart_rate"),
    "hrv_ms": ("mart_daily_hrv", "hrv_ms"),
}


@st.cache_resource
def _engine() -> Engine:
    """Streamlit-cached wrapper around `ingest.db.get_engine()`.

    `get_engine` is already `@lru_cache`d at module scope, so this
    decorator is technically redundant — kept for idiomatic Streamlit
    semantics (the cached resource shows up in the Streamlit cache
    inspector and survives hot-reload as a single shared instance).
    """
    return get_engine()


def _daily_mart(sql: str) -> pd.DataFrame:
    """Shared read pattern for daily marts (keeps each public fn a one-liner)."""
    return pd.read_sql(sql, _engine(), parse_dates=["day"])


@st.cache_data(ttl=300)
def daily_rhr() -> pd.DataFrame:
    """Daily resting heart rate (bpm), one row per day."""
    return _daily_mart(
        "SELECT day, resting_heart_rate, source_name "
        "FROM analytics_marts.mart_daily_rhr ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_hrv() -> pd.DataFrame:
    """Daily HRV SDNN (ms), averaged across nightly samples."""
    return _daily_mart(
        "SELECT day, hrv_ms, sample_count FROM analytics_marts.mart_daily_hrv ORDER BY day"
    )


@st.cache_data(ttl=300)
def experiment_effects() -> pd.DataFrame:
    """Causal-inference results: one row per (experiment, target metric)."""
    return pd.read_sql(
        "SELECT * FROM analytics_marts.mart_experiment_effects "
        "ORDER BY experiment_name, target_metric",
        _engine(),
        parse_dates=["start_date", "end_date", "cutoff_date"],
    )


@st.cache_data(ttl=300)
def experiment_metric_series(metric: str, start: str, end: str) -> pd.DataFrame:
    """Daily values for one metric over [start, end] — to draw the ITS fit."""
    mart, col = _EXPERIMENT_METRIC_SOURCE[metric]
    sql = text(
        f"SELECT day, {col} AS value FROM analytics_marts.{mart} "
        f"WHERE day >= :a AND day <= :b AND {col} IS NOT NULL ORDER BY day"
    )
    return pd.read_sql(sql, _engine(), params={"a": start, "b": end}, parse_dates=["day"])


@st.cache_data(ttl=300)
def daily_vo2max() -> pd.DataFrame:
    """Daily VO2 Max (mL/(kg·min)). Sparse — only on workout days."""
    return _daily_mart(
        "SELECT day, vo2max, sample_count FROM analytics_marts.mart_daily_vo2max ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_weight() -> pd.DataFrame:
    """Daily weight (kg), last reading of the day wins."""
    return _daily_mart(
        "SELECT day, weight_kg, source_name FROM analytics_marts.mart_daily_weight ORDER BY day"
    )


@st.cache_data(ttl=300)
def recovery_state() -> pd.DataFrame:
    """Public-API mart feeding weekly-health-review."""
    return _daily_mart(
        "SELECT day, is_today, rhr_bpm, hrv_ms, hrv_ms_7d_prior_avg, "
        "zone_2_min_today, zone_2_min_7d, strength_sessions_7d, "
        "training_load_today, acute_load_7d, chronic_load_28d, acwr, "
        "days_since_last_workout, recovery_signal "
        "FROM analytics_marts.mart_recovery_state ORDER BY day"
    )


@st.cache_data(ttl=300)
def training_load() -> pd.DataFrame:
    """Daily training load + rolling windows."""
    return _daily_mart(
        "SELECT day, zone_2_min, zone_2_min_7d, strength_sessions_7d, "
        "strength_min_7d, training_load, acute_load_7d, chronic_load_28d, acwr "
        "FROM analytics_marts.mart_training_load ORDER BY day"
    )


@st.cache_data(ttl=300)
def workout_zones() -> pd.DataFrame:
    """Per-workout zone breakdown (seconds in each zone)."""
    return pd.read_sql(
        "SELECT day_local AS day, activity_type, start_ts_local AS start_ts, "
        "duration_sec, zone_1_sec, zone_2_sec, zone_3_sec, zone_4_sec, "
        "zone_5_sec, hr_sample_count, avg_hr_bpm, max_hr_bpm "
        "FROM analytics_marts.mart_workout_zones ORDER BY start_ts_local",
        _engine(),
        parse_dates=["day", "start_ts"],
    )


@st.cache_data(ttl=300)
def daily_anomaly_bands() -> pd.DataFrame:
    """Tall-format daily metric values with rolling 28d mean, std, z-score.

    Powers the Anomaly Dashboard. Currently covers rhr_bpm and hrv_ms;
    sleep duration joins here once the categories loader is built.
    """
    return _daily_mart(
        "SELECT day, metric, value, rolling_mean, rolling_std, z_score "
        "FROM analytics_marts.mart_daily_anomaly_bands "
        "ORDER BY metric, day"
    )


@st.cache_data(ttl=300)
def hr_zones() -> pd.DataFrame:
    """HR zone boundaries from the `hr_zones` seed.

    Columns: zone_number, zone_name, hr_low, hr_high. Zone names match
    `transform/seeds/hr_zones.csv` (recovery, aerobic_base, tempo,
    threshold, vo2_max). Use this instead of hardcoding zone boundaries.
    """
    return pd.read_sql(
        "SELECT zone_number, zone_name, hr_low, hr_high "
        "FROM analytics_seeds.hr_zones ORDER BY zone_number",
        _engine(),
    )


@st.cache_data(ttl=300)
def monthly_aerobic_efficiency() -> pd.DataFrame:
    """Monthly time-weighted avg HR within Zone 2 + total Z2 minutes."""
    return pd.read_sql(
        "SELECT month, avg_z2_hr, z2_minutes, sample_count "
        "FROM analytics_marts.mart_monthly_aerobic_efficiency "
        "ORDER BY month",
        _engine(),
        parse_dates=["month"],
    )


@st.cache_data(ttl=300)
def daily_signals() -> pd.DataFrame:
    """Wide-format daily signals for correlation analysis."""
    return _daily_mart(
        "SELECT day, rhr_bpm, hrv_ms, trimp, acwr, recovery_signal, "
        "recovery_score, sleep_minutes "
        "FROM analytics_marts.mart_daily_signals ORDER BY day"
    )


@st.cache_data(ttl=300)
def sleep_nights() -> pd.DataFrame:
    """One row per night with composite score, efficiency, stage minutes."""
    return pd.read_sql(
        "SELECT night_date, time_in_bed_min, time_asleep_min, "
        "sleep_efficiency_pct, rem_min, deep_min, core_min, awake_min, "
        "rem_pct_of_sleep, deep_pct_of_sleep, awakening_count, "
        "bedtime_local, wake_time_local, composite_score "
        "FROM analytics_marts.mart_sleep_nights ORDER BY night_date",
        _engine(),
        parse_dates=["night_date", "bedtime_local", "wake_time_local"],
    )


@st.cache_data(ttl=300)
def sleep_stages() -> pd.DataFrame:
    """One row per sleep-stage segment, ordered within each night."""
    return pd.read_sql(
        "SELECT night_date, stage_start_local, stage_end_local, "
        "duration_min, sleep_stage, is_asleep, source_name, "
        "stage_seq_in_night "
        "FROM analytics_marts.mart_sleep_stages "
        "ORDER BY night_date, stage_seq_in_night",
        _engine(),
        parse_dates=["night_date", "stage_start_local", "stage_end_local"],
    )


@st.cache_data(ttl=300)
def sleep_naps() -> pd.DataFrame:
    """One row per nap (non-main sleep period with actual sleep).

    Companion to `sleep_nights()`: the main-sleep mart drops same-day naps,
    so this mart is where they surface. Empty DataFrame when the user has
    no recorded naps. nap_date is the calendar date the nap started on.
    """
    return pd.read_sql(
        "SELECT nap_date, night_date, period_seq, nap_start_local, "
        "nap_end_local, duration_min, time_asleep_min, awakening_count "
        "FROM analytics_marts.mart_sleep_naps "
        "ORDER BY nap_start_local",
        _engine(),
        parse_dates=["nap_date", "night_date", "nap_start_local", "nap_end_local"],
    )


@st.cache_data(ttl=300)
def workout_hrr() -> pd.DataFrame:
    """Per-workout heart-rate recovery (HRR).

    One row per workout. `hrr_*s` columns are NULL when no post-workout
    HR sample fell within tolerance of the target offset — leave them
    NULL on the rendering side rather than imputing.
    """
    return pd.read_sql(
        "SELECT activity_type, day_local, workout_start_local, "
        "workout_end_local, peak_hr_bpm, hrr_30s, hrr_60s, hrr_120s "
        "FROM analytics_marts.mart_workout_hrr "
        "ORDER BY workout_start_local",
        _engine(),
        parse_dates=["day_local", "workout_start_local", "workout_end_local"],
    )


@st.cache_data(ttl=300)
def daily_context() -> pd.DataFrame:
    """Daily external-context mart: weather + calendar schedule load.

    Returns empty DataFrame when neither OPENWEATHER_API_KEY nor
    CALENDAR_ICS_URL is configured — the mart still builds, just with
    zero rows. Page consumers should handle empty-DF as "feature
    unavailable" rather than as an error, and gate the weather vs.
    schedule-load sub-sections independently (one source can be
    configured without the other).
    """
    return _daily_mart(
        "SELECT day, temp_min_c, temp_max_c, temp_afternoon_c, temp_night_c, "
        "humidity_afternoon, cloud_cover_afternoon, precip_total_mm, wind_max_mps, "
        "timed_event_count, timed_event_hours, all_day_event_count, "
        "meeting_span_hours, meeting_density, is_high_meeting_day "
        "FROM analytics_marts.mart_daily_context ORDER BY day"
    )


@st.cache_data(ttl=300)
def forecast_bands() -> pd.DataFrame:
    """Tall-format forecast bands for the recovery signals.

    One row per (metric, day) covering both history and the next 7
    forecast days. Pivot on metric in the page. See `mart_forecast_bands`
    docs for the band-derivation math.
    """
    return pd.read_sql(
        "SELECT metric, day, value, smoothed, forecast, forecast_lower, "
        "forecast_upper, is_forecast, horizon_day_offset "
        "FROM analytics_marts.mart_forecast_bands ORDER BY metric, day",
        _engine(),
        parse_dates=["day"],
    )


@st.cache_data(ttl=300)
def forecast_backtest() -> pd.DataFrame:
    """Walk-forward backtest results — one row per (metric, cutoff, horizon)."""
    return pd.read_sql(
        "SELECT metric, cutoff_day, target_day, horizon_days, forecast, "
        "actual, abs_error "
        "FROM analytics_marts.mart_forecast_backtest "
        "ORDER BY metric, cutoff_day, horizon_days",
        _engine(),
        parse_dates=["cutoff_day", "target_day"],
    )


# ---------------------------------------------------------------------------
# "Ask" page (app/pages/10_ask.py) — Claude-powered NL→SQL helpers.
#
# Three independent units, each unit-testable in isolation:
#   compile_schema_summary  — pure: dict → str, deterministic ordering
#   validate_sql            — pure: str  → (ok, error)
#   execute_safe_sql        — DB-bound: validated SQL → DataFrame
# Plus get_anthropic_client() which returns None when ANTHROPIC_API_KEY is
# unset so the page can render a friendly skip instead of crashing on
# import.
# ---------------------------------------------------------------------------


def get_anthropic_client() -> anthropic.Anthropic | None:
    """Returns a configured Anthropic client, or None if no API key is set.

    Same pattern as the OpenWeather loader: optional dependency, the page
    is expected to detect None and render an info message rather than
    blow up.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()


def compile_schema_summary_from_manifest(manifest: dict[str, Any]) -> str:
    """Render a Claude-readable summary of every analytics_marts.* model.

    Pure function — given the parsed manifest dict, returns a deterministic
    text block sorted by mart name so prompt caching stays valid across
    runs (any byte change after the cache_control breakpoint invalidates
    downstream entries).
    """
    marts = sorted(
        (
            n
            for n in manifest.get("nodes", {}).values()
            if n.get("resource_type") == "model" and n.get("schema") == MART_SCHEMA
        ),
        key=lambda n: n["name"],
    )
    if not marts:
        return "(no marts found in manifest)"

    lines: list[str] = []
    for mart in marts:
        lines.append(f"=== {MART_SCHEMA}.{mart['name']} ===")
        desc = (mart.get("description") or "").strip()
        if desc:
            lines.append(desc)
        cols = mart.get("columns") or {}
        if cols:
            lines.append("Columns:")
            for col_name in sorted(cols):
                col = cols[col_name]
                col_desc = (col.get("description") or "").strip().replace("\n", " ")
                if col_desc:
                    lines.append(f"  - {col_name}: {col_desc}")
                else:
                    lines.append(f"  - {col_name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@st.cache_data(ttl=300)
def _schema_summary_cached(mtime: float) -> str:
    """Streamlit-cache wrapper. `mtime` is part of the cache key so a
    `dbt parse` invalidates this automatically."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    return compile_schema_summary_from_manifest(manifest)


def compile_schema_summary() -> str:
    """Live entry point used by the page. Returns '' when the manifest
    is missing — page should fall back gracefully (run `dbt parse`)."""
    if not MANIFEST_PATH.exists():
        return ""
    return _schema_summary_cached(MANIFEST_PATH.stat().st_mtime)


# SQL safety gate. Three layers:
#   1. sqlparse: exactly one statement, must be SELECT
#   2. token walk: reject any DDL or non-SELECT DML keyword anywhere
#   3. regex on FROM/JOIN: every qualified table reference must be in
#      analytics_marts.*, and there must be at least one such reference
#      (so 'SELECT 1' or 'SELECT current_user' can't slip through to
#      probe for the role context)
#
# Future hardening: pair this with a dedicated read-only Postgres role
# scoped to analytics_marts.* via GRANT. Skipped this round — for a
# single-user local app the AST gate is defensible and the role would
# require docker-compose / init-script churn.

_FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "TRUNCATE",
    "DROP",
    "CREATE",
    "ALTER",
    "GRANT",
    "REVOKE",
    "COPY",
    "CALL",
    "EXECUTE",
    "DO",
    "VACUUM",
    "ANALYZE",
    "REINDEX",
    "CLUSTER",
    "REFRESH",
    "COMMENT",
    "LOCK",
    "LISTEN",
    "NOTIFY",
    "RESET",
    "SET",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
}

_FROM_JOIN_QUALIFIED_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+(?P<schema>\w+)\.(?P<table>\w+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlValidation:
    ok: bool
    error: str = ""


def validate_sql(sql: str) -> SqlValidation:
    """Reject anything that isn't a single SELECT against analytics_marts.*.

    Returns SqlValidation(ok=True) on success, SqlValidation(ok=False,
    error=...) on failure. The error is safe to surface to the UI.
    """
    sql = sql.strip()
    if not sql:
        return SqlValidation(False, "empty SQL")

    statements = [s for s in sqlparse.parse(sql) if str(s).strip().rstrip(";").strip()]
    if len(statements) != 1:
        return SqlValidation(False, f"expected exactly 1 statement, got {len(statements)}")

    stmt = statements[0]
    stmt_type = stmt.get_type()
    if stmt_type != "SELECT":
        return SqlValidation(False, f"only SELECT allowed; got {stmt_type}")

    forbidden = _find_forbidden_keyword(stmt)
    if forbidden:
        return SqlValidation(False, f"forbidden keyword: {forbidden}")

    qualified_refs = list(_FROM_JOIN_QUALIFIED_RE.finditer(sql))
    if not qualified_refs:
        return SqlValidation(False, f"no qualified table reference; expected {MART_SCHEMA}.<mart>")
    for match in qualified_refs:
        schema = match.group("schema").lower()
        if schema != MART_SCHEMA:
            return SqlValidation(
                False, f"table reference outside {MART_SCHEMA}.*: {match.group(0)!r}"
            )

    return SqlValidation(True)


def _find_forbidden_keyword(token: Any) -> str | None:
    """Recursively walk the parse tree and return the first DDL or
    non-SELECT DML keyword found, or None."""
    ttype = token.ttype
    if ttype is not None:
        tt = str(ttype)
        if "DDL" in tt or "DML" in tt:
            kw = str(token.value).upper()
            if kw != "SELECT" and kw in _FORBIDDEN_KEYWORDS:
                return kw
    if hasattr(token, "tokens"):
        for child in token.tokens:
            found = _find_forbidden_keyword(child)
            if found:
                return found
    return None


_TRAILING_LIMIT_RE = re.compile(
    r"\bLIMIT\s+\d+(?:\s+OFFSET\s+\d+)?\s*$",
    re.IGNORECASE,
)


_LEADING_WITH_RE = re.compile(r"^\s*WITH\b", re.IGNORECASE)


def _add_limit_if_missing(sql: str, default_limit: int = 10000) -> str:
    """If the SQL doesn't end with LIMIT N, append one.

    Two paths:
    - Plain SELECT → wrap as `SELECT * FROM (sql) AS _limited LIMIT N`.
    - WITH-prefixed CTE → can't wrap in a subquery (Postgres rejects
      `SELECT * FROM (WITH cte AS …) AS x`), so we append `LIMIT N` to
      the final SELECT instead.

    Either form caps the result-set without depending on the inner SQL's
    own LIMIT (if any). Wrapping preserves an inner ORDER BY for the rows
    that come back.
    """
    stripped = sql.strip().rstrip(";").strip()
    if _TRAILING_LIMIT_RE.search(stripped):
        return stripped
    if _LEADING_WITH_RE.match(stripped):
        return f"{stripped}\nLIMIT {default_limit}"
    return f"SELECT * FROM ({stripped}) AS _limited LIMIT {default_limit}"


def execute_safe_sql(
    sql: str,
    timeout_seconds: int = 10,
    default_limit: int = 10000,
) -> pd.DataFrame:
    """Run a validated SELECT inside a transaction with a statement_timeout.

    Callers MUST first run validate_sql() and only invoke this on the
    success path. Defence-in-depth: even if validation is bypassed, the
    transaction is read-only (no COMMIT of writes outside our control)
    and the timeout bounds compute. The LIMIT injection caps result size.
    """
    safe_sql = _add_limit_if_missing(sql, default_limit=default_limit)
    engine = _engine()
    with engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_seconds)}s'"))
        return pd.read_sql(text(safe_sql), conn)


# ---------------------------------------------------------------------------
# "Query" page (app/pages/14_query.py) — NL→SQL power-user helpers.
#
# The Query page is the power-user sibling of the Ask page. Ask is
# answer-first: it hides the SQL and narrates the result. Query is
# query-first: the literal SQL is the deliverable, shown next to the
# result table, hand-editable, and refinable across turns. It reuses the
# same safety gate (validate_sql / execute_safe_sql) and schema feed
# (compile_schema_summary) — the only new ingredient here is a few-shot
# block of NL→SQL pairs that anchors Claude on this warehouse's idioms.
#
# Two pure, unit-testable units live here so the page module (which can't
# be imported by name — leading digit) stays a thin Streamlit shell:
#   NL_SQL_FEWSHOT      — the anchor pairs (every SQL is validate_sql-clean)
#   render_fewshot_block — pure: pairs → prompt text
# A regression test asserts every example still passes validate_sql, so a
# typo'd schema/keyword in an anchor fails CI rather than teaching Claude
# a query the gate would reject at runtime.
# ---------------------------------------------------------------------------

# Each pair is (natural-language request, canonical SQL). The SQL must be
# a single SELECT against analytics_marts.* — i.e. it must pass
# validate_sql() — because Claude learns the *shape* of a valid query
# from these, and tests/test_query_page.py enforces that invariant.
NL_SQL_FEWSHOT: list[tuple[str, str]] = [
    (
        "Weeks where total Zone 2 minutes exceeded 90 and average HRV stayed above 60 ms",
        """WITH weekly AS (
    SELECT date_trunc('week', t.day) AS week,
           SUM(t.zone_2_min)         AS zone_2_min,
           AVG(h.hrv_ms)             AS avg_hrv_ms
    FROM analytics_marts.mart_training_load t
    JOIN analytics_marts.mart_daily_hrv h ON h.day = t.day
    GROUP BY 1
)
SELECT week,
       ROUND(zone_2_min::numeric)     AS zone_2_min,
       ROUND(avg_hrv_ms::numeric, 1)  AS avg_hrv_ms
FROM weekly
WHERE zone_2_min > 90 AND avg_hrv_ms > 60
ORDER BY week""",
    ),
    (
        "Average resting heart rate by recovery signal, with the day count",
        """SELECT recovery_signal,
       ROUND(AVG(rhr_bpm)::numeric, 1) AS avg_rhr_bpm,
       COUNT(*)                        AS n_days
FROM analytics_marts.mart_recovery_state
GROUP BY recovery_signal
ORDER BY avg_rhr_bpm""",
    ),
    (
        "My 10 longest Zone 2 workouts, with activity type and average heart rate",
        """SELECT day_local,
       activity_type,
       ROUND((zone_2_sec / 60.0)::numeric, 1) AS zone_2_min,
       avg_hr_bpm
FROM analytics_marts.mart_workout_zones
WHERE zone_2_sec > 0
ORDER BY zone_2_sec DESC
LIMIT 10""",
    ),
    (
        "Compare my average HRV and resting HR on high-meeting days versus normal days",
        """SELECT c.is_high_meeting_day,
       ROUND(AVG(s.hrv_ms)::numeric, 1)  AS avg_hrv_ms,
       ROUND(AVG(s.rhr_bpm)::numeric, 1) AS avg_rhr_bpm,
       COUNT(*)                          AS n_days
FROM analytics_marts.mart_daily_signals s
JOIN analytics_marts.mart_daily_context c ON c.day = s.day
GROUP BY c.is_high_meeting_day
ORDER BY c.is_high_meeting_day""",
    ),
]


def render_fewshot_block(pairs: list[tuple[str, str]]) -> str:
    """Render NL→SQL pairs into a deterministic prompt block.

    Pure function: the same `pairs` always yields the same bytes, so the
    block can sit inside the cached system prompt without breaking the
    cache. Ordering is preserved (the pairs are already a curated list).
    """
    chunks: list[str] = []
    for i, (request, sql) in enumerate(pairs, start=1):
        chunks.append(f"Example {i}\nRequest: {request.strip()}\nSQL:\n{sql.strip()}")
    return "\n\n".join(chunks)
