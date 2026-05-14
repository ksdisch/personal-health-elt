"""Unit tests for the "Ask" page helpers (app/pages/10_ask.py).

DB-free and API-free. The page itself is exercised by
`tests/test_smoke.py` via the auto-glob compile-only smoke; this file
locks in the pure functions:

- `validate_sql`           — the SQL safety gate
- `compile_schema_summary_from_manifest` — the dbt-manifest renderer
- `get_anthropic_client`   — env-var-driven optional dependency
- `_add_limit_if_missing`  — LIMIT injection helper

The Anthropic client is monkey-patched; nothing here makes a real API
call. Postgres is never touched. CI-safe.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from app.lib.queries import (
    MART_SCHEMA,
    _add_limit_if_missing,
    compile_schema_summary_from_manifest,
    get_anthropic_client,
    validate_sql,
)

# ---------------------------------------------------------------------------
# validate_sql
# ---------------------------------------------------------------------------


class TestValidateSqlHappyPath:
    """Queries that SHOULD pass."""

    def test_simple_select(self) -> None:
        r = validate_sql("SELECT day, hrv_ms FROM analytics_marts.mart_daily_hrv ORDER BY day")
        assert r.ok, r.error

    def test_with_cte(self) -> None:
        r = validate_sql(
            "WITH base AS (SELECT * FROM analytics_marts.mart_recovery_state) "
            "SELECT recovery_signal, COUNT(*) FROM base GROUP BY recovery_signal"
        )
        assert r.ok, r.error

    def test_alias_qualified_columns_do_not_trip_schema_check(self) -> None:
        """Column refs like `m.hrv_ms` should not be mistaken for table refs."""
        r = validate_sql(
            "SELECT m.day, m.hrv_ms FROM analytics_marts.mart_daily_hrv m WHERE m.hrv_ms > 50"
        )
        assert r.ok, r.error

    def test_inner_join(self) -> None:
        r = validate_sql(
            "SELECT s.day, s.hrv_ms, c.temp_max_c "
            "FROM analytics_marts.mart_daily_signals s "
            "JOIN analytics_marts.mart_daily_context c ON s.day = c.day"
        )
        assert r.ok, r.error

    def test_aggregation_with_date_trunc(self) -> None:
        r = validate_sql(
            "SELECT date_trunc('week', day) AS week, AVG(hrv_ms) "
            "FROM analytics_marts.mart_daily_hrv GROUP BY 1 ORDER BY 1"
        )
        assert r.ok, r.error


class TestValidateSqlRejectsForbidden:
    """Queries that MUST be rejected — these are the security-critical paths."""

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE analytics_marts.mart_daily_hrv",
            "TRUNCATE analytics_marts.mart_daily_hrv",
            "ALTER TABLE analytics_marts.mart_daily_hrv ADD COLUMN x int",
            "CREATE TABLE foo (x int)",
        ],
    )
    def test_ddl_blocked(self, sql: str) -> None:
        r = validate_sql(sql)
        assert not r.ok

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO analytics_marts.mart_daily_hrv VALUES (1)",
            "UPDATE analytics_marts.mart_daily_hrv SET hrv_ms = 0",
            "DELETE FROM analytics_marts.mart_daily_hrv",
        ],
    )
    def test_write_dml_blocked(self, sql: str) -> None:
        r = validate_sql(sql)
        assert not r.ok

    def test_multiple_statements_blocked(self) -> None:
        """Classic injection — second statement after a `;`."""
        r = validate_sql("SELECT day FROM analytics_marts.mart_daily_hrv; DROP TABLE foo")
        assert not r.ok
        assert "1 statement" in r.error

    def test_raw_schema_blocked(self) -> None:
        r = validate_sql("SELECT day FROM raw.quantities")
        assert not r.ok
        assert MART_SCHEMA in r.error

    def test_staging_schema_blocked(self) -> None:
        r = validate_sql("SELECT * FROM analytics_staging.stg_categories")
        assert not r.ok
        assert MART_SCHEMA in r.error

    def test_intermediate_schema_blocked(self) -> None:
        r = validate_sql("SELECT * FROM analytics_intermediate.int_sleep_periods")
        assert not r.ok

    def test_information_schema_blocked(self) -> None:
        r = validate_sql("SELECT * FROM information_schema.tables")
        assert not r.ok

    def test_pg_catalog_blocked(self) -> None:
        r = validate_sql("SELECT rolname FROM pg_catalog.pg_roles")
        assert not r.ok

    def test_empty_blocked(self) -> None:
        r = validate_sql("")
        assert not r.ok
        assert "empty" in r.error.lower()

    def test_whitespace_only_blocked(self) -> None:
        r = validate_sql("   \n\t  ")
        assert not r.ok

    def test_no_qualified_reference_blocked(self) -> None:
        """`SELECT 1` would otherwise be valid Postgres but tells us
        nothing — and could be used to probe context. Require at least
        one `analytics_marts.*` reference."""
        r = validate_sql("SELECT 1")
        assert not r.ok
        assert "qualified table reference" in r.error


# ---------------------------------------------------------------------------
# compile_schema_summary_from_manifest
# ---------------------------------------------------------------------------


def _build_manifest(*models) -> dict:
    """Tiny manifest constructor — only the fields the compiler reads."""
    return {"nodes": {f"model.{m['name']}": m for m in models}}


class TestCompileSchemaSummary:
    """The compiler is a pure dict → str transform — these tests don't
    need a real dbt project."""

    def test_returns_non_empty_for_marts(self) -> None:
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_daily_hrv",
                "description": "Daily HRV SDNN.",
                "columns": {"day": {"description": "Calendar date."}},
            }
        )
        out = compile_schema_summary_from_manifest(manifest)
        assert "mart_daily_hrv" in out
        assert "Daily HRV SDNN." in out
        assert "Calendar date." in out

    def test_skips_non_mart_schemas(self) -> None:
        """Staging and intermediate models live in the manifest but must
        NOT appear in the prompt — otherwise the model might try to
        SELECT from them and trip the SQL guard."""
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": "analytics_staging",
                "name": "stg_quantities",
                "description": "Staging.",
                "columns": {},
            },
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_daily_hrv",
                "description": "Daily HRV.",
                "columns": {},
            },
        )
        out = compile_schema_summary_from_manifest(manifest)
        assert "mart_daily_hrv" in out
        assert "stg_quantities" not in out

    def test_skips_non_model_nodes(self) -> None:
        """Tests, sources, exposures also live in `nodes` (and in `sources`,
        `exposures` keys) — they should not appear in the summary."""
        manifest = {
            "nodes": {
                "test.foo": {
                    "resource_type": "test",
                    "schema": MART_SCHEMA,
                    "name": "test_not_null_day",
                    "description": "",
                    "columns": {},
                },
                "model.foo": {
                    "resource_type": "model",
                    "schema": MART_SCHEMA,
                    "name": "mart_daily_hrv",
                    "description": "HRV.",
                    "columns": {},
                },
            }
        }
        out = compile_schema_summary_from_manifest(manifest)
        assert "mart_daily_hrv" in out
        assert "test_not_null_day" not in out

    def test_sort_order_is_deterministic(self) -> None:
        """Identical manifest must produce identical output bytes —
        otherwise prompt caching is broken."""
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_zebra",
                "description": "Z.",
                "columns": {},
            },
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_alpha",
                "description": "A.",
                "columns": {},
            },
        )
        out = compile_schema_summary_from_manifest(manifest)
        assert out.index("mart_alpha") < out.index("mart_zebra")

    def test_columns_sorted_alphabetically(self) -> None:
        """Same caching argument as above — column order must be stable."""
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_x",
                "description": "X.",
                "columns": {
                    "zebra": {"description": "Z col."},
                    "alpha": {"description": "A col."},
                },
            }
        )
        out = compile_schema_summary_from_manifest(manifest)
        assert out.index("alpha") < out.index("zebra")

    def test_empty_manifest_returns_placeholder(self) -> None:
        out = compile_schema_summary_from_manifest({"nodes": {}})
        assert "no marts" in out.lower()

    def test_handles_missing_description(self) -> None:
        """Don't crash when a mart is missing fields."""
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_bare",
                "description": None,
                "columns": None,
            }
        )
        out = compile_schema_summary_from_manifest(manifest)
        assert "mart_bare" in out

    def test_handles_column_without_description(self) -> None:
        manifest = _build_manifest(
            {
                "resource_type": "model",
                "schema": MART_SCHEMA,
                "name": "mart_x",
                "description": "X.",
                "columns": {"day": {}},  # no description
            }
        )
        out = compile_schema_summary_from_manifest(manifest)
        # Should still list the column, just without a description
        assert "day" in out


