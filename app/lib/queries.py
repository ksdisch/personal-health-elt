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
        "SELECT day, hrv_ms, sample_count FROM analytics_marts.mart_daily_hrv ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_vo2max() -> pd.DataFrame:
    """Daily VO2 Max (mL/(kg·min)). Sparse — only on workout days."""
    return _daily_mart(
        "SELECT day, vo2max, sample_count FROM analytics_marts.mart_daily_vo2max ORDER BY day"
    )


@st.cache_data(ttl=300)
def daily_weight() -> pd.DataFrame:
    """Daily weight (kg), last reading of the day wins."""
    return _daily_mart(
        "SELECT day, weight_kg, source_name FROM analytics_marts.mart_daily_weight ORDER BY day"
    )


@st.cache_data(ttl=300)
def recovery_state() -> pd.DataFrame:
    """Public-API mart feeding weekly-health-review."""
    return _daily_mart(
        "SELECT day, is_today, rhr_bpm, hrv_ms, hrv_ms_7d_prior_avg, "
        "zone_2_min_today, zone_2_min_7d, strength_sessions_7d, "
        "training_load_today, acute_load_7d, chronic_load_28d, acwr, "
        "days_since_last_workout, recovery_signal "
        "FROM analytics_marts.mart_recovery_state ORDER BY day"
    )


@st.cache_data(ttl=300)
def training_load() -> pd.DataFrame:
    """Daily training load + rolling windows."""
    return _daily_mart(
        "SELECT day, zone_2_min, zone_2_min_7d, strength_sessions_7d, "
        "strength_min_7d, training_load, acute_load_7d, chronic_load_28d, acwr "
        "FROM analytics_marts.mart_training_load ORDER BY day"
    )


@st.cache_data(ttl=300)
def workout_zones() -> pd.DataFrame:
    """Per-workout zone breakdown (seconds in each zone)."""
    return pd.read_sql(
        "SELECT day_local AS day, activity_type, start_ts_local AS start_ts, "
        "duration_sec, zone_1_sec, zone_2_sec, zone_3_sec, zone_4_sec, "
        "zone_5_sec, hr_sample_count, avg_hr_bpm, max_hr_bpm "
        "FROM analytics_marts.mart_workout_zones ORDER BY start_ts_local",
        _engine(),
        parse_dates=["day", "start_ts"],
    )


@st.cache_data(ttl=300)
def daily_anomaly_bands() -> pd.DataFrame:
    """Tall-format daily metric values with rolling 28d mean, std, z-score.

    Powers the Anomaly Dashboard. Currently covers rhr_bpm and hrv_ms;
    sleep duration joins here once the categories loader is built.
    """
    return _daily_mart(
        "SELECT day, metric, value, rolling_mean, rolling_std, z_score "
        "FROM analytics_marts.mart_daily_anomaly_bands "
        "ORDER BY metric, day"
    )


@st.cache_data(ttl=300)
def hr_zones() -> pd.DataFrame:
    """HR zone boundaries from the `hr_zones` seed.

    Columns: zone_number, zone_name, hr_low, hr_high. Zone names match
    `transform/seeds/hr_zones.csv` (recovery, aerobic_base, tempo,
    threshold, vo2_max). Use this instead of hardcoding zone boundaries.
    """
    return pd.read_sql(
        "SELECT zone_number, zone_name, hr_low, hr_high "
        "FROM analytics_seeds.hr_zones ORDER BY zone_number",
        _engine(),
    )


@st.cache_data(ttl=300)
def monthly_aerobic_efficiency() -> pd.DataFrame:
    """Monthly time-weighted avg HR within Zone 2 + total Z2 minutes."""
    return pd.read_sql(
        "SELECT month, avg_z2_hr, z2_minutes, sample_count "
        "FROM analytics_marts.mart_monthly_aerobic_efficiency "
        "ORDER BY month",
        _engine(),
        parse_dates=["month"],
    )


@st.cache_data(ttl=300)
def daily_signals() -> pd.DataFrame:
    """Wide-format daily signals for correlation analysis."""
    return _daily_mart(
        "SELECT day, rhr_bpm, hrv_ms, trimp, acwr, recovery_signal, "
        "recovery_score "
        "FROM analytics_marts.mart_daily_signals ORDER BY day"
    )


@st.cache_data(ttl=300)
def sleep_nights() -> pd.DataFrame:
    """One row per night with composite score, efficiency, stage minutes."""
    return pd.read_sql(
        "SELECT night_date, time_in_bed_min, time_asleep_min, "
        "sleep_efficiency_pct, rem_min, deep_min, core_min, awake_min, "
        "rem_pct_of_sleep, deep_pct_of_sleep, awakening_count, "
        "bedtime_local, wake_time_local, composite_score "
        "FROM analytics_marts.mart_sleep_nights ORDER BY night_date",
        _engine(),
        parse_dates=["night_date", "bedtime_local", "wake_time_local"],
    )


@st.cache_data(ttl=300)
def sleep_stages() -> pd.DataFrame:
    """One row per sleep-stage segment, ordered within each night."""
    return pd.read_sql(
        "SELECT night_date, stage_start_local, stage_end_local, "
        "duration_min, sleep_stage, is_asleep, source_name, "
        "stage_seq_in_night "
        "FROM analytics_marts.mart_sleep_stages "
        "ORDER BY night_date, stage_seq_in_night",
        _engine(),
        parse_dates=["night_date", "stage_start_local", "stage_end_local"],
    )
