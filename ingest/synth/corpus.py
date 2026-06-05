"""Build a deterministic synthetic Apple-Health corpus.

The generator emits three kinds of artifacts:

* **HK CSV files** (quantities / workouts / categories) under ``out_dir`` that
  the existing ``ingest.loaders`` ingest unchanged (they dispatch on the
  ``HK*`` filename prefix and read the ``type`` column).
* **Direct-insert frames** for ``raw.weather`` and ``raw.calendar_daily`` —
  whose production loaders are credential-gated and not routed by ``batch.py``,
  so the demo flow inserts these rows straight into Postgres.

Everything is a pure function of ``(seed, scenario, start_date)``. Values carry
small seeded jitter so the data looks realistic, but the seed makes every run
byte-identical, which is what lets the golden-snapshot harness assert on mart
digests.

The corpus is anchored to fixed 2024 dates. Because that is firmly in the past,
``mart_recovery_state.is_today`` is deterministically false and
``days_since_last_workout`` is data-relative — no calendar-day drift in goldens.

Scenario → ``recovery_signal`` coverage (the ``full`` timeline stitches all):

============  ====================================================  =================
segment       how it drives the flagship mart                       recovery_signal
============  ====================================================  =================
cold_start    RHR+HRV only, no workouts -> acwr NULL / hrv-prior     insufficient_data
              NULL
baseline      steady moderate load, steady HRV                       neutral / well_recovered
spike         late load surge -> acwr > 1.5                          strained
hrv_crash     steady load (acwr <= 1.5) + HRV < 0.85x trailing       strained
steady_good   steady load (acwr in 0.8..1.3) + HRV >= 0.95x prior    well_recovered
============  ====================================================  =================
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

# --- HealthKit identifiers (the `type` column value; staging strips the prefix) ---
QTY_PREFIX = "HKQuantityTypeIdentifier"
RHR = f"{QTY_PREFIX}RestingHeartRate"
HRV = f"{QTY_PREFIX}HeartRateVariabilitySDNN"
HEART_RATE = f"{QTY_PREFIX}HeartRate"
VO2MAX = f"{QTY_PREFIX}VO2Max"
BODY_MASS = f"{QTY_PREFIX}BodyMass"

# --- Sources (drive stg_quantities source_priority: apple watch > iphone > other) ---
WATCH = {
    "source_name": "Kyle's Apple Watch",
    "source_version": "10.2",
    "product_type": "Watch7,1",
    "device": "Apple Watch",
}
PHONE = {
    "source_name": "Kyle's iPhone",
    "source_version": "17.2",
    "product_type": "iPhone16,1",
    "device": "iPhone",
}

# Fixed home location for synthetic weather (matches .env.example default).
_LAT = 41.8781
_LON = -87.6298

# HR profile -> zone placement (hr_zones.csv: Z1 110-135, Z2 136-153, Z3 154-171).
_WARMUP_BPM = 125  # zone 1
_MAIN_BPM = 145  # zone 2
_COOLDOWN_BPM = 160  # zone 3
_WARMUP_MIN = 5
_COOLDOWN_MIN = 2

SCENARIOS = ("full",)

# Planted causal effect (Phase 1 oracle): a persistent level step applied to RHR
# from a cutoff date. experiments.csv defines a matching `magnesium_glycinate`
# experiment whose interrupted-time-series should recover this KNOWN effect end
# to end through the warehouse. RHR is chosen deliberately — it does NOT feed the
# recovery_signal logic, so planting it leaves the Phase-0 branch coverage intact.
PLANTED_RHR_STEPS: tuple[tuple[date, float], ...] = ((date(2024, 2, 15), -3.0),)
_PLANTED_EXPERIMENT = "magnesium_glycinate"


def _planted_rhr_delta(day: date) -> float:
    return sum(delta for cutoff, delta in PLANTED_RHR_STEPS if day >= cutoff)


@dataclass(frozen=True)
class _DaySpec:
    """One day's synthetic plan."""

    day: date
    rhr: float
    hrv: float | None
    # cardio/strength workout: number of Zone-2 "main" minutes, or None for a rest day
    workout_main_min: int | None
    activity_type: str = "Running"
    multisource_rhr: bool = False


@dataclass
class CorpusManifest:
    """What a generation run produced."""

    csv_dir: Path
    weather: pd.DataFrame
    calendar: pd.DataFrame
    calendar_sha: str
    start_date: date
    end_date: date
    scenario: str
    n_quantity_rows: int
    n_workout_rows: int
    planted_effects: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Timestamp helpers
