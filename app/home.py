"""Streamlit landing page for the personal health ELT pipeline."""
import sys
from pathlib import Path

# Put project root on sys.path so pages can import ingest.* and app.lib.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Personal Health", layout="wide")

st.title("Personal Health")
st.caption("Apple Health → Postgres → dbt → Streamlit")

st.write(
    "Use the sidebar to navigate between daily, weekly review, training load, "
    "and body composition views."
)
