"""Unit tests for the "Query" page helpers (app/pages/14_query.py).

DB-free and API-free — like test_ask.py. The page itself is compile-checked
by tests/test_smoke.py via the auto-glob. This file locks the new pure units
in app/lib/queries.py:

- QUERY_FEWSHOT          — the NL→SQL few-shot pairs
- QUERY_EXAMPLE_REQUESTS — sidebar click-to-fill prompts
- format_fewshot_block   — the deterministic prompt renderer

The most important invariant: every few-shot SQL must pass the SAME
`validate_sql` guard the page enforces at runtime. We must never teach Claude
a query our own safety gate would reject — that would train it toward blocked
output. (The few-shot SQL is additionally run against the populated warehouse
during manual verification to catch mart-schema drift; that check is DB-bound
so it is not part of this CI-safe suite.)
"""

from __future__ import annotations

from app.lib.queries import (
    QUERY_EXAMPLE_REQUESTS,
    QUERY_FEWSHOT,
    format_fewshot_block,
    validate_sql,
)

# ---------------------------------------------------------------------------
# QUERY_FEWSHOT — the few-shot pairs
# ---------------------------------------------------------------------------


class TestQueryFewshot:
    def test_is_non_empty(self) -> None:
        assert QUERY_FEWSHOT, "few-shot set must not be empty"

    def test_each_is_request_sql_pair(self) -> None:
        for pair in QUERY_FEWSHOT:
            assert len(pair) == 2
            req, sql = pair
            assert isinstance(req, str) and req.strip()
            assert isinstance(sql, str) and sql.strip()

    def test_every_example_sql_passes_the_guard(self) -> None:
        """The load-bearing invariant: each taught SQL must survive the same
        validate_sql gate the page enforces. A rejected example would teach
        Claude toward blocked output."""
        for req, sql in QUERY_FEWSHOT:
            result = validate_sql(sql)
            assert result.ok, f"example for {req!r} fails the guard: {result.error}"

    def test_requests_are_unique(self) -> None:
        requests = [req for req, _ in QUERY_FEWSHOT]
        assert len(requests) == len(set(requests))


# ---------------------------------------------------------------------------
# QUERY_EXAMPLE_REQUESTS — the sidebar prompts
# ---------------------------------------------------------------------------


class TestQueryExampleRequests:
    def test_is_non_empty(self) -> None:
        assert QUERY_EXAMPLE_REQUESTS

    def test_all_non_blank_strings(self) -> None:
        for r in QUERY_EXAMPLE_REQUESTS:
            assert isinstance(r, str) and r.strip()

    def test_unique(self) -> None:
        assert len(QUERY_EXAMPLE_REQUESTS) == len(set(QUERY_EXAMPLE_REQUESTS))


# ---------------------------------------------------------------------------
# format_fewshot_block — the prompt renderer
# ---------------------------------------------------------------------------


class TestFormatFewshotBlock:
    def test_contains_every_request_and_sql(self) -> None:
        out = format_fewshot_block(QUERY_FEWSHOT)
        for req, sql in QUERY_FEWSHOT:
            assert req in out
            # the first line of the SQL should appear verbatim
            assert sql.strip().splitlines()[0] in out

    def test_labels_each_pair(self) -> None:
        out = format_fewshot_block(QUERY_FEWSHOT)
        assert out.count("Request:") == len(QUERY_FEWSHOT)
        assert out.count("SQL:") == len(QUERY_FEWSHOT)

    def test_is_deterministic(self) -> None:
        """Byte-stable output — it sits behind the prompt-cache breakpoint."""
        assert format_fewshot_block(QUERY_FEWSHOT) == format_fewshot_block(QUERY_FEWSHOT)

    def test_empty_input_returns_empty_string(self) -> None:
        assert format_fewshot_block([]) == ""

    def test_strips_sql_whitespace(self) -> None:
        out = format_fewshot_block([("r", "  SELECT 1  ")])
        assert out == "Request: r\nSQL:\nSELECT 1"
