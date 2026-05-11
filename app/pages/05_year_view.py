"""Year View — calendar heatmap of training strain and recovery.

GitHub-contributions style 365-day grid colored by daily TRIMP (strain)
or recovery signal. Toggle the encoded color to flip between
"what I did" (strain) and "how my body felt" (recovery).

Sources: mart_training_load (training_load) + mart_recovery_state
(recovery_signal). A pandas date spine fills rest days as zero-strain
or insufficient-data cells so the grid has no gaps.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import recovery_state, training_load

st.title("Year View")
st.caption(
    "Calendar heatmap of training strain (TRIMP) and recovery signal. "
    "Toggle the color encoding to flip between what you did and how you felt."
)

load_df = training_load()
rec_df = recovery_state()

if load_df.empty and rec_df.empty:
    st.info("No data yet — load HR/HRV/workouts first.")
    st.stop()

# ----------------------------------------------------------------- controls
c1, c2 = st.columns([1, 1])
with c1:
    window = st.radio(
        "Window",
        ["Last 90 days", "Last 180 days", "Last 365 days", "All time"],
        horizontal=True,
        index=2,
    )
with c2:
    mode = st.radio("Color by", ["Strain", "Recovery"], horizontal=True)

# ------------------------------------------------------------- date spine
# Anchor the spine to the union of both marts' day ranges so rest days
# render as zero-strain cells instead of leaving holes in the grid.
day_candidates_min = [
    d for d in [
        load_df["day"].min() if not load_df.empty else None,
        rec_df["day"].min() if not rec_df.empty else None,
    ] if d is not None
]
day_candidates_max = [
    d for d in [
        load_df["day"].max() if not load_df.empty else None,
        rec_df["day"].max() if not rec_df.empty else None,
    ] if d is not None
]
day_min = min(day_candidates_min)
day_max = max(day_candidates_max)

if window != "All time":
    days = int(window.split()[1])
    day_min = max(day_min, day_max - pd.Timedelta(days=days - 1))

spine = pd.DataFrame({"day": pd.date_range(day_min, day_max, freq="D")})

df = (
    spine
    .merge(load_df[["day", "training_load"]], on="day", how="left")
    .merge(rec_df[["day", "recovery_signal"]], on="day", how="left")
)
df["training_load"] = df["training_load"].fillna(0)
df["recovery_signal"] = df["recovery_signal"].fillna("insufficient_data")

# ------------------------------------------------------- calendar grid coords
# Monday-anchored week start gives a stable column key across years.
df["week_start"] = df["day"] - pd.to_timedelta(df["day"].dt.weekday, unit="D")
df["dow"] = df["day"].dt.day_name().str[:3]
DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SIGNAL_LABEL = {
    "well_recovered": "🟢 Well recovered",
    "neutral": "🟡 Neutral",
    "strained": "🔴 Strained",
    "insufficient_data": "⚪ Insufficient data",
}
df["signal_label"] = df["recovery_signal"].map(SIGNAL_LABEL).fillna(df["recovery_signal"])

base = alt.Chart(df).encode(
    x=alt.X(
        "week_start:T",
        title=None,
        axis=alt.Axis(format="%b %Y", labelAngle=0),
    ),
    y=alt.Y("dow:O", sort=DOW_ORDER, title=None),
    tooltip=[
        alt.Tooltip("day:T", title="Date", format="%a %b %d, %Y"),
        alt.Tooltip("training_load:Q", title="TRIMP", format=".0f"),
        alt.Tooltip("signal_label:N", title="Recovery"),
    ],
)

if mode == "Strain":
    chart = base.mark_rect(stroke="white", strokeWidth=1).encode(
        color=alt.Color(
            "training_load:Q",
            scale=alt.Scale(scheme="viridis"),
            legend=alt.Legend(title="TRIMP", orient="bottom"),
        ),
    )
else:
    chart = base.mark_rect(stroke="white", strokeWidth=1).encode(
        color=alt.Color(
            "recovery_signal:N",
            scale=alt.Scale(
                domain=["well_recovered", "neutral", "strained", "insufficient_data"],
                range=["#22c55e", "#eab308", "#ef4444", "#e5e7eb"],
            ),
            legend=alt.Legend(title="Signal", orient="bottom"),
        ),
    )

st.altair_chart(chart.properties(height=240), use_container_width=True)

# --------------------------------------------------------- weekly avg TRIMP
weekly = (
    df.groupby("week_start", as_index=False)["training_load"]
    .mean()
    .rename(columns={"training_load": "avg_trimp"})
)
st.subheader("Weekly average TRIMP")
weekly_chart = (
    alt.Chart(weekly)
    .mark_bar(color="#0ea5e9")
    .encode(
        x=alt.X("week_start:T", title=None),
        y=alt.Y("avg_trimp:Q", title="Avg TRIMP / day"),
        tooltip=[
            alt.Tooltip("week_start:T", title="Week of", format="%b %d, %Y"),
            alt.Tooltip("avg_trimp:Q", title="Avg TRIMP", format=".1f"),
        ],
    )
    .properties(height=140)
)
st.altair_chart(weekly_chart, use_container_width=True)

# ---------------------------------------------------------- summary callout
total_days = len(df)
training_days = int((df["training_load"] > 0).sum())
rest_days = total_days - training_days
strain_total = float(df["training_load"].sum())

col1, col2, col3 = st.columns(3)
col1.metric("Days in view", f"{total_days}")
col2.metric("Training days", f"{training_days}", f"{rest_days} rest")
col3.metric("Cumulative TRIMP", f"{strain_total:,.0f}")
