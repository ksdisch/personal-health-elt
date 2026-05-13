"""Training Load — rolling load, zones by workout, weekly Zone 2 trend.

Visualizes mart_training_load + mart_workout_zones. Shows what raw
workout data becomes once range-joined to HR samples and bucketed.
"""

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import training_load, workout_zones

st.title("Training Load")
st.caption(
    "Rolling load trajectory from `mart_training_load`; "
    "per-workout zone breakdown from `mart_workout_zones`."
)

load_df = training_load()
zones_df = workout_zones()

if load_df.empty:
    st.info("No training-load data yet.")
    st.stop()

# ----------------------------------------------------------------- top-line
latest = load_df.iloc[-1]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Training load today", f"{latest['training_load']:.0f}")
c2.metric("Acute (7d avg)", f"{latest['acute_load_7d']:.1f}")
c3.metric("Chronic (28d avg)", f"{latest['chronic_load_28d']:.1f}")
c4.metric(
    "ACWR",
    f"{latest['acwr']:.2f}" if pd.notna(latest["acwr"]) else "—",
)

# ------------------------------------------------------------ acute vs chronic
st.subheader("Acute vs. Chronic load")
tall_load = load_df.melt(
    id_vars="day",
    value_vars=["acute_load_7d", "chronic_load_28d"],
    var_name="series",
    value_name="value",
)
tall_load["series"] = tall_load["series"].map(
    {"acute_load_7d": "Acute (7d)", "chronic_load_28d": "Chronic (28d)"}
)

load_chart = (
    alt.Chart(tall_load)
    .mark_line(point=False, strokeWidth=2)
    .encode(
        x=alt.X("day:T", title=None),
        y=alt.Y("value:Q", title="Training load (TRIMP)"),
        color=alt.Color(
            "series:N",
            scale=alt.Scale(range=["#0ea5e9", "#94a3b8"]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        tooltip=[
            alt.Tooltip("day:T"),
            "series",
            alt.Tooltip("value:Q", format=".1f"),
        ],
    )
    .properties(height=300)
)
st.altair_chart(load_chart, use_container_width=True)

# --------------------------------------------------------- Zone 2 7d trend
st.subheader("Zone 2 minutes (rolling 7-day)")
st.caption("Zone 2 = 136–153 bpm (from `seeds/hr_zones.csv`).")
st.line_chart(load_df.set_index("day")[["zone_2_min_7d"]], height=260)

# --------------------------------------------------- per-workout zone stack
st.subheader("Per-workout zone breakdown")

if zones_df.empty:
    st.info("No workouts with HR samples yet.")
else:
    long = zones_df.assign(
        **{
            "Zone 1": zones_df["zone_1_sec"] / 60,
            "Zone 2": zones_df["zone_2_sec"] / 60,
            "Zone 3": zones_df["zone_3_sec"] / 60,
            "Zone 4": zones_df["zone_4_sec"] / 60,
            "Zone 5": zones_df["zone_5_sec"] / 60,
        }
    ).melt(
        id_vars=["start_ts", "activity_type"],
        value_vars=["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"],
        var_name="zone",
        value_name="minutes",
    )
    stack_chart = (
        alt.Chart(long[long["minutes"] > 0])
        .mark_bar()
        .encode(
            x=alt.X("start_ts:T", title=None),
            y=alt.Y("minutes:Q", title="Minutes in zone"),
            color=alt.Color(
                "zone:N",
                scale=alt.Scale(
                    domain=["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"],
                    range=["#94a3b8", "#22c55e", "#eab308", "#f97316", "#ef4444"],
                ),
                legend=alt.Legend(title="HR zone", orient="top"),
            ),
            tooltip=[
                alt.Tooltip("start_ts:T", title="Started"),
                "activity_type",
                "zone:N",
                alt.Tooltip("minutes:Q", format=".1f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(stack_chart, use_container_width=True)

    st.subheader("Activity mix")
    activity = (
        zones_df.groupby("activity_type")
        .agg(
            workouts=("start_ts", "count"),
            total_min=("duration_sec", lambda s: round(s.sum() / 60, 1)),
            avg_hr=("avg_hr_bpm", "mean"),
        )
        .reset_index()
        .sort_values("total_min", ascending=False)
    )
    activity["avg_hr"] = activity["avg_hr"].round(0)
    st.dataframe(
        activity.rename(
            columns={
                "activity_type": "Activity",
                "workouts": "Workouts",
                "total_min": "Total min",
                "avg_hr": "Avg HR (bpm)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
