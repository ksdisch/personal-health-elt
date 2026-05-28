"""Unit tests for the row-to-JSON serializer in scripts/push_recovery_state.

Only the pure-function surface (no Firestore, no DB). The push() integration
path is exercised manually via `--dry-run` against a real warehouse.
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

push_recovery_state = importlib.import_module("push_recovery_state")
_json_safe = push_recovery_state._json_safe
serialize_row = push_recovery_state.serialize_row
build_payloads = push_recovery_state.build_payloads


def test_json_safe_passes_through_primitives() -> None:
    assert _json_safe(1) == 1
    assert _json_safe(1.5) == 1.5
    assert _json_safe("well_recovered") == "well_recovered"
    assert _json_safe(True) is True
    assert _json_safe(None) is None


def test_json_safe_converts_nan_and_nat_to_none() -> None:
    assert _json_safe(float("nan")) is None
    assert _json_safe(pd.NaT) is None


def test_json_safe_converts_dates_to_iso() -> None:
    assert _json_safe(date(2026, 5, 28)) == "2026-05-28"
    assert _json_safe(pd.Timestamp("2026-05-28")) == "2026-05-28"


def test_json_safe_converts_decimal_to_float() -> None:
    out = _json_safe(Decimal("1.05"))
    assert isinstance(out, float)
    assert out == 1.05


def test_serialize_row_handles_full_mart_shape() -> None:
    row = pd.Series(
        {
            "day": pd.Timestamp("2026-05-28"),
            "is_today": True,
            "recovery_signal": "well_recovered",
            "rhr_bpm": 58.0,
            "hrv_ms": 68.4,
            "hrv_ms_7d_prior_avg": 66.1,
            "zone_2_min_today": 0.0,
            "zone_2_min_7d": 142.5,
            "strength_sessions_7d": 2,
            "training_load_today": 0.0,
            "acute_load_7d": 110.2,
            "chronic_load_28d": 105.0,
            "acwr": 1.05,
            "days_since_last_workout": 1,
        }
    )
    out = serialize_row(row)
    assert out["day"] == "2026-05-28"
    assert out["recovery_signal"] == "well_recovered"
    assert out["acwr"] == 1.05
    assert out["is_today"] is True
    assert out["strength_sessions_7d"] == 2


def test_serialize_row_drops_nan_to_none() -> None:
    row = pd.Series(
        {
            "day": pd.Timestamp("2026-05-28"),
            "rhr_bpm": float("nan"),
            "hrv_ms": 70.0,
            "acwr": None,
        }
    )
    out = serialize_row(row)
    assert out["rhr_bpm"] is None
    assert out["acwr"] is None
    assert out["hrv_ms"] == 70.0


def test_build_payloads_empty_input_returns_none_latest() -> None:
    latest, history = build_payloads(pd.DataFrame())
    assert latest is None
    assert history["rows"] == []
    assert "updated_at" in history


def test_build_payloads_latest_is_last_row() -> None:
    df = pd.DataFrame(
        [
            {"day": pd.Timestamp("2026-05-27"), "recovery_signal": "neutral", "acwr": 0.9},
            {"day": pd.Timestamp("2026-05-28"), "recovery_signal": "well_recovered", "acwr": 1.05},
        ]
    )
    latest, history = build_payloads(df)
    assert latest is not None
    assert latest["day"] == "2026-05-28"
    assert latest["recovery_signal"] == "well_recovered"
    assert len(history["rows"]) == 2
    assert history["rows"][-1]["day"] == "2026-05-28"


def test_build_payloads_shares_updated_at_across_docs() -> None:
    df = pd.DataFrame([{"day": pd.Timestamp("2026-05-28"), "recovery_signal": "neutral"}])
    latest, history = build_payloads(df)
    assert latest is not None
    assert latest["updated_at"] == history["updated_at"]


def test_push_skips_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPO_FIREBASE_SA_PATH", raising=False)
    monkeypatch.delenv("TEMPO_FIREBASE_USER_UID", raising=False)
    result = push_recovery_state.push(days=14, dry_run=False)
    assert result.skipped is True
    assert result.skip_reason and "missing env" in result.skip_reason
    assert result.rows_fetched == 0
