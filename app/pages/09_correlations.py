"""Lagged Correlation Heatmap — what predicts what.

Rows are leading indicators (yesterday's TRIMP, today's RHR, today's HRV);
columns are next-day outcomes (tomorrow's HRV, RHR, recovery score).
Each cell is the Pearson r over the lookback window. Cells where the
correlation is statistically significant (normal-approx p < 0.05) get
a star annotation.

Why this page exists. Line charts and heatmaps tell you what happened.
This grid tells you what *moved* what — which inputs are the actual levers
and which are noise.

Two more grids sit under "Recovery vs. external factors": yesterday's
weather and yesterday's schedule load (calendar density) against today's
recovery — the "did 5 back-to-back meetings tank my HRV?" question,
answered from mart_daily_context.

Significance test. We use the normal approximation: |r| > 1.96/sqrt(n).
Good enough for n ≥ 30 (our regime); avoids a scipy dependency.
"""

from __future__ import annotations

from math import erfc, sqrt

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.lib.queries import daily_context, daily_signals

st.title("Lagged Correlations")
st.caption(
    "Pearson correlation between leading indicators (rows) and next-day "
    "outcomes (columns). Cells with p < 0.05 (normal approximation) "
    "are starred."
)

df = daily_signals()

if df.empty:
    st.info("No daily signals data yet.")
    st.stop()

# ----------------------------------------------------------------- controls
window_days = st.selectbox(
    "Lookback window (days)",
    [30, 90, 180, 365],
    index=1,
)
st.caption(
    "Short windows expose noise. The same correlation can flip sign on a "
    "30-day window and stabilize on a 365-day window — that's a feature, "
    "not a bug."
)

# ----------------------------------------------------------- prepare lags
df = df.sort_values("day").reset_index(drop=True).copy()

# Leading indicators (left side of correlation): align onto the day they
# are *predicting from*. trimp_lag1 = yesterday's training load. rhr/hrv
# are today's values that predict tomorrow's outcome — no shift needed
# for the predictor side.
df["trimp_lag1"] = df["trimp"].shift(1)
df["sleep_lag1"] = df["sleep_minutes"].shift(1)

# Outcomes (right side): tomorrow's value, aligned onto today.
df["hrv_lead1"] = df["hrv_ms"].shift(-1)
df["rhr_lead1"] = df["rhr_bpm"].shift(-1)
df["recovery_lead1"] = df["recovery_score"].shift(-1)

# Trim to the lookback window
df = df[df["day"] >= df["day"].max() - pd.Timedelta(days=window_days - 1)].copy()

LEADING = {
    "trimp_lag1": "Yesterday's TRIMP",
    "sleep_lag1": "Yesterday's sleep",
    "rhr_bpm": "Today's RHR",
    "hrv_ms": "Today's HRV",
}
OUTCOMES = {
    "hrv_lead1": "Tomorrow's HRV",
    "rhr_lead1": "Tomorrow's RHR",
    "recovery_lead1": "Tomorrow's recovery",
}


def _two_tailed_p(r: float, n: int) -> float:
    """Normal-approximation two-tailed p-value for Pearson r.

    For n ≥ 30 (our regime), the t-distribution converges to normal and
    erfc gives a tight p-value without scipy.
    """
    if n < 3 or pd.isna(r):
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    t = r * sqrt((n - 2) / max(1 - r * r, 1e-12))
    return float(erfc(abs(t) / sqrt(2)))


# ----------------------------------------------------- correlation helpers
def _corr_rows(
    frame: pd.DataFrame,
    leading: dict[str, str],
    outcomes: dict[str, str],
    *,
    min_n: int = 5,
) -> pd.DataFrame:
    """Pearson r + normal-approx p for every (leading, outcome) pair.

    Returns a tidy frame (lead, outcome, r, n, p, sig, label) with lead
    and outcome as ordered Categoricals so chart axes stay stable. Pairs
    with fewer than ``min_n`` overlapping days render as "—".
    """
    out_rows = []
    for lead_col, lead_label in leading.items():
        for out_col, out_label in outcomes.items():
            sub = frame[[lead_col, out_col]].dropna()
            n = len(sub)
            if n < min_n:
                r = np.nan
                p = np.nan
            else:
                r = float(sub[lead_col].corr(sub[out_col]))
                p = _two_tailed_p(r, n)
            sig = not pd.isna(p) and p < 0.05
            out_rows.append(
                {
                    "lead": lead_label,
                    "outcome": out_label,
                    "r": r,
                    "n": n,
                    "p": p,
                    "sig": sig,
                    "label": f"{r:+.2f}{'★' if sig else ''}" if not pd.isna(r) else "—",
                }
            )
    out = pd.DataFrame(out_rows)
    out["lead"] = pd.Categorical(out["lead"], categories=list(leading.values()), ordered=True)
    out["outcome"] = pd.Categorical(
        out["outcome"], categories=list(outcomes.values()), ordered=True
    )
    return out