# --------------------------------------------------------------------------- #
def _utc(d: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A UTC datetime on calendar day ``d``.

    All synthetic stamps sit mid-day UTC (≈ morning/midday America/Chicago) so
    the staging TZ conversion never crosses a date boundary.
    """
    return datetime.combine(d, time(hour, minute, second), tzinfo=UTC)


def _iso(dt: datetime) -> str:
    """HealthKit-style ISO string, e.g. ``2024-01-15 14:00:00 +0000``."""
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


# --------------------------------------------------------------------------- #
# Day-plan construction (the `full` scenario)
# --------------------------------------------------------------------------- #
def _build_day_specs(start: date, rng: random.Random) -> list[_DaySpec]:
    """The `full` timeline: ~120 days stitching every recovery branch."""

    def jitter(scale: float) -> float:
        return rng.uniform(-scale, scale)

    specs: list[_DaySpec] = []
    idx = 0

    def add(n: int, *, rhr: float, hrv, main_min, strength_every: int = 0) -> None:
        nonlocal idx
        for k in range(n):
            d = start + timedelta(days=idx)
            is_strength = strength_every and (k % strength_every == strength_every - 1)
            specs.append(
                _DaySpec(
                    day=d,
                    rhr=round(rhr + jitter(1.0)),
                    hrv=None if hrv is None else round(hrv + jitter(2.0), 1),
                    workout_main_min=main_min,
                    activity_type="TraditionalStrengthTraining" if is_strength else "Running",
                    multisource_rhr=(idx % 17 == 5),  # a few scattered overlap days
                )
            )
            idx += 1

    # RHR is held at a FLAT baseline across all segments (only jitter varies it).
    # It does not feed recovery_signal, so a flat baseline keeps Phase-0 branch
    # coverage intact AND gives the Phase-1 causal experiments a clean series in
    # which the planted RHR step is the dominant signal (segment-driven RHR bumps
    # near the experiment cutoff would otherwise confound the interrupted-TS fit).
    rhr_base = 50
    # 1. cold_start (7d): physiology only, no workouts -> insufficient_data
    add(7, rhr=rhr_base, hrv=60, main_min=None)
    # 2. baseline (35d): steady moderate load -> neutral / well_recovered
    add(35, rhr=rhr_base, hrv=61, main_min=20, strength_every=5)
    # 3. spike (9d): load surge -> acwr > 1.5 -> strained
    add(9, rhr=rhr_base, hrv=60, main_min=65)
    # 4. post-spike + hrv_crash (20d): load back to steady; HRV craters mid-segment
    #    -> early days neutral (acwr dips <0.8), crash days strained (hrv)
    for k in range(20):
        d = start + timedelta(days=idx)
        crash = k in (9, 10)  # two deliberate HRV-crash days
        specs.append(
            _DaySpec(
                day=d,
                rhr=round(rhr_base + jitter(1.0)),
                hrv=round((42 if crash else 61) + jitter(1.5), 1),
                workout_main_min=20,
                activity_type="Running",
            )
        )
        idx += 1
    # 5. steady_good (49d): steady load + good HRV -> well_recovered
    add(49, rhr=rhr_base, hrv=63, main_min=22, strength_every=6)

    return specs


# --------------------------------------------------------------------------- #
# Row emission
# --------------------------------------------------------------------------- #
def _qty_row(
    metric: str, src: dict, start: datetime, end: datetime, unit: str, value: float
) -> dict:
    return {
        "type": metric,
        "sourceName": src["source_name"],
        "sourceVersion": src["source_version"],
        "productType": src["product_type"],
        "device": src["device"],
        "startDate": _iso(start),
        "endDate": _iso(end),
        "unit": unit,
        "value": value,
    }


def _hr_samples_for_workout(
    rows: list[dict], wstart: datetime, main_min: int
) -> tuple[datetime, float]:
    """Append per-minute in-workout HeartRate samples; return (end_ts, kcal).

    Profile: 5 min warmup (Z1) + ``main_min`` min (Z2) + 2 min (Z3). One sample
    per minute drives ``int_workout_hr_samples`` -> ``mart_workout_zones``.
    """
    minute = 0

    def emit(n: int, bpm: int) -> None:
        nonlocal minute
        for _ in range(n):
            ts = wstart + timedelta(minutes=minute)
            rows.append(_qty_row(HEART_RATE, WATCH, ts, ts, "count/min", bpm))
            minute += 1

    emit(_WARMUP_MIN, _WARMUP_BPM)
    emit(main_min, _MAIN_BPM)
    emit(_COOLDOWN_MIN, _COOLDOWN_BPM)
    total_min = _WARMUP_MIN + main_min + _COOLDOWN_MIN
    end = wstart + timedelta(minutes=total_min)
    kcal = round(total_min * 9.5, 3)  # ~9.5 kcal/min, plausible for Z2 cardio
    return end, kcal


def _weather_frame(days: list[date], rng: random.Random) -> pd.DataFrame:
    """Seasonal-ish daily weather in OpenWeather 'standard' units (Kelvin etc.)."""
    recs = []
    for d in days:
        doy = d.timetuple().tm_yday
        # winter-anchored sinusoid (coldest ~ Jan), mean ~ 284K (≈ 11°C)
        base_c = 11 + 13 * math.sin(2 * math.pi * (doy - 110) / 365)
        base_k = base_c + 273.15
        recs.append(
            {
                "obs_date": d,
                "lat": _LAT,
                "lon": _LON,
                "temp_min_k": round(base_k - 4 + rng.uniform(-1, 1), 2),
                "temp_max_k": round(base_k + 5 + rng.uniform(-1, 1), 2),
                "temp_morning_k": round(base_k - 2 + rng.uniform(-1, 1), 2),
                "temp_afternoon_k": round(base_k + 4 + rng.uniform(-1, 1), 2),
                "temp_evening_k": round(base_k + 1 + rng.uniform(-1, 1), 2),
                "temp_night_k": round(base_k - 3 + rng.uniform(-1, 1), 2),
                "humidity_afternoon": round(rng.uniform(40, 80), 1),
                "cloud_cover_afternoon": round(rng.uniform(0, 100), 1),
                "pressure_afternoon": round(rng.uniform(1005, 1025), 1),
                "precip_total_mm": round(max(0.0, rng.uniform(-3, 6)), 2),
                "wind_max_mps": round(rng.uniform(1, 9), 2),
                "wind_max_dir_deg": round(rng.uniform(0, 359), 1),
            }
        )
    return pd.DataFrame.from_records(recs)


def _calendar_frame(days: list[date], sha: str, rng: random.Random) -> pd.DataFrame:
    """Per-day calendar density. Weekdays busier than weekends."""
    recs = []
    for d in days:
        weekday = d.weekday() < 5
        n_timed = rng.randint(2, 8) if weekday else rng.randint(0, 2)
        hours = round(n_timed * rng.uniform(0.5, 1.25), 2)
        first = _utc(d, 14) if n_timed else None  # 14:00Z ≈ 08:00 local
        last = _utc(d, 22) if n_timed else None
        recs.append(
            {
                "day": d,
                "timed_event_count": n_timed,
                "timed_event_hours": hours,
                "all_day_event_count": rng.randint(0, 1),
                "first_event_local": None if first is None else first.replace(tzinfo=None),
                "last_event_local": None if last is None else last.replace(tzinfo=None),
                "source_sha256": sha,
            }
        )
    return pd.DataFrame.from_records(recs)


# --------------------------------------------------------------------------- #
# CSV writing
# --------------------------------------------------------------------------- #
_QTY_HEADER = [
    "type",
    "sourceName",
    "sourceVersion",
    "productType",
    "device",
    "startDate",
    "endDate",
    "unit",
    "value",
]
_WORKOUT_HEADER = [
    "sourceName",
    "sourceVersion",
    "productType",
    "startDate",
    "endDate",
    "activityType",
    "duration",
    "totalEnergyBurned",
    "totalDistance",
    "HKElevationAscended",
    "HKElevationDescended",
    "HKMaximumSpeed",
    "HKIndoorWorkout",
]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    """Write a HealthKit-style CSV, including the leading ``sep=,`` Excel hint
    the loaders strip — so the generator exercises that real code path."""
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("sep=,\n")
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate_corpus(
    out_dir: Path | str,
    *,
    seed: int = 0,
    scenario: str = "full",
    start_date: date = date(2024, 1, 1),
) -> CorpusManifest:
    """Generate a synthetic corpus into ``out_dir`` and return a manifest.

    Writes one CSV per quantity metric + one workouts CSV, and returns the
    weather / calendar frames for the demo flow to insert directly.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; known: {SCENARIOS}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    specs = _build_day_specs(start_date, rng)
    days = [s.day for s in specs]

    rhr_rows: list[dict] = []
    hrv_rows: list[dict] = []
    hr_rows: list[dict] = []
    vo2_rows: list[dict] = []
    mass_rows: list[dict] = []
    workout_rows: list[dict] = []

    for i, spec in enumerate(specs):
        # RHR: one value/day at 14:00Z. Optionally duplicated from the phone at
        # the same instant to exercise the source-priority dedup (watch wins).
        rhr_ts = _utc(spec.day, 14)
        rhr_val = round(spec.rhr + _planted_rhr_delta(spec.day))
        rhr_rows.append(_qty_row(RHR, WATCH, rhr_ts, rhr_ts, "count/min", rhr_val))
        if spec.multisource_rhr:
            rhr_rows.append(_qty_row(RHR, PHONE, rhr_ts, rhr_ts, "count/min", rhr_val + 3))

        # HRV: one SDNN value/day at 13:00Z (Apple samples during sleep).
        if spec.hrv is not None:
            hrv_ts = _utc(spec.day, 13)
            hrv_rows.append(_qty_row(HRV, WATCH, hrv_ts, hrv_ts, "ms", spec.hrv))

        # VO2 max ~ weekly; body mass every 3 days — feed their daily marts.
        if i % 7 == 0:
            vo2_ts = _utc(spec.day, 15)
            vo2 = round(47 + rng.uniform(-1, 1), 1)
            vo2_rows.append(_qty_row(VO2MAX, WATCH, vo2_ts, vo2_ts, "mL/min·kg", vo2))
        if i % 3 == 0:
            mass_ts = _utc(spec.day, 12)
            mass = round(75 + rng.uniform(-0.6, 0.6), 1)
            mass_rows.append(_qty_row(BODY_MASS, PHONE, mass_ts, mass_ts, "kg", mass))

        # Workout + its in-workout HR samples (drives zones -> training load).
        if spec.workout_main_min is not None:
            wstart = _utc(spec.day, 18)  # 18:00Z ≈ noon local
            wend, kcal = _hr_samples_for_workout(hr_rows, wstart, spec.workout_main_min)
            total_min = _WARMUP_MIN + spec.workout_main_min + _COOLDOWN_MIN
            workout_rows.append(
                {
                    "sourceName": WATCH["source_name"],
                    "sourceVersion": WATCH["source_version"],
                    "productType": WATCH["product_type"],
                    "startDate": _iso(wstart),
                    "endDate": _iso(wend),
                    "activityType": spec.activity_type,
                    "duration": total_min * 60,
                    "totalEnergyBurned": f"{kcal} kcal",
                    "totalDistance": f"{round(total_min * 180.0, 1)} m",
                    "HKElevationAscended": f"{rng.randint(0, 40)} m",
                    "HKElevationDescended": f"{rng.randint(0, 40)} m",
                    "HKMaximumSpeed": f"{round(rng.uniform(3.0, 5.0), 4)} m/s",
                    "HKIndoorWorkout": 0,
                }
            )

    # Write quantity CSVs (one per metric -> distinct SHA + distinct dispatch).
    _write_csv(out_dir / f"{RHR}.csv", _QTY_HEADER, rhr_rows)
    _write_csv(out_dir / f"{HRV}.csv", _QTY_HEADER, hrv_rows)
    _write_csv(out_dir / f"{HEART_RATE}.csv", _QTY_HEADER, hr_rows)
    _write_csv(out_dir / f"{VO2MAX}.csv", _QTY_HEADER, vo2_rows)
    _write_csv(out_dir / f"{BODY_MASS}.csv", _QTY_HEADER, mass_rows)
    _write_csv(out_dir / "HKWorkoutActivityTypeMixed.csv", _WORKOUT_HEADER, workout_rows)

    # Direct-insert enrichment frames.
    weather = _weather_frame(days, rng)
    calendar_sha = hashlib.sha256(f"synthetic-calendar::{scenario}::{seed}".encode()).hexdigest()
    calendar = _calendar_frame(days, calendar_sha, rng)

    n_qty = sum(len(r) for r in (rhr_rows, hrv_rows, hr_rows, vo2_rows, mass_rows))
    planted = [
        {
            "experiment": _PLANTED_EXPERIMENT,
            "metric": "rhr_bpm",
            "cutoff": str(cutoff),
            "level_change": delta,
        }
        for cutoff, delta in PLANTED_RHR_STEPS
    ]
    return CorpusManifest(
        csv_dir=out_dir,
        weather=weather,
        calendar=calendar,
        calendar_sha=calendar_sha,
        start_date=days[0],
        end_date=days[-1],
        scenario=scenario,
        n_quantity_rows=n_qty,
        n_workout_rows=len(workout_rows),
        planted_effects=planted,
    )
