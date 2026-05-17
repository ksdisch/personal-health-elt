"""Forecast — 7-day Holt projections + walk-forward backtest accuracy.

Every other page in this app looks backward — actuals, rolling averages,
anomaly bands. This one looks forward. For each of RHR, HRV, training
load, and a derived ACWR, the page renders the historical actuals as a
solid line and continues with a dashed forecast line + ±1.96·σ·√h
confidence band for the next 7 days.

The backtest table at the bottom reports MAE / RMSE / MAPE per metric
per horizon, honestly surfaced. With ~30 days of history available
today, the n per (metric × horizon) cell is small and the page says so
— this is the analytics-engineering "show your work" panel, not a
product claim.

Why ACWR has no band: it's not a fitted time-series forecast, it's a
deterministic projection from forecasted training_load (continuation
assumption). Cleanly propagating the underlying training_load
uncertainty would require Monte Carlo; the page caption flags this.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import forecast_backtest, forecast_bands

st.title("Forecast")
st.caption(
    "7-day Holt forecasts for the recovery signals plus walk-forward "
    "backtest accuracy. Solid = actuals, dashed = forecast, shaded "
    "band = ±1.96·σ·√h. Pure-SQL implementation (no ML dependencies)."
)

bands = forecast_bands()
backtest = forecast_backtest()

if bands.empty:
    st.info(
        "No forecast data yet — `mart_forecast_bands` is empty. "
        "Run `uv run dbt build --select +mart_forecast_bands` and reload."
    )
    st.stop()


METRIC_LABELS = {
    "rhr_bpm": "Resting HR (bpm)",
    "hrv_ms": "HRV SDNN (ms)",
    "training_load": "Training Load (TRIMP)",
    "acwr": "ACWR (acute / chronic)",
}

# Order the panels: physiology signals first (where the forecast is
# strongest), then training_load, then derived ACWR.
METRIC_ORDER = ["rhr_bpm", "hrv_ms", "training_load", "acwr"]


def _panel(metric: str, label: str) -> alt.Chart | None:
    sub = bands[bands["metric"] == metric].copy()
    if sub.empty:
        return None

    # Build a single "line value" column so the historical actual and the
    # forecast point connect visually at the boundary day.
    sub["display"] = sub["value"].combine_first(sub["forecast"])

    historical = sub[~sub["is_forecast"]]
    fcst = sub[sub["is_forecast"]]

    # Historical actual line (solid).
    line_actual = (
        alt.Chart(historical)
        .mark_line(color="#1e293b", strokeWidth=2)
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("value:Q", title=label, scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("day:T", format="%a %b %d, %Y"),
                alt.Tooltip("value:Q", title=label, format=".2f"),
            ],
        )
    )

    # Forecast line (dashed). Prepend the last historical row so the
    # dashed segment starts where the solid one ends instead of leaving
    # a one-day gap on the boundary.
    if not historical.empty and not fcst.empty:
        bridge_row = historical.tail(1).copy()
        bridge_row["forecast"] = bridge_row["value"]
        fcst_for_line = pd.concat([bridge_row, fcst], ignore_index=True)
    else:
        fcst_for_line = fcst

    line_forecast = (
        alt.Chart(fcst_for_line)
        .mark_line(color="#0ea5e9", strokeWidth=2, strokeDash=[6, 4])
        .encode(
            x="day:T",
            y=alt.Y("forecast:Q", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("day:T", format="%a %b %d, %Y"),
                alt.Tooltip("forecast:Q", title="Forecast", format=".2f"),
                alt.Tooltip("horizon_day_offset:Q", title="Days ahead", format="d"),
            ],
        )
    )

    # Confidence band. Only present for fitted metrics — derived ACWR
    # has NULL bands and the area mark will just render nothing.
    band = (
        alt.Chart(fcst.dropna(subset=["forecast_lower", "forecast_upper"]))
        .mark_area(opacity=0.18, color="#0ea5e9")
        .encode(
            x="day:T",
            y=alt.Y("forecast_lower:Q", title=label),
            y2="forecast_upper:Q",
            tooltip=[
                alt.Tooltip("day:T", format="%a %b %d, %Y"),
                alt.Tooltip("forecast_lower:Q", title="Lower", format=".2f"),
                alt.Tooltip("forecast_upper:Q", title="Upper", format=".2f"),
            ],
        )
    )

    return (band + line_actual + line_forecast).properties(height=240)


# ----------------------------------------------------------------- charts
for metric in METRIC_ORDER:
    if metric not in METRIC_LABELS:
        continue
    st.subheader(METRIC_LABELS[metric])
    chart = _panel(metric, METRIC_LABELS[metric])
    if chart is None:
        st.info(f"No data for {METRIC_LABELS[metric].lower()} yet.")
        continue
    st.altair_chart(chart, use_container_width=True)

    if metric == "acwr":
        st.caption(
            "ACWR forecast is a **deterministic projection** from "
            "forecasted training_load, not a fitted time series — "
            "answers 'where does ACWR land if my recent pattern "
            "continues?' Bands omitted (would require Monte Carlo)."
        )

# ------------------------------------------------------ backtest section
st.divider()
st.subheader("Backtest accuracy")
st.caption(
    "Walk-forward eval: for each historical cutoff day, the model "
    "predicts 1-7 days ahead using only data through that cutoff, then "
    "compares to what actually happened. MAPE excluded for "
    "training_load because actual=0 days inflate it pathologically."
)

if backtest.empty:
    st.info("No backtest data yet.")
else:
    rows: list[dict] = []
    for metric in ["rhr_bpm", "hrv_ms", "training_load"]:
        for horizon in range(1, 8):
            cell = backtest[(backtest["metric"] == metric) & (backtest["horizon_days"] == horizon)]
            if cell.empty:
                continue
            mae = float(cell["abs_error"].mean())
            rmse = float((cell["abs_error"] ** 2).mean() ** 0.5)
            avg_actual = float(cell["actual"].mean())
            if metric == "training_load":
                mape_str = "—"
            else:
                mape = 100 * (cell["abs_error"] / cell["actual"].abs().replace(0, pd.NA)).mean()
                mape_str = f"{mape:.1f}%" if pd.notna(mape) else "—"
            rows.append(
                {
                    "Metric": METRIC_LABELS[metric],
                    "Horizon (d)": horizon,
                    "n": len(cell),
                    "MAE": round(mae, 2),
                    "RMSE": round(rmse, 2),
                    "MAPE": mape_str,
                    "Avg actual": round(avg_actual, 2),
                }
            )

    bt_df = pd.DataFrame(rows)
    st.dataframe(bt_df, use_container_width=True, hide_index=True)

    # One-paragraph plain-English read of the table.
    rhr_h1 = bt_df[(bt_df["Metric"].str.startswith("Resting")) & (bt_df["Horizon (d)"] == 1)]
    hrv_h1 = bt_df[(bt_df["Metric"].str.startswith("HRV")) & (bt_df["Horizon (d)"] == 1)]
    tl_h1 = bt_df[(bt_df["Metric"].str.startswith("Training")) & (bt_df["Horizon (d)"] == 1)]

    readout: list[str] = []
    if not rhr_h1.empty:
        readout.append(
            f"**RHR** 1-day MAE = {rhr_h1.iloc[0]['MAE']} bpm "
            f"(avg actual ~{rhr_h1.iloc[0]['Avg actual']:.0f}); forecast is usable."
        )
    if not hrv_h1.empty:
        readout.append(
            f"**HRV** 1-day MAE = {hrv_h1.iloc[0]['MAE']} ms "
            f"(avg actual ~{hrv_h1.iloc[0]['Avg actual']:.0f}); high day-to-day "
            f"variance limits how much weight to put on point forecasts — use the band."
        )
    if not tl_h1.empty:
        readout.append(
            f"**Training load** 1-day MAE = {tl_h1.iloc[0]['MAE']} TRIMP "
            f"(avg actual ~{tl_h1.iloc[0]['Avg actual']:.0f}); Holt's struggles "
            f"with bursty workout/rest patterns — the forecast is a baseline-only "
            f"signal, not a session predictor."
        )

    if readout:
        st.markdown(" ".join(readout))

# --------------------------------------------------- honest constraints
st.divider()
with st.expander("Method + constraints", expanded=False):
    st.markdown(
        "- **Method:** Holt's linear exponential smoothing (level + trend), "
        "pure SQL via the `holt_forecast` macro. No Python ML dependencies.\n"
        "- **Hyperparameters:** α=0.3, β=0.1 fixed. Grid-search tuning is "
        "filed as a follow-up in BACKLOG.md.\n"
        "- **Bands:** ±1.96·σ·√h where σ is the in-sample residual stddev. "
        "Heuristic, not a rigorous prediction interval.\n"
        "- **ACWR:** deterministic continuation projection from forecasted "
        "training_load, not a fitted time series.\n"
        "- **Available history:** see chart x-axes. The backtest n per "
        "(metric × horizon) is small — read accuracy numbers with that in mind."
    )