def _corr_heatmap(
    corr_df: pd.DataFrame,
    leading: dict[str, str],
    outcomes: dict[str, str],
    *,
    height: int,
) -> alt.LayerChart:
    """Red-blue Pearson-r heatmap with bold ``+r★`` text labels."""
    heat = (
        alt.Chart(corr_df)
        .mark_rect(stroke="white", strokeWidth=1)
        .encode(
            x=alt.X("outcome:N", title=None, sort=list(outcomes.values())),
            y=alt.Y("lead:N", title=None, sort=list(leading.values())),
            color=alt.Color(
                "r:Q",
                scale=alt.Scale(scheme="redblue", domain=[-1, 1], reverse=True),
                legend=alt.Legend(title="Pearson r", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("lead:N", title="Leading indicator"),
                alt.Tooltip("outcome:N", title="Outcome"),
                alt.Tooltip("r:Q", title="Pearson r", format="+.3f"),
                alt.Tooltip("n:Q", title="n (paired days)"),
                alt.Tooltip("p:Q", title="p (normal approx)", format=".4f"),
            ],
        )
    )
    text = (
        alt.Chart(corr_df)
        .mark_text(fontSize=14, fontWeight="bold")
        .encode(
            x="outcome:N",
            y="lead:N",
            text="label:N",
            color=alt.condition("abs(datum.r) > 0.5", alt.value("white"), alt.value("#1e293b")),
        )
    )
    return (heat + text).properties(height=height)


def _external_grid(
    frame: pd.DataFrame,
    leading: dict[str, str],
    outcomes: dict[str, str],
    *,
    height: int,
    empty_msg: str,
    caption: str | None = None,
) -> None:
    """Render one external-factor correlation grid, or an info card if empty."""
    corr = _corr_rows(frame, leading, outcomes)
    if corr["r"].isna().all():
        st.info(empty_msg)
        return
    st.altair_chart(_corr_heatmap(corr, leading, outcomes, height=height), use_container_width=True)
    if caption:
        st.caption(caption)


# ---------------------------------------------------- compute correlations
corr_df = _corr_rows(df, LEADING, OUTCOMES)

# ---------------------------------------------------------------- heatmap
st.altair_chart(
    _corr_heatmap(corr_df, LEADING, OUTCOMES, height=300),
    use_container_width=True,
)

# ---------------------------------------------------------------- key takeaways
st.subheader("Strongest signals in this window")
top = (
    corr_df.dropna(subset=["r"])
    .assign(strength=lambda x: x["r"].abs())
    .sort_values("strength", ascending=False)
    .head(5)
    .drop(columns=["strength", "label", "sig"])
    .rename(
        columns={
            "lead": "Leading",
            "outcome": "Outcome",
            "r": "Pearson r",
            "n": "n",
            "p": "p-value",
        }
    )
)
st.dataframe(
    top,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Pearson r": st.column_config.NumberColumn(format="%+.3f"),
        "p-value": st.column_config.NumberColumn(format="%.4f"),
    },
)

# ====================================================================
# Recovery vs. external factors
# ====================================================================
#
# Yesterday's weather and yesterday's schedule load (calendar density)
# predicting today's recovery outcomes. Same lag structure as the main
# heatmap (day D predictor → day D+1 outcome), split into two sub-grids
# so weather and schedule read independently and each can be empty on
# its own (one source configured without the other).

st.divider()
st.subheader("Recovery vs. external factors")
st.caption(
    "Yesterday's weather and schedule load as predictors of today's "
    "recovery signals. Same lag + significance method as the grid above."
)

ctx = daily_context()

if ctx.empty:
    st.info(
        "No external-context data yet — configure `OPENWEATHER_API_KEY` "
        "(weather) and/or `CALENDAR_ICS_URL` (calendar), then run the "
        "weekly load. The weather and schedule grids fill in independently."
    )
