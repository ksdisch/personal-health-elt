"""Runtime configuration: loads .env and exposes paths + DB URL."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_PATH = Path(
    os.getenv("HEALTH_EXPORT_PATH", str(PROJECT_ROOT / "data" / "raw"))
).resolve()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "health")
POSTGRES_USER = os.getenv("POSTGRES_USER", "health")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "health")

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
