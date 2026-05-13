"""Unit tests for the OpenWeather day_summary loader.

Pure-function tests for `payload_to_row` plus injection-based tests for
`load_weather_daily` that bypass the real HTTP fetch via the
`fetch_fn=` parameter. No network. No Postgres required for the
no-key-configured path; integration paths skip when Postgres is
unreachable (via the shared `pg_engine` fixture).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.loaders.weather_openweather import (
    load_weather_daily,
    payload_to_row,
)

# Sentinel coordinates chosen far outside any realistic user location so
# integration test rows can be cleaned up surgically (and never collide
# with a real configured lat/lon).
_TEST_LAT = 89.0
_TEST_LON = -179.0

# A canonical day_summary payload — temperatures in K, the rest in the
# API's "standard" units. Used as a baseline; tests mutate copies.
_SAMPLE_PAYLOAD: dict[str, Any] = {
    "lat": _TEST_LAT,
    "lon": _TEST_LON,
    "tz": "+00:00",
    "date": "2099-03-21",
    "units": "standard",
    "cloud_cover": {"afternoon": 12.5},
    "humidity": {"afternoon": 48.0},
    "precipitation": {"total": 0.0},
    "temperature": {
        "min": 280.15,
        "max": 290.15,
        "morning": 282.0,
        "afternoon": 289.5,
        "evening": 286.0,
        "night": 281.0,
    },
    "pressure": {"afternoon": 1020.0},
    "wind": {"max": {"speed": 4.5, "direction": 270.0}},
}


def test_payload_to_row_maps_every_column() -> None:
    row = payload_to_row(_SAMPLE_PAYLOAD, _TEST_LAT, _TEST_LON)
    assert row["obs_date"] == date(2099, 3, 21)
    assert row["lat"] == _TEST_LAT
    assert row["lon"] == _TEST_LON
    assert row["temp_min_k"] == 280.15
    assert row["temp_max_k"] == 290.15
    assert row["temp_morning_k"] == 282.0
    assert row["temp_afternoon_k"] == 289.5
    assert row["temp_evening_k"] == 286.0
    assert row["temp_night_k"] == 281.0
    assert row["humidity_afternoon"] == 48.0
    assert row["cloud_cover_afternoon"] == 12.5
    assert row["pressure_afternoon"] == 1020.0
    assert row["precip_total_mm"] == 0.0
    assert row["wind_max_mps"] == 4.5
    assert row["wind_max_dir_deg"] == 270.0


def test_payload_to_row_tolerates_missing_sub_objects() -> None:
    """OpenWeather omits keys when a reading isn't available; tolerate that."""
    minimal = {"date": "2099-03-21"}
    row = payload_to_row(minimal, _TEST_LAT, _TEST_LON)
    assert row["obs_date"] == date(2099, 3, 21)
    assert row["temp_min_k"] is None
    assert row["humidity_afternoon"] is None
    assert row["wind_max_mps"] is None


def test_load_weather_daily_skips_when_no_api_key() -> None:
    """No key configured → no HTTP, no DB writes, skipped=True."""

    def _should_not_be_called(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fetch_fn called even though api_key was None")

    result = load_weather_daily(
        date(2099, 3, 21),
        date(2099, 3, 22),
        api_key=None,
        lat=_TEST_LAT,
        lon=_TEST_LON,
        fetch_fn=_should_not_be_called,
    )
    assert result.skipped is True
    assert result.rows_inserted == 0
    assert result.days_fetched == 0


def test_load_weather_daily_skips_when_no_coords() -> None:
    """Key but no coords → also skipped."""

    def _should_not_be_called(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fetch_fn called even though lat/lon were None")

    result = load_weather_daily(
        date(2099, 3, 21),
        date(2099, 3, 22),
        api_key="present",
        lat=None,
        lon=None,
        fetch_fn=_should_not_be_called,
    )
    assert result.skipped is True


def test_load_weather_daily_fetches_only_missing_dates(pg_engine: Engine) -> None:
    """Pre-seed one of three dates; loader should fetch only the other two."""
    engine = pg_engine
    pre_loaded = date(2099, 3, 22)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw.weather (obs_date, lat, lon, temp_min_k) "
                    "VALUES (:d, :lat, :lon, :tmin)"
                ),
                {"d": pre_loaded, "lat": _TEST_LAT, "lon": _TEST_LON, "tmin": 270.0},
            )

        calls: list[date] = []

        def _fake_fetch(d: date, lat: float, lon: float, _key: str) -> dict[str, Any]:
            calls.append(d)
            return {**_SAMPLE_PAYLOAD, "date": d.isoformat(), "lat": lat, "lon": lon}

        result = load_weather_daily(
            date(2099, 3, 21),
            date(2099, 3, 23),
            api_key="fake-key",
            lat=_TEST_LAT,
            lon=_TEST_LON,
            engine=engine,
            fetch_fn=_fake_fetch,
        )

        assert sorted(calls) == [date(2099, 3, 21), date(2099, 3, 23)]
        assert result.days_fetched == 2
        assert result.days_already_present == 1
        assert result.rows_inserted == 2
        assert result.skipped is False

    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM raw.weather WHERE lat = :lat AND lon = :lon"),
                {"lat": _TEST_LAT, "lon": _TEST_LON},
            )


def test_load_weather_daily_rerun_is_noop(pg_engine: Engine) -> None:
    """Second invocation over the same range fetches zero new days."""
    engine = pg_engine

    def _fake_fetch(d: date, lat: float, lon: float, _key: str) -> dict[str, Any]:
        return {**_SAMPLE_PAYLOAD, "date": d.isoformat(), "lat": lat, "lon": lon}

    try:
        first = load_weather_daily(
            date(2099, 4, 1),
            date(2099, 4, 2),
            api_key="fake-key",
            lat=_TEST_LAT,
            lon=_TEST_LON,
            engine=engine,
            fetch_fn=_fake_fetch,
        )
        assert first.rows_inserted == 2

        # Sentinel: fetch_fn must NOT be called on the second run.
        def _should_not_be_called(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("fetch_fn called for an already-loaded date")

        second = load_weather_daily(
            date(2099, 4, 1),
            date(2099, 4, 2),
            api_key="fake-key",
            lat=_TEST_LAT,
            lon=_TEST_LON,
            engine=engine,
            fetch_fn=_should_not_be_called,
        )
        assert second.rows_inserted == 0
        assert second.days_fetched == 0
        assert second.days_already_present == 2
        assert second.skipped is False

    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM raw.weather WHERE lat = :lat AND lon = :lon"),
                {"lat": _TEST_LAT, "lon": _TEST_LON},
            )


@pytest.mark.parametrize(
    "missing_key",
    ["temperature", "humidity", "wind", "precipitation"],
)
def test_payload_to_row_handles_individual_missing_groups(missing_key: str) -> None:
    """Drop one sub-object at a time; nothing raises, missing values become None."""
    p = dict(_SAMPLE_PAYLOAD)
    p.pop(missing_key, None)
    row = payload_to_row(p, _TEST_LAT, _TEST_LON)
    # Spot-check: obs_date always present, lat/lon always set, no exception.
    assert row["obs_date"] == date(2099, 3, 21)
    assert row["lat"] == _TEST_LAT
    assert row["lon"] == _TEST_LON
