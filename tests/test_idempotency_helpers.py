"""Unit tests for the pure-function helpers in ingest.loaders._idempotency.

The DB-bound helpers (already_loaded, record_file, upsert_rows) are
covered end-to-end by tests/test_idempotency_integration.py. This file
covers the pure transformation, records_with_none_for_nan, which has no
DB dependency and is worth quick targeted tests.
"""

from __future__ import annotations

import math

import pandas as pd

from ingest.loaders._idempotency import records_with_none_for_nan


def test_records_coerces_nan_to_none() -> None:
    """A NaN cell must become Python None, not the string 'NaN'."""
    df = pd.DataFrame({"a": [1, math.nan], "b": ["x", "y"]})
    records = records_with_none_for_nan(df)
    assert records == [
        {"a": 1, "b": "x"},
        {"a": None, "b": "y"},
    ]


def test_records_preserves_real_zero_and_empty_string() -> None:
    """0 and '' are not NaN — they must survive intact."""
    df = pd.DataFrame({"a": [0, ""], "b": [0.0, "x"]})
    records = records_with_none_for_nan(df)
    assert records[0]["a"] == 0
    assert records[0]["b"] == 0.0
    assert records[1]["a"] == ""
    assert records[1]["b"] == "x"


def test_records_empty_dataframe_returns_empty_list() -> None:
    """No rows in -> no records out. No exception on the empty path."""
    df = pd.DataFrame({"a": [], "b": []})
    assert records_with_none_for_nan(df) == []


def test_records_handles_mixed_nan_types() -> None:
    """pd.NA, math.nan, and numpy nan all coerce to None."""
    df = pd.DataFrame(
        {
            "math_nan": [math.nan],
            "pd_na": [pd.NA],
            "real_value": [42],
        }
    )
    [record] = records_with_none_for_nan(df)
    assert record["math_nan"] is None
    assert record["pd_na"] is None
    assert record["real_value"] == 42
