"""Runtime configuration: loads .env and exposes paths + DB URL."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_PATH = Path(os.getenv("HEALTH_EXPORT_PATH", str(PROJECT_ROOT / "data" / "raw"))).resolve()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "health")
POSTGRES_USER = os.getenv("POSTGRES_USER", "health")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "health")

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)


def _maybe_float(s: str) -> float | None:
    return float(s) if s else None


# OpenWeather One Call 3.0 day_summary loader (optional).
# All three must be set for the weather loader to do anything; if any are
# missing the loader returns LoadResult(skipped=True) and weekly_load
# continues. Lat/lon are a fixed home location — single-user pipeline,
# no per-day GPS derivation.
OPENWEATHER_API_KEY: str | None = os.getenv("OPENWEATHER_API_KEY") or None
OPENWEATHER_LAT: float | None = _maybe_float(os.getenv("OPENWEATHER_LAT", ""))
OPENWEATHER_LON: float | None = _maybe_float(os.getenv("OPENWEATHER_LON", ""))

# Google Calendar secret iCal URL (optional). Found in Google Calendar
# Settings → "Settings for my calendars" → <calendar> → "Integrate
# calendar" → "Secret address in iCal format". Anyone with this URL can
# read your full calendar — store in .env, never commit it. Unset =
# calendar loader no-ops; mart_daily_context's calendar columns stay NULL.
CALENDAR_ICS_URL: str | None = os.getenv("CALENDAR_ICS_URL") or None

# Anomaly → notification pipeline.
# Rules live in YAML at the path below (default: config/notification_rules.yaml).
# Pushover transport is optional — both token and user must be set for the
# notifier to POST to the API. Either missing = stdout only. NOTIFY_DRY_RUN
# forces stdout regardless and is the test-mode toggle from the BACKLOG.
NOTIFICATION_RULES_PATH = Path(
    os.getenv("NOTIFICATION_RULES_PATH", str(PROJECT_ROOT / "config" / "notification_rules.yaml"))
).resolve()
PUSHOVER_TOKEN: str | None = os.getenv("PUSHOVER_TOKEN") or None
PUSHOVER_USER: str | None = os.getenv("PUSHOVER_USER") or None
NOTIFY_DRY_RUN: bool = os.getenv("NOTIFY_DRY_RUN", "").lower() in ("1", "true", "yes")
