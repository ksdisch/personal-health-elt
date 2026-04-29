"""Weekly Review — visualizes mart_recovery_state (the public API).

This page is the consumer's-eye view of what the weekly-health-review
Claude skill will see: a recovery signal, the rolling ACWR and HRV
trajectory, and the last two weeks of daily rows.
"""
import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import recovery_state

st.title("Weekly Review")
st.caption(
    "Recovery signal from `mart_recovery_state` — "
    "the public API the weekly-health-review skill reads."
)

df = recovery_state()

if df.empty:
    st.info("No recovery data yet. Load HR, HRV, and workout CSVs first.")
    st.stop()

# ----------------------------------------------------------------------- headline
latest = df.iloc[-1]
signal = latest["recovery_signal"]
signal_label = {
    "well_recovered": "🟢 Well recovered",
    "neutral": "🟡 Neutral",
    "strained": "🔴 Strained",
    "insufficient_data": "⚪ Insufficient data",
}.get(signal, signal)

st.header(signal_label)
st.caption(f"as of {latest['day'].strftime('%A, %B %-d, %Y')}")


def _fmt(val, spec: str, unit: str = "") -> str:
    return f"{val:{spec}}{unit}" if pd.notna(val) else "—"


c1, c2, c3, c4 = st.columns(4)
c1.metric("RHR", _fmt(latest["rhr_bpm"], ".0f", " bpm"))
c2.metric("HRV", _fmt(latest["hrv_ms"], ".1f", " ms"))
c3.metric("ACWR", _fmt(latest["acwr"], ".2f"))
c4.metric("Zone 2 (7d)", _fmt(latest["zone_2_min_7d"], ".0f", " min"))

# ---------------------------------------------------------------------------- ACWR
st.subheader("Acute : Chronic Workload Ratio")
st.caption("Green band = sweet spot (0.8–1.3). Red = injury-risk zone (>1.5).")

acwr_df = df[["day", "acwr"]].dropna()

if len(acwr_df) >= 2:
    # Anchor bands to the data's actual date range so the band layer and the
    # line layer share an x-scale (day:T). Earlier version used pixel-space
    # alt.value(0..10_000) which hijacked the shared x-scale and squished
    # the line to the left edge.
    day_min = acwr_df["day"].min()
    day_max = acwr_df["day"].max()
    bands = pd.DataFrame(
        [
            {"day_start": day_min, "day_end": day_max,
             "y_low": 0.8, "y_high": 1.3, "tier": "sweet spot"},
            {"day_start": day_min, "day_end": day_max,
             "y_low": 1.5, "y_high": 3.0, "tier": "injury risk"},
        ]
    )
    y_max = max(2.0, acwr_df["acwr"].max() * 1.1)
    band_layer = (
        alt.Chart(bands)
        .mark_rect(opacity=0.18)
        .encode(
            x=alt.X("day_start:T", title=None),
            x2="day_end:T",
            y=alt.Y("y_low:Q", scale=alt.Scale(domain=[0, y_max]), title="ACWR"),
            y2="y_high:Q",
            color=alt.Color(
                "tier:N",
                scale=alt.Scale(
                    domain=["sweet spot", "injury risk"],
                    range=["#22c55e", "#ef4444"],
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
        )
    )
    line_layer = (
        alt.Chart(acwr_df)
        .mark_line(point=True, strokeWidth=2, color="#0ea5e9")
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("acwr:Q", scale=alt.Scale(domain=[0, y_max])),
            tooltip=[
                alt.Tooltip("day:T"),
                alt.Tooltip("acwr:Q", format=".2f"),
            ],
        )
    )
    st.altair_chart(
        (band_layer + line_layer).properties(height=320),
        use_container_width=True,
    )
else:
    st.info("Not enough data yet for an ACWR trajectory.")

# ------------------------------------------------------------------- HRV vs baseline
st.subheader("HRV vs. 7-day prior baseline")

hrv_df = df[["day", "hrv_ms", "hrv_ms_7d_prior_avg"]].dropna(subset=["hrv_ms"])
if not hrv_df.empty:
    tall = hrv_df.melt(
        id_vars="day",
        value_vars=["hrv_ms", "hrv_ms_7d_prior_avg"],
        var_name="series",
        value_name="ms",
    )
    tall["series"] = tall["series"].map(
        {"hrv_ms": "HRV today", "hrv_ms_7d_prior_avg": "Baseline (7d prior avg)"}
    )
    hrv_chart = (
        alt.Chart(tall.dropna())
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("ms:Q", title="HRV SDNN (ms)"),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(range=["#0ea5e9", "#94a3b8"]),
                legend=alt.Legend(title=None),
            ),
            tooltip=[alt.Tooltip("day:T"), "series", alt.Tooltip("ms:Q", format=".1f")],
        )
    )
    st.altair_chart(hrv_chart.properties(height=280), use_container_width=True)
else:
    st.info("No HRV data available.")

# -------------------------------------------------------------------- daily detail
st.subheader("Last 14 days")

recent = df.tail(14).copy()
recent = recent.assign(
    signal=recent["recovery_signal"].map(
        {
            "well_recovered": "🟢",
            "neutral": "🟡",
            "strained": "🔴",
            "insufficient_data": "⚪",
        }
    ),
)
display = (
    recent[
        [
            "day", "signal", "rhr_bpm", "hrv_ms",
            "zone_2_min_today", "zone_2_min_7d", "acwr",
            "days_since_last_workout",
        ]
    ]
    .rename(
        columns={
            "day": "Day",
            "signal": "Signal",
            "rhr_bpm": "RHR",
            "hrv_ms": "HRV",
            "zone_2_min_today": "Z2 today",
            "zone_2_min_7d": "Z2 7d",
            "acwr": "ACWR",
            "days_since_last_workout": "Days since wo.",
        }
    )
    .sort_values("Day", ascending=False)
)

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Day": st.column_config.DateColumn(format="ddd MMM D"),
        "RHR": st.column_config.NumberColumn(format="%.0f"),
        "HRV": st.column_config.NumberColumn(format="%.1f"),
        "Z2 today": st.column_config.NumberColumn(format="%.1f"),
        "Z2 7d": st.column_config.NumberColumn(format="%.0f"),
        "ACWR": st.column_config.NumberColumn(format="%.2f"),
    },
)

with st.expander("What the skill sees"):
    st.write(
        "Full mart_recovery_state columns for the most recent day — this is "
        "exactly the payload the weekly-health-review skill will consume."
    )
    st.json(
        {
            k: (None if pd.isna(v) else (str(v) if hasattr(v, "isoformat") else v))
            for k, v in latest.items()
        }
    )
