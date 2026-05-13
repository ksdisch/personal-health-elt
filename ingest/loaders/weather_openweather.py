"""OpenWeather One Call 3.0 daily-summary loader.

Pulls per-day weather summaries (temp min/max, humidity, cloud cover,
precipitation, wind) for a fixed lat/lon from the
``/data/3.0/onecall/day_summary`` endpoint. Used by the cross-source
enrichment family: weather joins the daily context mart and downstream
correlation analysis ("does my recovery score drop on hot nights?").

Idempotency contract differs from the file-based loaders. The natural
key is (obs_date, lat, lon); ``ON CONFLICT DO NOTHING`` keeps re-runs
idempotent. There is no SHA file ledger — this is an API source, not a
file source — so ``raw.file_inventory`` is not touched.

Optional source. If ``OPENWEATHER_API_KEY`` (or lat/lon) is unset the
loader returns ``WeatherLoadResult(skipped=True)`` without making any
HTTP calls, so the weekly_load flow can include it unconditionally.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ingest.config import OPENWEATHER_API_KEY, OPENWEATHER_LAT, OPENWEATHER_LON
from ingest.db import get_engine
from ingest.loaders._idempotency import upsert_rows

logger = logging.getLogger(__name__)

OPENWEATHER_DAY_SUMMARY_URL = "https://api.openweathermap.org/data/3.0/onecall/day_summary"
_HTTP_TIMEOUT_SEC = 30

FetchFn = Callable[[date, float, float, str], dict[str, Any]]


@dataclass(frozen=True)
class WeatherLoadResult:
    rows_read: int
    rows_inserted: int
    days_fetched: int
    days_already_present: int
    skipped: bool  # entire run skipped (no API key / coords configured)


def _fetch_day(d: date, lat: float, lon: float, api_key: str) -> dict[str, Any]:
    """One HTTP GET against the OpenWeather day_summary endpoint."""
    qs = urlencode({"lat": lat, "lon": lon, "date": d.isoformat(), "appid": api_key})
    url = f"{OPENWEATHER_DAY_SUMMARY_URL}?{qs}"
    req = Request(url, headers={"User-Agent": "personal-health-elt/0.1"})
    with urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 (constant https URL)
        payload = json.loads(resp.read())
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected response shape for {d}: {type(payload).__name__}")
    return payload


def payload_to_row(payload: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    """Flatten one day_summary response into a raw.weather row dict.

    Tolerant of missing sub-objects — OpenWeather omits keys when no
    reading is available rather than emitting nulls, so each accessor
    falls back to {} before .get().
    """
    t = payload.get("temperature") or {}
    h = payload.get("humidity") or {}
    c = payload.get("cloud_cover") or {}
    p = payload.get("pressure") or {}
    pr = payload.get("precipitation") or {}
    w_max = (payload.get("wind") or {}).get("max") or {}
    return {
        "obs_date": date.fromisoformat(payload["date"]),
        "lat": lat,
        "lon": lon,
        "temp_min_k": t.get("min"),
        "temp_max_k": t.get("max"),
        "temp_morning_k": t.get("morning"),
        "temp_afternoon_k": t.get("afternoon"),
        "temp_evening_k": t.get("evening"),
        "temp_night_k": t.get("night"),
        "humidity_afternoon": h.get("afternoon"),
        "cloud_cover_afternoon": c.get("afternoon"),
        "pressure_afternoon": p.get("afternoon"),
        "precip_total_mm": pr.get("total"),
        "wind_max_mps": w_max.get("speed"),
        "wind_max_dir_deg": w_max.get("direction"),
    }


def _dates_missing(engine: Engine, start: date, end: date, lat: float, lon: float) -> list[date]:
    """Dates in [start, end] inclusive not already in raw.weather for this (lat, lon)."""
    with engine.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT obs_date FROM raw.weather "
                    "WHERE lat = :lat AND lon = :lon "
                    "AND obs_date BETWEEN :start AND :end"
                ),
                {"lat": lat, "lon": lon, "start": start, "end": end},
            )
        }
    missing: list[date] = []
    d = start
    while d <= end:
        if d not in existing:
            missing.append(d)
        d = d + timedelta(days=1)
    return missing


def load_weather_daily(
    start_date: date,
    end_date: date,
    *,
    api_key: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    engine: Engine | None = None,
    fetch_fn: FetchFn | None = None,
) -> WeatherLoadResult:
    """Backfill daily weather summaries for [start_date, end_date] inclusive.

    Queries the DB first for dates already present at (lat, lon) and only
    calls the API for the gaps. One HTTP call per missing date. Inserts
    via ON CONFLICT DO NOTHING on the natural key, so a concurrent run
    or a re-execution after a partial failure is safe.

    Returns ``WeatherLoadResult(skipped=True)`` and makes no HTTP calls
    when any of ``api_key`` / ``lat`` / ``lon`` is missing (config-less
    portfolio clones). The weekly_load flow includes the weather task
    unconditionally; absent config = silent no-op.

    ``fetch_fn`` is injected for tests so the unit suite can validate
    end-to-end behavior without real HTTP.
    """
    api_key = api_key if api_key is not None else OPENWEATHER_API_KEY
    lat = lat if lat is not None else OPENWEATHER_LAT
    lon = lon if lon is not None else OPENWEATHER_LON

    if not api_key or lat is None or lon is None:
        logger.info("weather: no API key / coords configured, skipping")
        return WeatherLoadResult(
            rows_read=0,
            rows_inserted=0,
            days_fetched=0,
            days_already_present=0,
            skipped=True,
        )

    engine = engine or get_engine()
    fetch = fetch_fn or _fetch_day

    missing = _dates_missing(engine, start_date, end_date, lat, lon)
    total_days = (end_date - start_date).days + 1
    already_present = total_days - len(missing)
    if not missing:
        logger.info("weather: %d dates in range, all already loaded", total_days)
        return WeatherLoadResult(
            rows_read=0,
            rows_inserted=0,
            days_fetched=0,
            days_already_present=already_present,
            skipped=False,
        )

    rows = [payload_to_row(fetch(d, lat, lon, api_key), lat, lon) for d in missing]
    df = pd.DataFrame(rows)

    with engine.begin() as conn:
        inserted = upsert_rows(
            conn,
            df,
            table="weather",
            index_elements=["obs_date", "lat", "lon"],
        )

    logger.info(
        "weather: fetched %d days, inserted %d, %d already present",
        len(missing),
        inserted,
        already_present,
    )
    return WeatherLoadResult(
        rows_read=len(df),
        rows_inserted=inserted,
        days_fetched=len(missing),
        days_already_present=already_present,
        skipped=False,
    )


def _main() -> None:
    """CLI: backfill the trailing N days, default 14.

    Usage:
        uv run python -m ingest.loaders.weather_openweather [days]
    """
    import sys

    days = int(sys.argv[1]) if len(sys.argv) >= 2 else 14
    end = date.today() - timedelta(days=1)  # API day_summary is for past dates
    start = end - timedelta(days=days - 1)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_weather_daily(start, end)
    if result.skipped:
        print("status:    SKIPPED (OPENWEATHER_API_KEY / LAT / LON not configured)")
        return
    print(f"range:     {start} .. {end}")
    print(f"fetched:   {result.days_fetched}")
    print(f"already:   {result.days_already_present}")
    print(f"inserted:  {result.rows_inserted}")


if __name__ == "__main__":
    _main()
