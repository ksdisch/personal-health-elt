"""Daily view — today's key metrics at a glance.

One tab per metric. Each tab uses the same _render helper so the layout
stays consistent as more metrics are added.
"""
import pandas as pd
import streamlit as st

from app.lib.queries import daily_hrv, daily_rhr, daily_vo2max, daily_weight

st.title("Daily")
st.caption("All values in America/Chicago")


def _render(
    df: pd.DataFrame,
    *,
    value_col: str,
    label: str,
    unit: str,
    decimals: int = 1,
    empty_hint: str | None = None,
) -> None:
    """Standard metric layout: three cards + line chart + raw-data expander."""
    if df.empty:
        st.info(empty_hint or f"No {label} data loaded yet.")
        return

    latest = df.iloc[-1]
    avg_7 = df.tail(7)[value_col].mean()
    avg_all = df[value_col].mean()

    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"Latest {label}",
        f"{latest[value_col]:.{decimals}f} {unit}",
        help=f"as of {latest['day'].strftime('%Y-%m-%d')}",
    )
    c2.metric("7-day average", f"{avg_7:.{decimals}f} {unit}")
    c3.metric("All-time average", f"{avg_all:.{decimals}f} {unit}")

    st.line_chart(df.set_index("day")[value_col], height=320)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True, hide_index=True)


tab_rhr, tab_hrv, tab_vo2, tab_weight = st.tabs(
    ["Resting HR", "HRV", "VO₂ Max", "Weight"]
)

with tab_rhr:
    _render(
        daily_rhr(),
        value_col="resting_heart_rate",
        label="RHR",
        unit="bpm",
        decimals=0,
    )

with tab_hrv:
    _render(
        daily_hrv(),
        value_col="hrv_ms",
        label="HRV",
        unit="ms",
        decimals=1,
    )

with tab_vo2:
    _render(
        daily_vo2max(),
        value_col="vo2max",
        label="VO₂ Max",
        unit="mL/(kg·min)",
        decimals=1,
    )

with tab_weight:
    _render(
        daily_weight(),
        value_col="weight_kg",
        label="Weight",
        unit="kg",
        decimals=1,
        empty_hint="No weight data yet. Connect a smart scale to Apple Health and re-export.",
    )
