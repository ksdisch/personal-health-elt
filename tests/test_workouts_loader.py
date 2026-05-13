"""Unit tests for parse_workouts_csv (pure function, no DB)."""

from pathlib import Path

import pandas as pd
import pytest

from ingest.loaders.workouts import _numeric_prefix, parse_workouts_csv

_HEADER = (
    "type,sourceName,sourceVersion,productType,device,startDate,endDate,"
    "activityType,duration,durationUnit,totalEnergyBurned,totalDistance,"
    "totalSwimmingStrokeCount,totalFlightsClimbed,HKElevationAscended,"
    "HKMaximumSpeed,HKElevationDescended,HKIndoorWorkout,"
    "WORKOUTDOORS_HEALTHKIT_DISTANCE\n"
)
_ROW_RUN = (
    'HKWorkoutTypeIdentifier,WorkOutDoors,5,"Watch7,12",somedev,'
    "2026-03-26 16:25:52 +0000,2026-03-26 17:20:07 +0000,"
    "Running,3255.45,sec,659.283 kcal,9688.1 m,,,"
    "8 m,4.82924 m/s,26 m,0,\n"
)
_ROW_INDOOR_YOGA = (
    'HKWorkoutTypeIdentifier,Health,26.2,"iPhone17,1",,'
    "2026-03-20 13:00:00 +0000,2026-03-20 13:45:00 +0000,"
    "Yoga,2700,sec,,,,,,,,1,\n"
)


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "workout.csv"
    content = "sep=,\n" + _HEADER + "".join(rows)
    path.write_text(content, encoding="utf-8")
    return path


def test_numeric_prefix_parses_common_patterns() -> None:
    assert _numeric_prefix("659.283 kcal") == pytest.approx(659.283)
    assert _numeric_prefix("9688.1 m") == pytest.approx(9688.1)
    assert _numeric_prefix("4.82924 m/s") == pytest.approx(4.82924)
    assert _numeric_prefix("-1.5 m") == pytest.approx(-1.5)
    assert _numeric_prefix("8 m") == 8.0


def test_numeric_prefix_returns_none_for_missing() -> None:
    assert _numeric_prefix(None) is None
    assert _numeric_prefix(float("nan")) is None


def test_numeric_prefix_returns_none_for_garbage() -> None:
    assert _numeric_prefix("n/a") is None
    assert _numeric_prefix("") is None


def test_parse_renames_columns_to_snake_case(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_RUN]))
    required = {
        "activity_type",
        "source_name",
        "source_version",
        "product_type",
        "start_ts",
        "end_ts",
        "duration_sec",
        "total_energy_kcal",
        "total_distance_m",
        "elevation_asc_m",
        "elevation_desc_m",
        "max_speed_mps",
        "indoor",
    }
    assert required.issubset(set(df.columns))


def test_parse_strips_units_from_embedded_fields(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_RUN]))
    row = df.iloc[0]
    assert row["total_energy_kcal"] == pytest.approx(659.283)
    assert row["total_distance_m"] == pytest.approx(9688.1)
    assert row["elevation_asc_m"] == 8.0
    assert row["elevation_desc_m"] == 26.0
    assert row["max_speed_mps"] == pytest.approx(4.82924)


def test_parse_activity_type_and_duration(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_RUN]))
    row = df.iloc[0]
    assert row["activity_type"] == "Running"
    assert row["duration_sec"] == pytest.approx(3255.45)


def test_parse_timestamps_are_utc_aware(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_RUN]))
    assert str(df["start_ts"].dt.tz) == "UTC"
    assert str(df["end_ts"].dt.tz) == "UTC"


def test_parse_indoor_boolean_coercion(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_RUN, _ROW_INDOOR_YOGA]))
    # Allow numpy bool scalars here — pandas promotes object columns of
    # bool/None; SQLAlchemy serializes either to Postgres boolean fine.
    assert bool(df.iloc[0]["indoor"]) is False
    assert bool(df.iloc[1]["indoor"]) is True


def test_parse_missing_fields_become_null(tmp_path: Path) -> None:
    df = parse_workouts_csv(_write_csv(tmp_path, [_ROW_INDOOR_YOGA]))
    row = df.iloc[0]
    # Yoga has no distance, no energy burned, no elevation, no speed.
    assert pd.isna(row["total_distance_m"])
    assert pd.isna(row["total_energy_kcal"])
    assert pd.isna(row["elevation_asc_m"])
    assert pd.isna(row["max_speed_mps"])


def test_parse_empty_file_returns_empty_df(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("sep=,\n" + _HEADER, encoding="utf-8")
    df = parse_workouts_csv(path)
    assert df.empty


def test_parse_tolerates_missing_source_columns(tmp_path: Path) -> None:
    """Not every workout CSV has every column — e.g. some older exports
    lack HKMaximumSpeed. parse should set those to NaN, not crash."""
    path = tmp_path / "sparse.csv"
    path.write_text(
        "sep=,\n"
        "type,sourceName,startDate,endDate,activityType,duration\n"
        "HKWorkoutTypeIdentifier,Watch,"
        "2026-03-26 16:25:52 +0000,2026-03-26 17:20:07 +0000,"
        "Running,3255.45\n",
        encoding="utf-8",
    )
    df = parse_workouts_csv(path)
    assert len(df) == 1
    assert df.iloc[0]["activity_type"] == "Running"
    assert pd.isna(df.iloc[0]["total_distance_m"])
    assert pd.isna(df.iloc[0]["max_speed_mps"])
