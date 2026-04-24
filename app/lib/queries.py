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


def _daily_mart(sql: str) -> pd.DataFrame:
    """Shared read pattern for daily marts (keeps each public fn a one-liner)."""
    return pd.read_sql(sql, _engine(), parse_dates=["day"])


@st.cache_data(ttl=300)
def daily_rhr() -> pd.DataFrame:
    """Daily resting heart rate (bpm), one row per day."""
    return _daily_mart(
        "SELECT day, resting_heart_rate, source_name "
        "FROM analytics_marts.mart_daily_rhr ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_hrv() -> pd.DataFrame:
    """Daily HRV SDNN (ms), averaged across nightly samples."""
    return _daily_mart(
        "SELECT day, hrv_ms, sample_count "
        "FROM analytics_marts.mart_daily_hrv ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_vo2max() -> pd.DataFrame:
    """Daily VO2 Max (mL/(kg·min)). Sparse — only on workout days."""
    return _daily_mart(
        "SELECT day, vo2max, sample_count "
        "FROM analytics_marts.mart_daily_vo2max ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_weight() -> pd.DataFrame:
    """Daily weight (kg), last reading of the day wins."""
    return _daily_mart(
        "SELECT day, weight_kg, source_name "
        "FROM analytics_marts.mart_daily_weight ORDER BY day"
    )
