"""Streamlit landing page for the personal health ELT pipeline."""
import streamlit as st

st.set_page_config(page_title="Personal Health", layout="wide")

st.title("Personal Health")
st.caption("Apple Health → Postgres → dbt → Streamlit")

st.write(
    "Use the sidebar to navigate between daily, weekly review, training load, "
    "and body composition views."
)
