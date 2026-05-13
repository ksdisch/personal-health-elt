"""Unit tests for the batch loader — DB-free via loader injection."""

from pathlib import Path

import pytest

from ingest.loaders.batch import (
    BatchResult,
    dispatch,
    load_folder,
    metric_type_from_path,
)
from ingest.loaders.quantities import LoadResult


def test_dispatch_recognizes_quantity_prefix(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "HKQuantityTypeIdentifierHeartRate_x.csv") == "quantities"


def test_dispatch_recognizes_category_prefix(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "HKCategoryTypeIdentifierSleepAnalysis_x.csv") == "categories"


def test_dispatch_returns_none_for_unknown(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "random.csv") is None
    assert dispatch(tmp_path / "workouts.csv") is None


def test_load_folder_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_folder(tmp_path / "does-not-exist")


def _fake_ok_loader(calls: list[Path]):
    def _load(path: Path, engine=None) -> LoadResult:
        calls.append(path)
        return LoadResult(path=path, sha256="abc", rows_read=10, rows_inserted=10, skipped=False)

    return _load


def test_load_folder_dispatches_to_correct_loaders(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierHeartRate_a.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierRestingHeartRate_b.csv").write_text("hdr\n")
    (tmp_path / "HKCategoryTypeIdentifierSleep_c.csv").write_text("hdr\n")
    (tmp_path / "other.csv").write_text("hdr\n")

    q_calls: list[Path] = []
    c_calls: list[Path] = []
    result = load_folder(
        tmp_path,
        quantities_loader=_fake_ok_loader(q_calls),
        categories_loader=_fake_ok_loader(c_calls),
    )

    assert {p.name for p in q_calls} == {
        "HKQuantityTypeIdentifierHeartRate_a.csv",
        "HKQuantityTypeIdentifierRestingHeartRate_b.csv",
    }
    assert {p.name for p in c_calls} == {"HKCategoryTypeIdentifierSleep_c.csv"}
    assert len(result.loaded) == 3
    assert len(result.skipped) == 1  # only the unrecognized "other.csv"
    assert result.total_rows_inserted == 30


def test_load_folder_walks_subdirectories(tmp_path: Path) -> None:
    sub = tmp_path / "nested" / "deep"
    sub.mkdir(parents=True)
    (sub / "HKQuantityTypeIdentifierVO2Max_x.csv").write_text("hdr\n")

    calls: list[Path] = []
    result = load_folder(tmp_path, quantities_loader=_fake_ok_loader(calls))

    assert len(calls) == 1
    assert calls[0].name == "HKQuantityTypeIdentifierVO2Max_x.csv"
    assert len(result.loaded) == 1


def test_load_folder_continues_past_errors(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierGood_a.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierBad_b.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierGood_c.csv").write_text("hdr\n")

    def flaky(path: Path, engine=None) -> LoadResult:
        if "Bad" in path.name:
            raise RuntimeError("boom")
        return LoadResult(path=path, sha256="x", rows_read=1, rows_inserted=1, skipped=False)

    result = load_folder(tmp_path, quantities_loader=flaky)

    assert len(result.loaded) == 2
    assert len(result.errors) == 1
    assert result.errors[0][0].name == "HKQuantityTypeIdentifierBad_b.csv"
    assert isinstance(result.errors[0][1], RuntimeError)


def test_batch_result_counts(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierA_x.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierB_x.csv").write_text("hdr\n")

    def mixed(path: Path, engine=None) -> LoadResult:
        # First one is "already loaded", second is new.
        skipped = "A_x" in path.name
        return LoadResult(
            path=path,
            sha256="y",
            rows_read=0 if skipped else 5,
            rows_inserted=0 if skipped else 5,
            skipped=skipped,
        )

    result = load_folder(tmp_path, quantities_loader=mixed)
    assert result.files_loaded == 1
    assert result.files_already_loaded == 1
    assert result.total_rows_inserted == 5


# ---- per-metric observability ---------------------------------------------


def test_metric_type_strips_quantity_prefix(tmp_path: Path) -> None:
    p = tmp_path / "HKQuantityTypeIdentifierRestingHeartRate.csv"
    assert metric_type_from_path(p) == "RestingHeartRate"


def test_metric_type_strips_category_prefix(tmp_path: Path) -> None:
    p = tmp_path / "HKCategoryTypeIdentifierSleepAnalysis.csv"
    assert metric_type_from_path(p) == "SleepAnalysis"


def test_metric_type_strips_workout_prefix(tmp_path: Path) -> None:
    p = tmp_path / "HKWorkoutActivityTypeRunning.csv"
    assert metric_type_from_path(p) == "Running"


def test_metric_type_returns_unknown_for_unrecognized(tmp_path: Path) -> None:
    assert metric_type_from_path(tmp_path / "random.csv") == "unknown"


def test_per_kind_summary_buckets_loaded_files(tmp_path: Path) -> None:
    """BatchResult.per_kind_summary aggregates by loader kind, including the
    per-kind rows_inserted total — the new signal we want for partial-failure
    diagnosis."""
    result = BatchResult(folder=tmp_path)
    result.loaded = [
        LoadResult(
            path=tmp_path / "HKQuantityTypeIdentifierA.csv",
            sha256="a",
            rows_read=10,
            rows_inserted=10,
            skipped=False,
        ),
        LoadResult(
            path=tmp_path / "HKQuantityTypeIdentifierB.csv",
            sha256="b",
            rows_read=0,
            rows_inserted=0,
            skipped=True,
        ),
        LoadResult(
            path=tmp_path / "HKCategoryTypeIdentifierSleep.csv",
            sha256="c",
            rows_read=5,
            rows_inserted=5,
            skipped=False,
        ),
    ]
    summary = result.per_kind_summary()
    assert summary["quantities"]["files_loaded"] == 1
    assert summary["quantities"]["files_already_loaded"] == 1
    assert summary["quantities"]["rows_inserted"] == 10
    assert summary["categories"]["files_loaded"] == 1
    assert summary["categories"]["rows_inserted"] == 5
    # workouts has no activity → omitted from output, never zero-padded.
    assert "workouts" not in summary


def test_per_kind_summary_counts_errors(tmp_path: Path) -> None:
    result = BatchResult(folder=tmp_path)
    result.errors = [
        (tmp_path / "HKQuantityTypeIdentifierBoom.csv", RuntimeError("boom")),
        (tmp_path / "HKCategoryTypeIdentifierSplat.csv", ValueError("splat")),
    ]
    summary = result.per_kind_summary()
    assert summary["quantities"]["files_errored"] == 1
    assert summary["categories"]["files_errored"] == 1


def test_errored_metric_types_lists_each_failure(tmp_path: Path) -> None:
    """The per-failure list is what an operator reads first to find the
    bad file — it carries the metric name, the kind, the path, the
    error type, and a truncated message."""
    result = BatchResult(folder=tmp_path)
    result.errors = [
        (
            tmp_path / "HKQuantityTypeIdentifierHeartRate.csv",
            RuntimeError("boom"),
        ),
    ]
    [entry] = result.errored_metric_types()
    assert entry["metric_type"] == "HeartRate"
    assert entry["kind"] == "quantities"
    assert entry["error_type"] == "RuntimeError"
    assert entry["error_msg"] == "boom"


def test_errored_metric_types_truncates_long_messages(tmp_path: Path) -> None:
    """A runaway stack trace can't drown the structured log."""
    long_message = "x" * 500
    result = BatchResult(folder=tmp_path)
    result.errors = [
        (tmp_path / "HKQuantityTypeIdentifierA.csv", RuntimeError(long_message)),
    ]
    [entry] = result.errored_metric_types()
    assert len(entry["error_msg"]) == 200


def test_per_metric_type_summary_sorts_by_filename(tmp_path: Path) -> None:
    """Output is sorted for stable logs."""
    result = BatchResult(folder=tmp_path)
    result.loaded = [
        LoadResult(
            path=tmp_path / "HKQuantityTypeIdentifierZ.csv",
            sha256="z",
            rows_read=1,
            rows_inserted=1,
            skipped=False,
        ),
        LoadResult(
            path=tmp_path / "HKQuantityTypeIdentifierA.csv",
            sha256="a",
            rows_read=2,
            rows_inserted=2,
            skipped=False,
        ),
    ]
    rows = result.per_metric_type_summary()
    assert [r["metric_type"] for r in rows] == ["A", "Z"]


def test_format_summary_table_handles_empty_result(tmp_path: Path) -> None:
    """No-op runs should still produce a readable line, not a blank string."""
    result = BatchResult(folder=tmp_path)
    assert "no files processed" in result.format_summary_table()


def test_format_summary_table_renders_known_kinds(tmp_path: Path) -> None:
    result = BatchResult(folder=tmp_path)
    result.loaded = [
        LoadResult(
            path=tmp_path / "HKQuantityTypeIdentifierA.csv",
            sha256="a",
            rows_read=3,
            rows_inserted=3,
            skipped=False,
        ),
    ]
    table = result.format_summary_table()
    assert "quantities" in table
    assert "3" in table
