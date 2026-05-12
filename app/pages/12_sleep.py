"""Sleep — last night summary, hypnogram, 14-day trend, score breakdown.

Composite score is computed upstream in `mart_sleep_nights` (weights live in
the `sleep_score_weights` seed). This page surfaces last night at a glance,
the stage-by-time hypnogram, a short-window trend, and a per-component
breakdown of what is helping or hurting the score.

Sources: mart_sleep_nights + mart_sleep_stages.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import sleep_nights, sleep_stages

# Stage display ordering / labels / colors. Keep these in sync with the
# `sleep_stage` values emitted by mart_sleep_stages.
STAGE_ORDER = [
    "awake",
    "asleepREM",
    "asleepCore",
    "asleepDeep",
    "asleepUnspecified",
    "inBed",
]
STAGE_LABELS = {
    "awake": "Awake",
    "asleepREM": "REM",
    "asleepCore": "Core",
    "asleepDeep": "Deep",
    "asleepUnspecified": "Unspecified",
    "inBed": "In bed",
}
STAGE_COLORS = [
    "#f87171",  # Awake
    "#a78bfa",  # REM
    "#60a5fa",  # Core
    "#1e40af",  # Deep
    "#94a3b8",  # Unspecified
    "#cbd5e1",  # In bed
]

# Score weights / targets. Mirrors `analytics_seeds.sleep_score_weights` —
# kept here so the per-component breakdown does not need an extra query.
TARGET_EFFICIENCY_PCT = 90.0
TARGET_REM_PCT = 22.0
TARGET_DEEP_PCT = 18.0
WEIGHT_EFFICIENCY = 0.40
WEIGHT_REM = 0.30
WEIGHT_DEEP = 0.30
WEIGHT_FRAGMENTATION = 1.5

st.title("Sleep")
st.caption(
    "Per-night composite score, hypnogram, and 14-day trend. "
    "Source: mart_sleep_nights + mart_sleep_stages."
)

nights_df = sleep_nights()
stages_df = sleep_stages()

if nights_df.empty or stages_df.empty:
    st.info("No sleep data yet — run the ingest flow and dbt build first.")
    st.stop()

# ================================================== Section 1: last night
last = nights_df.iloc[-1]
st.subheader(f"Last night — {last['night_date'].strftime('%a %b %d, %Y')}")

asleep_min = int(last["time_asleep_min"])
hours, minutes = divmod(asleep_min, 60)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Composite score", f"{last['composite_score']:.0f}")
c2.metric("Efficiency", f"{last['sleep_efficiency_pct']:.0f}%")
c3.metric("Time asleep", f"{hours}h {minutes}m")
c4.metric(
    "REM / Deep",
    f"{last['rem_pct_of_sleep']:.0f}% / {last['deep_pct_of_sleep']:.0f}%",
)
c5.metric("Awakenings", f"{int(last['awakening_count'])}")

# ===================================================== Section 2: hypnogram
st.subheader("Hypnogram")
last_stages = stages_df[stages_df["night_date"] == last["night_date"]].copy()

if last_stages.empty:
    st.info("No stage segments recorded for last night.")
else:
    last_stages["stage_label"] = last_stages["sleep_stage"].map(STAGE_LABELS)
    label_order = [STAGE_LABELS[s] for s in STAGE_ORDER]

    hypnogram = (
        alt.Chart(last_stages)
        .mark_rect()
        .encode(
            x=alt.X("stage_start_local:T", title=None),
            x2="stage_end_local:T",
            y=alt.Y("stage_label:N", sort=label_order, title=None),
            color=alt.Color(
                "stage_label:N",
                scale=alt.Scale(domain=label_order, range=STAGE_COLORS),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("stage_label:N", title="Stage"),
                alt.Tooltip("stage_start_local:T", title="Start"),
                alt.Tooltip("stage_end_local:T", title="End"),
                alt.Tooltip("duration_min:Q", title="Minutes", format=".0f"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(hypnogram, use_container_width=True)

# =================================================== Section 3: 14-day trend
st.subheader("14-day trend")
trend_df = nights_df.tail(14).copy()

score_chart = (
    alt.Chart(trend_df)
    .mark_line(point=True, strokeWidth=2)
    .encode(
        x=alt.X("night_date:T", title=None),
        y=alt.Y(
            "composite_score:Q",
            title="Composite score",
            scale=alt.Scale(domain=[0, 100]),
        ),
        tooltip=[
            alt.Tooltip("night_date:T", title="Night", format="%a %b %d"),
            alt.Tooltip("composite_score:Q", title="Score", format=".1f"),
        ],
    )
    .properties(height=240, title="Composite score")
)

eff_chart = (
    alt.Chart(trend_df)
    .mark_line(point=True, strokeWidth=2, color="#10b981")
    .encode(
        x=alt.X("night_date:T", title=None),
        y=alt.Y(
            "sleep_efficiency_pct:Q",
            title="Efficiency (%)",
            scale=alt.Scale(domain=[60, 100]),
        ),
        tooltip=[
            alt.Tooltip("night_date:T", title="Night", format="%a %b %d"),
            alt.Tooltip("sleep_efficiency_pct:Q", title="Efficiency", format=".1f"),
        ],
    )
    .properties(height=240, title="Sleep efficiency")
)

st.altair_chart(score_chart & eff_chart, use_container_width=True)

# ============================================ Section 4: score breakdown
st.subheader("What's hurting last night's score")
st.caption(
    "Each component is scored 0–100 relative to its target, then multiplied "
    "by its weight. The fragmentation penalty subtracts directly."
)

eff_score = min(100.0, 100.0 * last["sleep_efficiency_pct"] / TARGET_EFFICIENCY_PCT)
rem_score = min(100.0, 100.0 * last["rem_pct_of_sleep"] / TARGET_REM_PCT)
deep_score = min(100.0, 100.0 * last["deep_pct_of_sleep"] / TARGET_DEEP_PCT)
frag_penalty = -1.0 * WEIGHT_FRAGMENTATION * float(last["awakening_count"])

components = pd.DataFrame(
    [
        {
            "component": "Efficiency",
            "score": eff_score,
            "weighted_contrib": WEIGHT_EFFICIENCY * eff_score,
        },
        {
            "component": "REM %",
            "score": rem_score,
            "weighted_contrib": WEIGHT_REM * rem_score,
        },
        {
            "component": "Deep %",
            "score": deep_score,
            "weighted_contrib": WEIGHT_DEEP * deep_score,
        },
        {
            "component": "Fragmentation penalty",
            "score": frag_penalty,
            "weighted_contrib": frag_penalty,
        },
    ]
)

contrib_chart = (
    alt.Chart(components)
    .mark_bar()
    .encode(
        x=alt.X("weighted_contrib:Q", title="Contribution to composite score"),
        y=alt.Y("component:N", sort="-x", title=None),
        color=alt.condition(
            "datum.weighted_contrib > 0",
            alt.value("#10b981"),
            alt.value("#f87171"),
        ),
        tooltip=[
            alt.Tooltip("component:N", title="Component"),
            alt.Tooltip("score:Q", title="Component score (0-100)", format=".1f"),
            alt.Tooltip("weighted_contrib:Q", title="Weighted contribution", format=".1f"),
        ],
    )
    .properties(height=200)
)
st.altair_chart(contrib_chart, use_container_width=True)

# ================================================== Section 5: raw data
with st.expander("Last 14 nights — raw data"):
    st.dataframe(trend_df, use_container_width=True, hide_index=True)
