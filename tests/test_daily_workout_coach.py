"""Pure-function unit tests for scripts/daily_workout_coach.py.

Covers the recommendation policy decision tree (one test per major
branch) and the markdown card renderer's edge cases. No Postgres
required — the SQL helpers are exercised end-to-end manually before
shipping.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# scripts/ is not a Python package, so import via importlib. Register in
# sys.modules BEFORE exec_module — @dataclass on a `from __future__ import
# annotations` module otherwise can't resolve `cls.__module__` and raises
# `AttributeError: 'NoneType' object has no attribute '__dict__'`.
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "daily_workout_coach.py"
_spec = importlib.util.spec_from_file_location("daily_workout_coach", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
dwc = importlib.util.module_from_spec(_spec)
sys.modules["daily_workout_coach"] = dwc
_spec.loader.exec_module(dwc)


# --------------------------------------------------------------------------- fixtures


def _row(**overrides) -> pd.Series:
    """Build a mart_recovery_state-shaped Series with sensible defaults."""
    defaults = {
        "day": pd.Timestamp("2026-04-20"),
        "recovery_signal": "neutral",
        "rhr_bpm": 56.0,
        "hrv_ms": 40.0,
        "hrv_ms_7d_prior_avg": 42.0,
        "zone_2_min_today": 0.0,
        "zone_2_min_7d": 90.0,
        "strength_sessions_7d": 1,
        "training_load_today": 0.0,
        "acute_load_7d": 40.0,
        "chronic_load_28d": 40.0,
        "acwr": 1.0,
        "days_since_last_workout": 1,
    }
    defaults.update(overrides)
    return pd.Series(defaults)


def _history(n: int = 14) -> pd.DataFrame:
    """Plausible 14-day mart_training_load slice. Tests that care about
    transition detection (e.g. ACWR spike) override specific rows after
    construction."""
    base = pd.Timestamp("2026-04-20")
    return pd.DataFrame(
        [
            {
                "day": base - timedelta(days=n - 1 - i),
                "zone_2_min": 0.0 if i % 3 else 45.0,
                "training_load": 0.0 if i % 3 else 90.0,
                "acute_load_7d": 40.0,
                "chronic_load_28d": 40.0,
                "acwr": 1.0,
                "strength_sessions_7d": 1,
                "strength_min_7d": 45.0,
            }
            for i in range(n)
        ]
    )


# --------------------------------------------------------------------------- recommend()


def test_strained_with_acwr_spike_triggers_rest() -> None:
    """ACWR > 1.5 + strained → full rest day (not even an easy walk)."""
    rec = dwc.recommend(
        _row(recovery_signal="strained", acwr=1.7, hrv_ms=28.0, hrv_ms_7d_prior_avg=42.0),
        _history(),
    )
    assert rec.session_type == "Rest day"
    assert rec.target_zone is None
    assert rec.target_min == 0
    assert "rest" in rec.headline.lower()
    # The rationale should cite the actual ACWR number.
    joined = " ".join(rec.rationale)
    assert "1.70" in joined or "1.7" in joined


def test_strained_without_spike_recommends_easy_walk() -> None:
    """Strained from HRV crash (not load spike) → easy Z1 walk, not rest."""
    rec = dwc.recommend(
        _row(
            recovery_signal="strained",
            acwr=0.9,
            hrv_ms=28.0,
            hrv_ms_7d_prior_avg=42.0,
        ),
        _history(),
    )
    assert rec.session_type == "Easy walk (Zone 1)"
    assert rec.target_zone == "Z1"
    assert rec.target_min == 30
    # Should cite the HRV drop in the rationale.
    joined = " ".join(rec.rationale)
    assert "HRV" in joined and "%" in joined


def test_insufficient_data_returns_conservative_z2() -> None:
    rec = dwc.recommend(
        _row(recovery_signal="insufficient_data", hrv_ms=None, acwr=None),
        _history(),
    )
    assert rec.session_type == "Conservative Zone 2"
    assert rec.target_zone == "Z2"
    assert rec.target_min == 30


def test_neutral_with_days_since_zero_recommends_recovery() -> None:
    """Already trained today → easy recovery."""
    rec = dwc.recommend(
        _row(recovery_signal="neutral", days_since_last_workout=0),
        _history(),
    )
    assert rec.session_type == "Easy recovery"
    assert rec.target_zone == "Z1"
    assert rec.target_min == 20


def test_neutral_with_rest_day_recommends_standard_z2() -> None:
    rec = dwc.recommend(
        _row(recovery_signal="neutral", days_since_last_workout=2),
        _history(),
    )
    assert rec.session_type == "Zone 2"
    assert rec.target_zone == "Z2"
    assert rec.target_min == 45


def test_well_recovered_with_acwr_spike_blocks_intensity() -> None:
    """Even with green recovery, ACWR > 1.5 → defensive Z2 only."""
    rec = dwc.recommend(
        _row(recovery_signal="well_recovered", acwr=1.6),
        _history(),
    )
    assert rec.session_type == "Zone 2 (defensive)"
    assert rec.target_min == 30


def test_well_recovered_with_climbing_acwr_holds_steady() -> None:
    """ACWR 1.3–1.5 → no intensity, hold at 45-min Z2."""
    rec = dwc.recommend(
        _row(recovery_signal="well_recovered", acwr=1.4),
        _history(),
    )
    assert rec.session_type == "Zone 2"
    assert rec.target_min == 45


def test_well_recovered_under_trained_adds_volume() -> None:
    """ACWR < 0.8 + green → long Z2 to close volume gap."""
    rec = dwc.recommend(
        _row(recovery_signal="well_recovered", acwr=0.5, zone_2_min_7d=44.0),
        _history(),
    )
    assert rec.session_type == "Zone 2 (build)"
    assert rec.target_min == 75
    # Rationale should reference the volume gap.
    joined = " ".join(rec.rationale).lower()
    assert "0.50" in joined or "0.5" in joined
    assert "180" in joined


def test_well_recovered_sweet_spot_z2_deficit_recommends_60min_z2() -> None:
    """ACWR sweet spot + Z2 < 70% of target → 60 min Z2."""
    rec = dwc.recommend(
        _row(
            recovery_signal="well_recovered",
            acwr=1.0,
            zone_2_min_7d=80.0,  # 44% of 180 — clear deficit
            strength_sessions_7d=2,  # strength target met
        ),
        _history(),
    )
    assert rec.session_type == "Zone 2 base"
    assert rec.target_min == 60


def test_well_recovered_sweet_spot_strength_deficit_recommends_strength() -> None:
    """ACWR sweet spot + Z2 ≥ 70% + strength deficit → strength session."""
    rec = dwc.recommend(
        _row(
            recovery_signal="well_recovered",
            acwr=1.0,
            zone_2_min_7d=150.0,  # 83% of 180 — Z2 essentially on track
            strength_sessions_7d=0,
        ),
        _history(),
    )
    assert rec.session_type == "Strength session"
    assert rec.target_zone is None
    assert rec.target_min == 45


def test_well_recovered_base_met_greenlights_intensity() -> None:
    """ACWR sweet spot + Z2 met + strength met → high intensity OK."""
    rec = dwc.recommend(
        _row(
            recovery_signal="well_recovered",
            acwr=1.0,
            zone_2_min_7d=180.0,
            strength_sessions_7d=2,
        ),
        _history(),
    )
    assert "High-intensity" in rec.session_type
    assert rec.target_zone == "Z3-Z4"


# --------------------------------------------------------------------------- render_card()


def test_render_card_empty_df_says_no_data() -> None:
    out = dwc.render_card(pd.DataFrame(), pd.DataFrame(), today=date(2026, 5, 16))
    assert "## 2026-05-16" in out
    assert "No recovery data available" in out


def test_render_card_includes_h2_session_and_snapshot() -> None:
    row = _row(
        day=pd.Timestamp("2026-04-20"),
        recovery_signal="well_recovered",
        acwr=0.6,
        zone_2_min_7d=44.0,
        rhr_bpm=53.0,
        hrv_ms=44.0,
    )
    recovery = pd.DataFrame([row])
    out = dwc.render_card(recovery, _history())
    # H2 dated on the latest day in the recovery df.
    assert out.startswith("## 2026-04-20 (Mon)")
    # Session line is present.
    assert "🎯 **Session:**" in out
    # Snapshot cites the actual numbers Claude / the skill will surface.
    assert "53" in out  # RHR
    assert "44" in out  # HRV / Z2 — both happen to be 44 in this fixture
    assert "0.60" in out or "0.6" in out  # ACWR
    # Footer attribution is intact.
    assert "mart_recovery_state" in out
    assert "mart_training_load" in out


def test_render_card_shows_only_workout_days_in_load_table() -> None:
    """The 14-day load table should suppress zero-load days for compactness."""
    row = _row(day=pd.Timestamp("2026-04-20"))
    recovery = pd.DataFrame([row])
    history = _history()
    # Force a known pattern: 3 workout days out of 14.
    history["training_load"] = 0.0
    history["zone_2_min"] = 0.0
    history.loc[history.index[0], "training_load"] = 100.0
    history.loc[history.index[5], "training_load"] = 80.0
    history.loc[history.index[10], "zone_2_min"] = 45.0

    out = dwc.render_card(recovery, history)
    # 3 workout rows in the table (data lines start with "| Mon ", "| Tue ", etc).
    # Count rows in the table by counting lines that look like a date row.
    table_rows = [
        ln
        for ln in out.splitlines()
        if ln.startswith("| ") and "TRIMP" not in ln and "---" not in ln
    ]
    assert len(table_rows) == 3


def test_render_card_no_workouts_says_so() -> None:
    """When no workouts in window, render the "no workouts" line instead of an empty table."""
    row = _row(day=pd.Timestamp("2026-04-20"))
    recovery = pd.DataFrame([row])
    empty_history = pd.DataFrame(
        [
            {
                "day": pd.Timestamp("2026-04-20") - timedelta(days=i),
                "zone_2_min": 0.0,
                "training_load": 0.0,
                "acute_load_7d": 0.0,
                "chronic_load_28d": 0.0,
                "acwr": None,
                "strength_sessions_7d": 0,
                "strength_min_7d": 0.0,
            }
            for i in range(14)
        ]
    )
    out = dwc.render_card(recovery, empty_history)
    assert "No workouts logged" in out


# --------------------------------------------------------------------------- _fmt()


@pytest.mark.parametrize(
    "value,spec,expected",
    [
        (53.7, ".1f", "53.7"),
        (53.7, ".0f", "54"),
        (None, ".1f", "—"),
        (float("nan"), ".1f", "—"),
        (0.0, ".0f", "0"),
    ],
)
def test_fmt_handles_nulls_and_formats(value, spec, expected) -> None:
    assert dwc._fmt(value, spec) == expected
