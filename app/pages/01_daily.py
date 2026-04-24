"""Daily view — today's key metrics at a glance."""
import streamlit as st

from app.lib.queries import daily_rhr

st.title("Daily")
st.caption("Resting heart rate (bpm), America/Chicago")

df = daily_rhr()

if df.empty:
    st.info(
        "No resting HR data yet. Load a CSV first:\n\n"
        "```\nuv run python -m ingest.loaders.quantities <path-to-csv>\n```"
    )
else:
    latest = df.iloc[-1]
    avg_7 = df.tail(7)["resting_heart_rate"].mean()
    avg_all = df["resting_heart_rate"].mean()

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Latest RHR",
        f"{int(latest['resting_heart_rate'])} bpm",
        help=f"as of {latest['day'].strftime('%Y-%m-%d')}",
    )
    col2.metric("7-day average", f"{avg_7:.1f} bpm")
    col3.metric("All-time average", f"{avg_all:.1f} bpm")

    st.line_chart(df.set_index("day")["resting_heart_rate"], height=320)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True, hide_index=True)
