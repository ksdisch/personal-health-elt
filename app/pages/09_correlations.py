"""Lagged Correlation Heatmap — what predicts what.

Rows are leading indicators (yesterday's TRIMP, today's RHR, today's HRV);
columns are next-day outcomes (tomorrow's HRV, RHR, recovery score).
Each cell is the Pearson r over the lookback window. Cells where the
correlation is statistically significant (normal-approx p < 0.05) get
a star annotation.

Why this page exists. Line charts and heatmaps tell you what happened.
This grid tells you what *moved* what — which inputs are the actual levers
and which are noise. Sleep duration is the most-anticipated row here and
will appear once ingest/loaders/categories.py is implemented and a
mart_daily_sleep is built.

Significance test. We use the normal approximation: |r| > 1.96/sqrt(n).
Good enough for n ≥ 30 (our regime); avoids a scipy dependency.
"""
from __future__ import annotations

from math import erfc, sqrt

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.lib.queries import daily_signals

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

# Outcomes (right side): tomorrow's value, aligned onto today.
df["hrv_lead1"] = df["hrv_ms"].shift(-1)
df["rhr_lead1"] = df["rhr_bpm"].shift(-1)
df["recovery_lead1"] = df["recovery_score"].shift(-1)

# Trim to the lookback window
df = df[df["day"] >= df["day"].max() - pd.Timedelta(days=window_days - 1)].copy()

LEADING = {
    "trimp_lag1": "Yesterday's TRIMP",
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


# ---------------------------------------------------- compute correlations
rows = []
for lead_col, lead_label in LEADING.items():
    for out_col, out_label in OUTCOMES.items():
        sub = df[[lead_col, out_col]].dropna()
        n = len(sub)
        if n < 5:
            r = np.nan
            p = np.nan
        else:
            r = float(sub[lead_col].corr(sub[out_col]))
            p = _two_tailed_p(r, n)
        rows.append(
            {
                "lead": lead_label,
                "outcome": out_label,
                "r": r,
                "n": n,
                "p": p,
                "sig": p is not None and not pd.isna(p) and p < 0.05,
                "label": (
                    f"{r:+.2f}{'★' if (p is not None and not pd.isna(p) and p < 0.05) else ''}"
                    if not pd.isna(r)
                    else "—"
                ),
            }
        )

corr_df = pd.DataFrame(rows)

# Preserve row/column order for visual stability
corr_df["lead"] = pd.Categorical(corr_df["lead"], categories=list(LEADING.values()), ordered=True)
corr_df["outcome"] = pd.Categorical(
    corr_df["outcome"], categories=list(OUTCOMES.values()), ordered=True
)

# ---------------------------------------------------------------- heatmap
heat = (
    alt.Chart(corr_df)
    .mark_rect(stroke="white", strokeWidth=1)
    .encode(
        x=alt.X("outcome:N", title=None, sort=list(OUTCOMES.values())),
        y=alt.Y("lead:N", title=None, sort=list(LEADING.values())),
        color=alt.Color(
            "r:Q",
            scale=alt.Scale(
                scheme="redblue",
                domain=[-1, 1],
                reverse=True,
            ),
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
        color=alt.condition(
            "abs(datum.r) > 0.5", alt.value("white"), alt.value("#1e293b")
        ),
    )
)
st.altair_chart((heat + text).properties(height=300), use_container_width=True)

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
- **Missing**: sleep duration → next-day HRV is the most-asked-about cell
  and is blank until `ingest/loaders/categories.py` is implemented.
"""
    )
