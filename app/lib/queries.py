"""Shared SQL helpers for Streamlit pages.

Any query that touches raw HR samples will scan millions of rows — those
functions MUST be wrapped in @st.cache_data at the function boundary. Apply
the decorator here, not inside page files.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ingest.config import DATABASE_URL


@st.cache_resource
def _engine() -> Engine:
    return create_engine(DATABASE_URL)


@st.cache_data(ttl=300)
def daily_rhr() -> pd.DataFrame:
    """Daily resting heart rate (bpm) in America/Chicago, from mart_daily_rhr."""
    return pd.read_sql(
        "SELECT day, resting_heart_rate, source_name "
        "FROM analytics_marts.mart_daily_rhr "
        "ORDER BY day",
        _engine(),
        parse_dates=["day"],
    )
