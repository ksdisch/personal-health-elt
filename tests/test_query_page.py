"""Unit tests for the "Query" page helpers (app/pages/14_query.py).

DB-free and API-free. The page module itself is compile-covered by
`tests/test_smoke.py` (it can't be imported by name — leading digit), so
this file pins the two pure units that back it, both living in
`app/lib/queries.py`:

- `NL_SQL_FEWSHOT`     — the curated NL→SQL anchor pairs
- `render_fewshot_block` — pure: pairs → deterministic prompt text

The load-bearing test is `test_every_example_passes_validate_sql`: each
anchor SQL is run through the SAME `validate_sql` gate the page enforces
at runtime. A typo'd schema or a forbidden keyword in an anchor therefore
fails CI here, rather than silently teaching Claude a query the gate would
reject in production.
"""

from __future__ import annotations

from app.lib.queries import (
    MART_SCHEMA,
    NL_SQL_FEWSHOT,
    render_fewshot_block,
    validate_sql,
)

# ---------------------------------------------------------------------------
# NL_SQL_FEWSHOT — the anchor pairs must each be a valid, schema-clean query
# ---------------------------------------------------------------------------


class TestFewshotAnchors:
    def test_is_non_empty_list_of_pairs(self) -> None:
        assert NL_SQL_FEWSHOT, "expected at least one few-shot anchor"
        for pair in NL_SQL_FEWSHOT:
            assert isinstance(pair, tuple) and len(pair) == 2
            nl, sql = pair
            assert isinstance(nl, str) and nl.strip()
            assert isinstance(sql, str) and sql.strip()

    def test_every_example_passes_validate_sql(self) -> None:
        """The whole point of the anchors: they must survive the same gate
        the page applies to model output. If one fails, fix the anchor."""
        for nl, sql in NL_SQL_FEWSHOT:
            result = validate_sql(sql)
            assert result.ok, f"anchor for {nl!r} failed validation: {result.error}"

    def test_every_example_references_marts_schema(self) -> None:
        for nl, sql in NL_SQL_FEWSHOT:
            assert f"{MART_SCHEMA}." in sql, f"anchor for {nl!r} never references {MART_SCHEMA}"

    def test_requests_are_unique(self) -> None:
        requests = [nl for nl, _ in NL_SQL_FEWSHOT]
        assert len(requests) == len(set(requests)), "duplicate few-shot requests"


# ---------------------------------------------------------------------------
# render_fewshot_block — pure dict/list → str transform
# ---------------------------------------------------------------------------


class TestRenderFewshotBlock:
    def test_contains_every_request_and_sql(self) -> None:
        out = render_fewshot_block(NL_SQL_FEWSHOT)
        for nl, sql in NL_SQL_FEWSHOT:
            assert nl.strip() in out
            # first line of the SQL is enough to prove the body made it in
            assert sql.strip().splitlines()[0] in out

    def test_numbers_examples_from_one(self) -> None:
        out = render_fewshot_block(NL_SQL_FEWSHOT)
        assert "Example 1" in out
        assert f"Example {len(NL_SQL_FEWSHOT)}" in out
        # one-past-the-end must not appear
        assert f"Example {len(NL_SQL_FEWSHOT) + 1}" not in out

    def test_is_deterministic(self) -> None:
        """Identical input → identical bytes, so the block can live inside
        the cached system prompt without busting the cache."""
        a = render_fewshot_block(NL_SQL_FEWSHOT)
        b = render_fewshot_block(NL_SQL_FEWSHOT)
        assert a == b

    def test_preserves_order(self) -> None:
        pairs = [("first request", "SELECT 1"), ("second request", "SELECT 2")]
        out = render_fewshot_block(pairs)
        assert out.index("first request") < out.index("second request")

    def test_empty_input_returns_empty_string(self) -> None:
        assert render_fewshot_block([]) == ""

    def test_labels_request_and_sql(self) -> None:
        out = render_fewshot_block([("count the rows", "SELECT count(*) FROM x")])
        assert "Request: count the rows" in out
        assert "SQL:" in out
