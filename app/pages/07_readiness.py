"""Readiness Quadrant — load × recovery scatter.

Each day is a point: x = today's training load (TRIMP), y = today's HRV.
Median lines split the plot into four quadrants:

  • Top-right: trained hard while recovered (ideal)
  • Bottom-right: trained hard while strained (injury risk)
  • Top-left: rested while recovered (left on the table)
  • Bottom-left: rested while strained (smart deload)

Color encodes recency (older = faded). The bottom-right quadrant filling up
is the strongest single signal that you're consistently pushing through
fatigue — the kind of pattern that's invisible in line charts.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.lib.queries import recovery_state, workout_zones

st.title("Readiness Quadrant")
st.caption(
    "Daily training load (TRIMP) × HRV. Quadrants split on the in-window "
    "medians. The bottom-right corner is where injury risk concentrates."
)

rec_df = recovery_state()
zones_df = workout_zones()

if rec_df.empty:
    st.info("No recovery data yet.")
    st.stop()

# -------------------------------------------------------------------- controls
window_days = st.slider("Lookback window (days)", 30, 365, 90, step=15)
cutoff = rec_df["day"].max() - pd.Timedelta(days=window_days - 1)

df = rec_df[rec_df["day"] >= cutoff].copy()

# Need both axes — drop days missing either.
df = df.dropna(subset=["training_load_today", "hrv_ms"])

if df.empty:
    st.info("No days in the window have both training load and HRV recorded.")
    st.stop()

# --------------------------------------------- attach the longest workout/day
# Per-day workout type for the tooltip: pick the longest workout that day
# (ties broken by start time). Days with no workout get "Rest day".
if not zones_df.empty:
    zones_df = zones_df.assign(day=zones_df["day"].dt.normalize())
    per_day_wo = (
        zones_df.sort_values(["day", "duration_sec"], ascending=[True, False])
        .groupby("day", as_index=False)
        .agg(
            activity_type=("activity_type", "first"),
            workout_min=("duration_sec", lambda s: round(s.sum() / 60, 1)),
        )
    )
    df = df.merge(per_day_wo, on="day", how="left")
else:
    df["activity_type"] = None
    df["workout_min"] = 0.0

df["activity_type"] = df["activity_type"].fillna("Rest day")
df["workout_min"] = df["workout_min"].fillna(0.0)

# ---------------------------------------------------- quadrant median lines
load_median = float(df["training_load_today"].median())
hrv_median = float(df["hrv_ms"].median())

# Build the chart with explicit padded domains so corner labels render fully.
load_min = float(df["training_load_today"].min())
load_max = float(df["training_load_today"].max())
hrv_min = float(df["hrv_ms"].min())
hrv_max = float(df["hrv_ms"].max())
load_pad = max((load_max - load_min) * 0.1, 1)
hrv_pad = max((hrv_max - hrv_min) * 0.1, 1)

x_domain = [load_min - load_pad, load_max + load_pad]
y_domain = [hrv_min - hrv_pad, hrv_max + hrv_pad]

points = (
    alt.Chart(df)
    .mark_circle(opacity=0.7, stroke="#1e293b", strokeWidth=0.5)
    .encode(
        x=alt.X(
            "training_load_today:Q",
            title="Training load today (TRIMP)",
            scale=alt.Scale(domain=x_domain),
        ),
        y=alt.Y(
            "hrv_ms:Q",
            title="HRV SDNN (ms)",
            scale=alt.Scale(domain=y_domain),
        ),
        color=alt.Color(
            "day:T",
            scale=alt.Scale(scheme="blues"),
            legend=alt.Legend(title="Date", orient="bottom"),
        ),
        size=alt.Size(
            "workout_min:Q",
            scale=alt.Scale(range=[40, 360]),
            legend=alt.Legend(title="Workout min", orient="bottom"),
        ),
        tooltip=[
            alt.Tooltip("day:T", title="Date", format="%a %b %d, %Y"),
            alt.Tooltip("activity_type:N", title="Workout"),
            alt.Tooltip("training_load_today:Q", title="TRIMP", format=".0f"),
            alt.Tooltip("workout_min:Q", title="Minutes", format=".0f"),
            alt.Tooltip("rhr_bpm:Q", title="RHR", format=".0f"),
            alt.Tooltip("hrv_ms:Q", title="HRV", format=".1f"),
            alt.Tooltip("acwr:Q", title="ACWR", format=".2f"),
            alt.Tooltip("recovery_signal:N", title="Signal"),
        ],
    )
)

vline = (
    alt.Chart(pd.DataFrame({"x": [load_median]}))
    .mark_rule(strokeDash=[4, 4], color="#94a3b8")
    .encode(x="x:Q")
)
hline = (
    alt.Chart(pd.DataFrame({"y": [hrv_median]}))
    .mark_rule(strokeDash=[4, 4], color="#94a3b8")
    .encode(y="y:Q")
)

# Quadrant labels — corner-anchored text. Coords are derived so labels
# move with the data domain rather than colliding with points. Split into
# two layers because Altair's mark_text takes `align` as a mark property,
# not a field-driven encoding.
right_labels = pd.DataFrame(
    [
        {"x": x_domain[1], "y": y_domain[1], "label": "Trained hard, recovered ✅"},
        {"x": x_domain[1], "y": y_domain[0], "label": "Trained hard, strained ⚠️"},
    ]
)
left_labels = pd.DataFrame(
    [
        {"x": x_domain[0], "y": y_domain[1], "label": "Rested, recovered"},
        {"x": x_domain[0], "y": y_domain[0], "label": "Rested, strained (deload)"},
    ]
)
label_kwargs = dict(fontSize=11, fontStyle="italic", color="#64748b", dy=-4)
right_layer = (
    alt.Chart(right_labels)
    .mark_text(align="right", dx=-4, **label_kwargs)
    .encode(x="x:Q", y="y:Q", text="label:N")
)
left_layer = (
    alt.Chart(left_labels)
    .mark_text(align="left", dx=4, **label_kwargs)
    .encode(x="x:Q", y="y:Q", text="label:N")
)

st.altair_chart(
    (vline + hline + points + right_layer + left_layer).properties(height=480),
    use_container_width=True,
)

# ---------------------------------------------------------- quadrant counts
hard = df["training_load_today"] >= load_median
recovered = df["hrv_ms"] >= hrv_median
df["quadrant"] = (
    np.where(hard, "Hard", "Rested") + " + " + np.where(recovered, "recovered", "strained")
)

st.subheader(f"Quadrant breakdown — last {window_days} days")
counts = df["quadrant"].value_counts().rename_axis("Quadrant").reset_index(name="Days")
counts["Share"] = (counts["Days"] / counts["Days"].sum() * 100).round(1).astype(str) + "%"

c1, c2 = st.columns([1, 2])
with c1:
    st.dataframe(counts, hide_index=True, use_container_width=True)
with c2:
    st.caption(
        f"Medians in this window — TRIMP {load_median:.0f}, HRV {hrv_median:.1f} ms. "
        f"A bottom-right cluster (`Hard + strained`) is the warning signal."
    )
