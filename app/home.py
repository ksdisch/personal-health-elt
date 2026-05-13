"""Streamlit landing page for the personal health ELT pipeline."""

import sys
from pathlib import Path

# Put project root on sys.path so pages can import ingest.* and app.lib.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib.queries import recovery_state, training_load, workout_zones  # noqa: E402

st.set_page_config(page_title="Personal Health", layout="wide")

st.title("Personal Health")
st.caption("Apple Health → Postgres → dbt → Streamlit")

# ----------------------------------------------------------- pipeline at a glance
rec = recovery_state()
load = training_load()
wo = workout_zones()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Days of data", f"{len(rec):,}" if not rec.empty else "0")
c2.metric("Workouts", f"{len(wo):,}" if not wo.empty else "0")
c3.metric(
    "Active range",
    f"{rec['day'].min().strftime('%b %-d')} → {rec['day'].max().strftime('%b %-d')}"
    if not rec.empty
    else "—",
)
latest_signal = rec.iloc[-1]["recovery_signal"] if not rec.empty else None
c4.metric(
    "Latest signal",
    {
        "well_recovered": "🟢 Well recovered",
        "neutral": "🟡 Neutral",
        "strained": "🔴 Strained",
        "insufficient_data": "⚪ Insufficient",
    }.get(latest_signal, "—"),
)

# ---------------------------------------------------------------------- nav hint
st.divider()
st.subheader("Navigate")

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown("**📅 Daily**")
    st.caption("RHR, HRV, VO₂ Max, Weight — tabs per metric with 3 cards + trend.")
with col_b:
    st.markdown("**🧘 Weekly Review**")
    st.caption("Recovery signal + ACWR trajectory. Public-API surface for the skill.")
with col_c:
    st.markdown("**🏋️ Training Load**")
    st.caption("Per-workout zone stack, acute/chronic load, Zone 2 trend.")

# ----------------------------------------------------------------------- stack
st.divider()
st.subheader("Stack")
st.code(
    """Python 3.12 + uv · Postgres 16 (Docker) · Prefect 3.x · dbt-core
pandas · SQLAlchemy · Streamlit · Altair · Ruff · pytest · GitHub Actions""",
    language="text",
)
if not load.empty:
    last_day = load["day"].max().strftime("%Y-%m-%d")
    st.caption(f"Last `dbt build` produced training load through {last_day}.")

# Suppress the unused-import pandas warning — pd is imported for side-effect usage above.
_ = pd
