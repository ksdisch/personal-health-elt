"""Unit tests for parse_quantities_csv (pure function, no DB)."""

from pathlib import Path

import pandas as pd
import pytest

from ingest.loaders.quantities import parse_quantities_csv

_SAMPLE_HEADER = "type,sourceName,sourceVersion,productType,device,startDate,endDate,unit,value\n"
_SAMPLE_ROW = (
    "HKQuantityTypeIdentifierRestingHeartRate,"
    "Kyle's Watch,26.2,Watch7,,"
    "2026-03-21 07:00:40 +0000,2026-03-22 01:17:26 +0000,"
    "count/min,70.0\n"
)


def _write_csv(tmp_path: Path, *, include_sep_hint: bool, rows: int = 1) -> Path:
    content = ""
    if include_sep_hint:
        content += "sep=,\n"
    content += _SAMPLE_HEADER
    content += _SAMPLE_ROW * rows
    path = tmp_path / "rhr.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_strips_sep_hint(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    assert len(df) == 1


def test_parse_without_sep_hint(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=False))
    assert len(df) == 1


def test_parse_renames_columns_to_snake_case(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    expected = {
        "metric_type",
        "source_name",
        "source_version",
        "product_type",
        "device",
        "start_ts",
        "end_ts",
        "unit",
        "value",
    }
    assert set(df.columns) == expected


def test_parse_timestamps_are_utc_aware(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    assert df["start_ts"].dt.tz is not None
    assert str(df["start_ts"].dt.tz) == "UTC"
    assert str(df["end_ts"].dt.tz) == "UTC"


def test_parse_values_are_float(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    assert df["value"].dtype.kind == "f"
    assert df["value"].iloc[0] == pytest.approx(70.0)


def test_parse_preserves_row_count(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True, rows=5))
    assert len(df) == 5


def test_parse_raises_on_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("type,value\nHKQuantityTypeIdentifierX,1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing expected columns"):
        parse_quantities_csv(path)


def test_parse_handles_utc_offset_format(tmp_path: Path) -> None:
    """HK timestamps look like '2026-03-21 07:00:40 +0000' — ensure parsing works."""
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    ts = df["start_ts"].iloc[0]
    assert ts.year == 2026
    assert ts.hour == 7
    assert ts.tzinfo is not None


def test_parse_returns_dataframe(tmp_path: Path) -> None:
    df = parse_quantities_csv(_write_csv(tmp_path, include_sep_hint=True))
    assert isinstance(df, pd.DataFrame)
