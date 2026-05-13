"""Unit tests for the notification transports.

`send_stdout` is exercised via capsys. `send_pushover` is exercised by
monkeypatching `urlopen` so no real HTTP fires — the network is forbidden
here on purpose (CI sandboxes block egress, and a flaky external API
shouldn't break this suite).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from ingest.notifications import transport as transport_mod
from ingest.notifications.rules import Trigger
from ingest.notifications.transport import (
    PushoverError,
    send_pushover,
    send_stdout,
)

_TRIGGER = Trigger(
    rule_name="red_transition",
    day=date(2026, 5, 13),
    severity="warning",
    signal="strained",
    message="HRV 42ms, ACWR 1.67",
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def test_send_stdout_prints_severity_and_message(capsys: pytest.CaptureFixture[str]) -> None:
    send_stdout(_TRIGGER)
    out = capsys.readouterr().out
    assert "[NOTIFY WARNING]" in out
    assert "red_transition" in out
    assert "2026-05-13" in out
    assert "HRV 42ms, ACWR 1.67" in out


def test_send_pushover_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["data"] = req.data.decode("utf-8")
        captured["method"] = req.get_method()
        return _FakeResponse(b'{"status":1,"request":"abc"}')

    monkeypatch.setattr(transport_mod, "urlopen", fake_urlopen)

    result = send_pushover(_TRIGGER, token="tok_xyz", user="user_abc")
    assert result == {"status": 1, "request": "abc"}
    assert captured["url"] == transport_mod.PUSHOVER_API_URL
    assert captured["method"] == "POST"
    # urlencoded body, order isn't guaranteed — assert each kv pair appears.
    body = captured["data"]
    assert "token=tok_xyz" in body
    assert "user=user_abc" in body
    assert "priority=0" in body  # severity=warning maps to priority 0
    assert "Health" in body  # title


def test_send_pushover_uses_priority_1_for_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    crit = Trigger(
        rule_name="three_strained_days",
        day=date(2026, 5, 13),
        severity="critical",
        signal="strained",
        message="3rd strained day",
    )
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        captured["data"] = req.data.decode("utf-8")
        return _FakeResponse(b'{"status":1}')

    monkeypatch.setattr(transport_mod, "urlopen", fake_urlopen)
    send_pushover(crit, token="t", user="u")
    assert "priority=1" in captured["data"]


def test_send_pushover_raises_on_non_success_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        return _FakeResponse(json.dumps({"status": 0, "errors": ["user invalid"]}).encode())

    monkeypatch.setattr(transport_mod, "urlopen", fake_urlopen)
    with pytest.raises(PushoverError, match="user invalid"):
        send_pushover(_TRIGGER, token="t", user="u")


def test_send_pushover_raises_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        raise TimeoutError("api timeout")

    monkeypatch.setattr(transport_mod, "urlopen", fake_urlopen)
    with pytest.raises(PushoverError, match="HTTP request to Pushover failed"):
        send_pushover(_TRIGGER, token="t", user="u")


def test_send_pushover_raises_on_non_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"<html>oops</html>")

    monkeypatch.setattr(transport_mod, "urlopen", fake_urlopen)
    with pytest.raises(PushoverError, match="non-JSON body"):
        send_pushover(_TRIGGER, token="t", user="u")