# ---------------------------------------------------------------------------
# get_anthropic_client
# ---------------------------------------------------------------------------


class TestGetAnthropicClient:
    """The env-var-driven optional dependency. Same pattern as the
    weather loader — None on missing key, not an exception."""

    def test_returns_none_when_no_api_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert get_anthropic_client() is None

    def test_returns_none_when_api_key_blank(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            assert get_anthropic_client() is None

    def test_returns_client_when_api_key_set(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"}):
            client = get_anthropic_client()
            assert client is not None


# ---------------------------------------------------------------------------
# _add_limit_if_missing
# ---------------------------------------------------------------------------


class TestAddLimitIfMissing:
    def test_wraps_when_no_limit(self) -> None:
        out = _add_limit_if_missing("SELECT day FROM analytics_marts.mart_daily_hrv ORDER BY day")
        assert "LIMIT 10000" in out
        # Inner query is preserved verbatim inside a subquery
        assert "ORDER BY day" in out

    def test_preserves_existing_limit(self) -> None:
        sql = "SELECT day FROM analytics_marts.mart_daily_hrv LIMIT 50"
        assert _add_limit_if_missing(sql) == sql

    def test_preserves_limit_offset(self) -> None:
        sql = "SELECT day FROM analytics_marts.mart_daily_hrv LIMIT 50 OFFSET 10"
        assert _add_limit_if_missing(sql) == sql

    def test_strips_trailing_semicolon(self) -> None:
        out = _add_limit_if_missing("SELECT day FROM analytics_marts.mart_daily_hrv;")
        assert ";" not in out.rstrip()[:-1]  # any ; only at the end of full string

    def test_custom_limit(self) -> None:
        out = _add_limit_if_missing(
            "SELECT day FROM analytics_marts.mart_daily_hrv",
            default_limit=42,
        )
        assert "LIMIT 42" in out

    def test_with_cte_appends_not_wraps(self) -> None:
        """Top-level WITH cannot be wrapped in a subquery — Postgres
        rejects `SELECT * FROM (WITH cte AS …) AS x`. The helper must
        append `LIMIT N` to the final SELECT instead."""
        sql = (
            "WITH base AS (SELECT * FROM analytics_marts.mart_recovery_state) "
            "SELECT recovery_signal, COUNT(*) FROM base GROUP BY recovery_signal"
        )
        out = _add_limit_if_missing(sql)
        # Must NOT be wrapped in `SELECT * FROM (...) AS _limited`
        assert "_limited" not in out
        # Must end with LIMIT N
        assert out.rstrip().endswith("LIMIT 10000")

    def test_with_inside_subquery_still_wraps(self) -> None:
        """A WITH inside a subquery is NOT a top-level WITH and should
        still be wrappable. The leading-WITH check uses `^` anchoring."""
        sql = "SELECT * FROM (WITH cte AS (SELECT 1) SELECT * FROM cte) AS x"
        # This is an artificial example; the validator would reject it
        # for the unqualified table ref. But the helper should not have a
        # false positive on the WITH detection.
        out = _add_limit_if_missing(sql)
        assert "_limited" in out