else:
    # daily_signals holds the recovery-side columns; daily_context holds the
    # external-factor predictors. Join on day, lag predictors back one day,
    # THEN trim to the window (so an edge-of-window lag still resolves).
    full = daily_signals().merge(ctx, on="day", how="inner").sort_values("day")
    full = full.reset_index(drop=True).copy()

    # Outcomes: today's values (predictors are the lagged side).
    full["hrv_today"] = full["hrv_ms"]
    full["rhr_today"] = full["rhr_bpm"]
    full["recovery_today"] = full["recovery_score"]
    full["sleep_today"] = full["sleep_minutes"]
    EXT_OUTCOMES = {
        "hrv_today": "Today's HRV",
        "rhr_today": "Today's RHR",
        "sleep_today": "Today's sleep (min)",
        "recovery_today": "Today's recovery",
    }

    # Predictors: shift each external column back one day (yesterday's value).
    WEATHER_COLS = (
        "temp_min_c",
        "temp_max_c",
        "temp_night_c",
        "humidity_afternoon",
        "precip_total_mm",
        "wind_max_mps",
    )
    # Boolean → float so the high-meeting-day point-biserial r is a plain Pearson.
    full["is_high_meeting_day"] = full["is_high_meeting_day"].astype(float)
    CALENDAR_COLS = (
        "timed_event_count",
        "timed_event_hours",
        "meeting_density",
        "is_high_meeting_day",
    )
    for col in (*WEATHER_COLS, *CALENDAR_COLS):
        full[f"{col}_lag1"] = full[col].shift(1)

    windowed = full[full["day"] >= full["day"].max() - pd.Timedelta(days=window_days - 1)].copy()

    # ----------------------------------------------------- weather sub-grid
    st.markdown("**Weather → recovery**")
    WEATHER_LEADING = {
        "temp_night_c_lag1": "Yesterday night temp (°C)",
        "temp_max_c_lag1": "Yesterday max temp (°C)",
        "humidity_afternoon_lag1": "Yesterday humidity (%)",
        "precip_total_mm_lag1": "Yesterday precip (mm)",
        "wind_max_mps_lag1": "Yesterday wind (m/s)",
    }
    if windowed[list(WEATHER_COLS)].notna().any().any():
        _external_grid(
            windowed,
            WEATHER_LEADING,
            EXT_OUTCOMES,
            height=320,
            empty_msg="Not enough weather/recovery overlap yet (need ≥ 5 paired days).",
            caption=(
                "Weather is sparse by nature — n drops fast for the rainier and "
                "windier rows. Treat |r| below 0.2 as noise even when starred."
            ),
        )
    else:
        st.info(
            "No weather data yet — set `OPENWEATHER_API_KEY` / `OPENWEATHER_LAT` / "
            "`OPENWEATHER_LON` in `.env`, then run "
            "`uv run python -m ingest.loaders.weather_openweather 30`."
        )

    # ----------------------------------------------- schedule-load sub-grid
    st.markdown("**Schedule load → recovery**")
    CALENDAR_LEADING = {
        "timed_event_count_lag1": "Yesterday's meetings (count)",
        "timed_event_hours_lag1": "Yesterday's meeting hours",
        "meeting_density_lag1": "Yesterday's meeting density",
        "is_high_meeting_day_lag1": "Yesterday a high-meeting day",
    }
    if windowed["timed_event_count"].fillna(0).gt(0).any():
        _external_grid(
            windowed,
            CALENDAR_LEADING,
            EXT_OUTCOMES,
            height=300,
            empty_msg="Not enough calendar/recovery overlap yet (need ≥ 5 paired days).",
            caption=(
                'The "5 back-to-back meetings" question lives here — meeting '
                "density near 1.0 means a packed day. Correlation ≠ causation: a "
                "busy calendar co-moves with travel, stress, and short sleep."
            ),
        )
    else:
        st.info(
            "No calendar data yet — set `CALENDAR_ICS_URL` in `.env`, then run "
            "the weekly load so `mart_daily_context` fills in."
        )

# ---------------------------------------------------------------- caveats
with st.expander("Method + caveats"):
    end_date = df["day"].max().strftime("%b %d, %Y") if not df.empty else "n/a"
    st.markdown(
        f"""
- **Window**: last {window_days} days, ending {end_date}.
- **Pearson r**: linear correlation only; non-monotonic relationships are
  invisible.
- **Significance**: two-tailed p-value via the normal approximation
  (`erfc(|t|/√2)`). Tight for n ≥ 30; loose for very small windows.
- **Lag structure**: leading indicators are aligned to predict the *next
  day's* outcome — so each row in the underlying frame pairs day D's lead
  with day D+1's outcome, except yesterday's TRIMP which is day D-1 → D.
- **External factors (lower grids)**: same lag idea — every weather and
  calendar column is shifted back one day, so each row pairs *yesterday's*
  weather / schedule with *today's* recovery / HRV / sleep. Pairing is an
  `inner` join, so the effective window can be shorter than the upper grid
  until each source's backfill catches up.
- **Schedule load**: *meeting density* is the share of the first-to-last
  meeting window actually spent in meetings — a back-to-back proxy (~1.0 =
  packed). *High-meeting day* is ≥ 5 timed events. These describe what your
  calendar looked like, not causation: a packed day co-moves with stress,
  travel, and short sleep, any of which could be the real driver.
"""
    )
