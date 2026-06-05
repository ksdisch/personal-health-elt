"""Experiments — personal causal inference over logged interventions.

The descriptive/predictive pages answer "what happened" and "what's next". This
one answers the *causal* question: did an intervention actually move a metric?

For each experiment (defined in `transform/seeds/experiments.csv`) and target
metric, the page shows the interrupted-time-series fit — actuals around the
intervention, the pre-intervention mean extended as a dashed **counterfactual**,
and the post mean — plus an effect card with the level change, its confidence
interval, the autocorrelation-robust (Newey-West HAC) p-value, and a
permutation/placebo p-value. The verdict is deliberately conservative for n-of-1
data: a real effect needs BOTH p-values under 0.05, ≥10 obs per side, and no
overlapping experiment. See ingest/analysis/causal.py + ADR-0008 / ADR-0009.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.lib.queries import experiment_effects, experiment_metric_series

_PRE_WINDOW_DAYS = 28

METRIC_LABELS = {"rhr_bpm": "Resting HR (bpm)", "hrv_ms": "HRV SDNN (ms)"}

_VERDICT_STYLE = {
    "likely_decrease": ("🟢", "likely decrease"),
    "likely_increase": ("🟢", "likely increase"),
    "no_clear_effect": ("⚪", "no clear effect"),
    "confounded": ("🟠", "confounded (overlapping experiment)"),
    "insufficient_data": ("⚪", "insufficient data"),
}

st.title("Experiments")
st.caption(
    "Personal causal inference over logged interventions — interrupted time "
    "series with Newey-West HAC errors, a permutation/placebo p-value, and a "
    "secondary difference-in-differences. Conservative by design for n-of-1 data."
)

effects = experiment_effects()
if effects.empty:
    st.info(
        "No experiment effects yet — `mart_experiment_effects` is empty. Add rows "
        "to `transform/seeds/experiments.csv`, run the causal step "
        "(`uv run python -m ingest.analysis.causal`), then "
        "`uv run dbt build --select stg_experiment_effects+` and reload."
    )
    st.stop()


def _its_chart(metric: str, label: str, row: pd.Series) -> alt.Chart | None:
    start = (row["start_date"] - pd.Timedelta(days=_PRE_WINDOW_DAYS)).date().isoformat()
    end = row["end_date"].date().isoformat()
    cutoff = pd.Timestamp(row["cutoff_date"])
    series = experiment_metric_series(metric, start, end)
    if series.empty:
        return None

    pre = series[series["day"] < cutoff]
    post = series[series["day"] >= cutoff]
    if pre.empty or post.empty:
        return None
    pre_mean = float(pre["value"].mean())
    post_mean = float(post["value"].mean())

    actual = (
        alt.Chart(series)
        .mark_line(point=True, color="#1e293b", strokeWidth=1.5)
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("value:Q", title=label, scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("day:T", format="%b %d"), alt.Tooltip("value:Q", format=".1f")],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"day": [cutoff]}))
        .mark_rule(color="#0ea5e9", strokeDash=[4, 3])
        .encode(x="day:T")
    )
    pre_seg = (
        alt.Chart(pd.DataFrame({"day": [series["day"].min(), cutoff], "m": [pre_mean, pre_mean]}))
        .mark_line(color="#64748b", strokeWidth=2)
        .encode(x="day:T", y="m:Q")
    )
    post_seg = (
        alt.Chart(pd.DataFrame({"day": [cutoff, series["day"].max()], "m": [post_mean, post_mean]}))
        .mark_line(color="#16a34a", strokeWidth=2)
        .encode(x="day:T", y="m:Q")
    )
    counterfactual = (
        alt.Chart(pd.DataFrame({"day": [cutoff, series["day"].max()], "m": [pre_mean, pre_mean]}))
        .mark_line(color="#dc2626", strokeWidth=2, strokeDash=[6, 4])
        .encode(x="day:T", y="m:Q")
    )

    return (pre_seg + post_seg + counterfactual + rule + actual).properties(height=240)


for name, grp in effects.groupby("experiment_name", sort=True):
    head = grp.iloc[0]
    st.subheader(name.replace("_", " ").title())
    window = f"{head['start_date'].date()} → {head['end_date'].date()}"
    st.caption(f"_{head['hypothesis']}_  ·  window {window}")

    for _, row in grp.iterrows():
        metric = row["target_metric"]
        label = METRIC_LABELS.get(metric, metric)
        emoji, verdict_text = _VERDICT_STYLE.get(row["verdict"], ("⚪", row["verdict"]))

        chart_col, card_col = st.columns([3, 2])
        with chart_col:
            chart = _its_chart(metric, label, row)
            if chart is None:
                st.info(f"No series for {label}.")
            else:
                st.altair_chart(chart, use_container_width=True)
        with card_col:
            st.markdown(f"**{label}** — {emoji} {verdict_text}")
            if pd.notna(row["level_change"]):
                ci = f"[{row['level_ci_low']:.2f}, {row['level_ci_high']:.2f}]"
                st.metric("Level change", f"{row['level_change']:+.2f}", help=f"95% CI {ci}")
                c1, c2 = st.columns(2)
                c1.metric("HAC p", f"{row['hac_p_value']:.3f}")
                c2.metric("placebo p", f"{row['placebo_p_value']:.3f}")
                did = "—" if pd.isna(row["did_estimate"]) else f"{row['did_estimate']:+.2f}"
                st.caption(
                    f"n = {int(row['n_pre'])} pre / {int(row['n_post'])} post · "
                    f"DiD vs control: {did}"
                )
            else:
                n_pre, n_post = int(row["n_pre"]), int(row["n_post"])
                st.caption(f"Insufficient data (n = {n_pre} pre / {n_post} post).")
    st.divider()

with st.expander("Method + honest constraints", expanded=False):
    st.markdown(
        "- **Estimator:** segmented-regression interrupted time series. The level "
        "change is the discontinuity at the intervention; **Newey-West HAC** errors "
        "correct for the autocorrelation that makes a naive t-test on daily "
        "RHR/HRV wrong.\n"
        "- **Permutation p:** re-fits the level change at many random fake cutoffs — "
        "an empirical p-value trustworthy at n~30–60 where parametric p's are "
        "fragile.\n"
        "- **DiD:** difference-in-differences vs a control metric, reported but never "
        "gating (a single subject rarely has a truly unaffected control).\n"
        "- **Verdict:** `likely_*` requires HAC p < 0.05 AND placebo p < 0.05 AND "
        "≥10 obs per side AND no overlapping experiment.\n"
        "- **n-of-1 caveat:** ~30–60 days per experiment is thin; effects carry wide "
        "CIs. The method + the honest interval is the deliverable, not a confident "
        "point estimate. Validated by recovering a *planted* synthetic effect "
        "(tests/test_causal.py)."
    )
