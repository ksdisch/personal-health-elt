"""Anomaly Dashboard — rolling z-score early-warning system.

Each metric (RHR, HRV) is plotted as a 90-day line with a shaded ±2σ band
derived from a rolling 28-day mean/std (excluding today). Days outside the
band are flagged red. A side panel lists the most recent anomalies.

The textbook overreaching/illness signature is RHR spike + HRV crash on the
same day — both panels going red together is a 24–48 hour early warning.

Sleep duration will join here as a third panel once the categories loader
lands and a mart_daily_sleep is built.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import daily_anomaly_bands

st.title("Anomaly Dashboard")
st.caption(
    "Rolling 28-day z-score bands from `int_daily_anomaly_bands`. "
    "Today is excluded from its own baseline; |z| > 2 is flagged."
)

df = daily_anomaly_bands()

if df.empty:
    st.info("No anomaly bands yet — need at least 28 days of metric history.")
    st.stop()

window_days = st.slider("Lookback window (days)", 30, 365, 90, step=15)
df = df[df["day"] >= df["day"].max() - pd.Timedelta(days=window_days)].copy()

METRIC_LABELS = {
    "rhr_bpm": "Resting HR (bpm)",
    "hrv_ms": "HRV SDNN (ms)",
}


def _panel(metric: str, label: str) -> alt.Chart:
    sub = df[df["metric"] == metric].copy()
    if sub.empty:
        return None

    sub["band_low"] = sub["rolling_mean"] - 2 * sub["rolling_std"]
    sub["band_high"] = sub["rolling_mean"] + 2 * sub["rolling_std"]
    sub["is_anomaly"] = sub["z_score"].abs() > 2

    band = (
        alt.Chart(sub.dropna(subset=["band_low", "band_high"]))
        .mark_area(opacity=0.18, color="#0ea5e9")
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("band_low:Q", title=label),
            y2="band_high:Q",
        )
    )
    mean_line = (
        alt.Chart(sub.dropna(subset=["rolling_mean"]))
        .mark_line(strokeDash=[4, 4], color="#0ea5e9")
        .encode(x="day:T", y="rolling_mean:Q")
    )
    line = (
        alt.Chart(sub)
        .mark_line(color="#1e293b", strokeWidth=2)
        .encode(
            x="day:T",
            y="value:Q",
            tooltip=[
                alt.Tooltip("day:T", format="%a %b %d"),
                alt.Tooltip("value:Q", title=label, format=".1f"),
                alt.Tooltip("rolling_mean:Q", title="28d mean", format=".1f"),
                alt.Tooltip("z_score:Q", title="z-score", format=".2f"),
            ],
        )
    )
    flags = (
        alt.Chart(sub[sub["is_anomaly"]])
        .mark_circle(color="#ef4444", size=90)
        .encode(
            x="day:T",
            y="value:Q",
            tooltip=[
                alt.Tooltip("day:T", format="%a %b %d"),
                alt.Tooltip("value:Q", title=label, format=".1f"),
                alt.Tooltip("z_score:Q", title="z-score", format=".2f"),
            ],
        )
    )
    return (band + mean_line + line + flags).properties(height=240)


# ----------------------------------------------------------------- charts
left, right = st.columns([3, 1])

with left:
    for metric, label in METRIC_LABELS.items():
        chart = _panel(metric, label)
        st.subheader(label)
        if chart is None:
            st.info(f"No {label.lower()} data yet.")
        else:
            st.altair_chart(chart, use_container_width=True)

with right:
    st.subheader("Recent anomalies")
    recent = (
        df[df["z_score"].abs() > 2]
        .assign(magnitude=lambda x: x["z_score"].abs())
        .sort_values("day", ascending=False)
        .head(20)
    )
    if recent.empty:
        st.info("None in window.")
    else:
        recent = recent.assign(
            metric_label=recent["metric"].map(METRIC_LABELS),
            direction=recent["z_score"].apply(lambda z: "↑" if z > 0 else "↓"),
        )
        st.dataframe(
            recent[["day", "metric_label", "direction", "value", "z_score"]]
            .rename(
                columns={
                    "day": "Day",
                    "metric_label": "Metric",
                    "direction": "Dir",
                    "value": "Value",
                    "z_score": "z",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Day": st.column_config.DateColumn(format="MMM D"),
                "Value": st.column_config.NumberColumn(format="%.1f"),
                "z": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# --------------------------------------------------- combined-day callout
combined = (
    df.pivot(index="day", columns="metric", values="z_score")
    .dropna(how="all")
)
if {"rhr_bpm", "hrv_ms"}.issubset(combined.columns):
    flagged = combined[
        (combined["rhr_bpm"] > 2) & (combined["hrv_ms"] < -2)
    ]
    if not flagged.empty:
        st.warning(
            f"**{len(flagged)} day(s)** in the window had RHR ↑ AND HRV ↓ "
            f"both beyond 2σ — the textbook overreaching/illness pattern. "
            f"Most recent: {flagged.index.max().strftime('%a %b %d, %Y')}."
        )
