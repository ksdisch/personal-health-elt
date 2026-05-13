"""Aerobic Efficiency — monthly Zone 2 HR drift + VO₂ Max trend.

Zone 2 work is the most evidence-backed driver of long-term aerobic
capacity, and the progression is invisible in raw HR/pace numbers. As
fitness improves, average HR within Zone 2 drifts toward the lower bound
of the band (you can hold the same effort at a lower heart rate). This
page makes that slow-moving signal legible over months.

The VO₂ Max sub-section overlays a 6-month rolling average to smooth out
Apple's noisy per-workout estimates.

Sources: mart_monthly_aerobic_efficiency (built off int_workout_hr_samples
range-join) + mart_daily_vo2max.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import daily_vo2max, hr_zones, monthly_aerobic_efficiency

# Pull Zone 2 bounds from the seed so the chart stays in sync with the
# canonical hr_zones config (no hardcoded bpm literals).
_zones = hr_zones()
_z2 = _zones.loc[_zones["zone_name"] == "aerobic_base"].iloc[0]
Z2_LOW = int(_z2["hr_low"])
Z2_HIGH = int(_z2["hr_high"])
Z2_MID = (Z2_LOW + Z2_HIGH) / 2

st.title("Aerobic Efficiency")
st.caption(
    f"Monthly avg HR within Zone 2 ({Z2_LOW}–{Z2_HIGH} bpm). Lower is "
    "better — same physiological effort at a lower heart rate signals "
    "an improving aerobic base."
)

ae_df = monthly_aerobic_efficiency()

# ============================================================== Z2 panel
if ae_df.empty:
    st.info(
        "No Zone 2 data yet. The mart aggregates from `int_workout_hr_samples`; "
        f"you need workouts with HR samples that fall in zone 2 ({Z2_LOW}–{Z2_HIGH} bpm)."
    )
else:
    avg_z2_min = float(ae_df["avg_z2_hr"].min())
    avg_z2_max = float(ae_df["avg_z2_hr"].max())
    y_pad = max((avg_z2_max - avg_z2_min) * 0.2, 2)
    y_low = max(Z2_LOW, avg_z2_min - y_pad)
    y_high = min(Z2_HIGH, avg_z2_max + y_pad)

    hr_line = (
        alt.Chart(ae_df)
        .mark_line(point=alt.OverlayMarkDef(size=70), color="#0ea5e9", strokeWidth=2)
        .encode(
            x=alt.X("month:T", title=None, axis=alt.Axis(format="%b %Y")),
            y=alt.Y(
                "avg_z2_hr:Q",
                title="Avg HR within Zone 2 (bpm)",
                scale=alt.Scale(domain=[y_low, y_high]),
            ),
            tooltip=[
                alt.Tooltip("month:T", title="Month", format="%B %Y"),
                alt.Tooltip("avg_z2_hr:Q", title="Avg Z2 HR", format=".1f"),
                alt.Tooltip("z2_minutes:Q", title="Z2 minutes", format=".0f"),
                alt.Tooltip("sample_count:Q", title="HR samples"),
            ],
        )
    )
    midline = (
        alt.Chart(pd.DataFrame({"y": [Z2_MID]}))
        .mark_rule(strokeDash=[6, 4], color="#94a3b8")
        .encode(y="y:Q")
    )
    z2_chart = (hr_line + midline).properties(height=300)

    minutes_chart = (
        alt.Chart(ae_df)
        .mark_bar(color="#22c55e", opacity=0.7)
        .encode(
            x=alt.X("month:T", title=None),
            y=alt.Y("z2_minutes:Q", title="Total Z2 minutes"),
            tooltip=[
                alt.Tooltip("month:T", title="Month", format="%B %Y"),
                alt.Tooltip("z2_minutes:Q", title="Z2 minutes", format=".0f"),
            ],
        )
        .properties(height=180)
    )

    st.subheader("Avg HR within Zone 2 (lower = fitter)")
    st.altair_chart(z2_chart, use_container_width=True)
    st.caption(f"Dashed line at {Z2_MID:.0f} bpm (mid-Zone 2) for visual reference.")

    st.subheader("Zone 2 volume")
    st.altair_chart(minutes_chart, use_container_width=True)

    # ------------------------------------------------------ scoreboard
    if len(ae_df) >= 2:
        first_month = ae_df.iloc[0]
        latest_month = ae_df.iloc[-1]
        hr_delta = latest_month["avg_z2_hr"] - first_month["avg_z2_hr"]
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Latest avg Z2 HR",
            f"{latest_month['avg_z2_hr']:.1f} bpm",
            f"{hr_delta:+.1f} vs. first month",
            delta_color="inverse",  # lower is better
        )
        c2.metric(
            "Latest Z2 minutes",
            f"{latest_month['z2_minutes']:.0f}",
        )
        c3.metric(
            "Months of data",
            f"{len(ae_df)}",
        )

# ================================================================= VO₂ Max
st.markdown("---")
st.subheader("VO₂ Max trend")
st.caption(
    "Apple writes VO₂ Max only after outdoor cardio workouts, so the raw "
    "series is sparse. The 6-month rolling average is the trend that matters."
)

vo2 = daily_vo2max()

if vo2.empty:
    st.info("No VO₂ Max readings yet.")
else:
    vo2 = vo2.sort_values("day").copy()
    # 6-month rolling avg by date (not by sample count) — handles sparse data
    vo2 = vo2.set_index("day")
    vo2["rolling_6mo"] = vo2["vo2max"].rolling("180D", min_periods=3).mean()
    vo2 = vo2.reset_index()

    points = (
        alt.Chart(vo2)
        .mark_circle(opacity=0.4, color="#94a3b8", size=40)
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("vo2max:Q", title="VO₂ Max (mL/kg/min)"),
            tooltip=[
                alt.Tooltip("day:T", title="Date", format="%b %d, %Y"),
                alt.Tooltip("vo2max:Q", title="VO₂ Max", format=".1f"),
            ],
        )
    )
    rolling = (
        alt.Chart(vo2.dropna(subset=["rolling_6mo"]))
        .mark_line(color="#0ea5e9", strokeWidth=3)
        .encode(
            x="day:T",
            y="rolling_6mo:Q",
            tooltip=[
                alt.Tooltip("day:T", format="%b %d, %Y"),
                alt.Tooltip("rolling_6mo:Q", title="6-mo avg", format=".2f"),
            ],
        )
    )
    st.altair_chart((points + rolling).properties(height=280), use_container_width=True)
