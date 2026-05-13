"""Unit tests for the weekly_load flow's failure-path behavior.

Targets `run_dbt_build`'s subprocess wrapping + error semantics. The
test bypasses Prefect's retry machinery by calling the underlying
function via `.fn` — what we want to verify is the contract (raise on
non-zero, log stderr tail), not Prefect's retry implementation.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

import pytest

from ingest.flows.weekly_load import DbtBuildError, run_dbt_build


def _fake_completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["uv", "run", "dbt", "build"],
        returncode=returncode,
        stdout="",
        stderr=stderr,
    )


def test_run_dbt_build_returns_zero_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: dbt exits 0 → task returns 0, no exception."""

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        return _fake_completed(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_dbt_build.fn() == 0


def test_run_dbt_build_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero exit → DbtBuildError with the exit code in the message.

    Prefect's @task(retries=2, retry_delay_seconds=60) decorator wraps
    this raise: the actual flow run will retry twice before giving up.
    Here we test the raise itself, not the retry behavior.
    """

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        return _fake_completed(returncode=2, stderr="dbt did the thing wrong\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(DbtBuildError, match=r"rc=2"):
        run_dbt_build.fn()


def test_run_dbt_build_logs_stderr_tail_on_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """On failure the ERROR log includes the tail of dbt stderr so
    the alert is actionable without dumping a full stack trace."""
    stderr = "\n".join(f"line {i}" for i in range(1, 31)) + "\n"

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        return _fake_completed(returncode=1, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.ERROR, logger="prefect"), pytest.raises(DbtBuildError):
        run_dbt_build.fn()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "expected an ERROR log from the failure path"
    joined = "\n".join(r.getMessage() for r in error_records)
    # Tail is last 20 lines; lines 11..30 should appear, lines 1..10 should not.
    assert "line 30" in joined
    assert "line 11" in joined
    assert "line 10" not in joined


def test_run_dbt_build_handles_empty_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero exit with empty stderr still raises and doesn't blow up
    on a missing-tail substitution."""

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        return _fake_completed(returncode=3, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(DbtBuildError, match=r"rc=3"):
        run_dbt_build.fn()
