"""Notification transports — stdout (always) and Pushover (optional).

Each transport is a pure function taking a Trigger plus its credentials.
The orchestrator (`notify.py`) decides which transports to invoke based
on what's configured; transports don't read env or config themselves so
they stay easy to unit-test by direct call.

Pushover was chosen over Slack / email because the BACKLOG entry frames
the feature as an *interruption*: the value is realized when the user's
phone rings, not when they happen to glance at a laptop later. Pushover
is one POST against an HTTPS endpoint, no OAuth dance, free tier covers
~7500 notifications/month. Stdlib `urllib` only — no new top-level dep.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ingest.notifications.rules import Trigger

logger = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
_HTTP_TIMEOUT_SEC = 10

# Pushover priority levels:
#   -2 silent, -1 quiet, 0 normal, 1 high (bypass quiet hours), 2 emergency
# `critical` maps to 1 so the user is interrupted even at night; everything
# else stays at 0 so the phone respects do-not-disturb.
_PRIORITY_BY_SEVERITY: dict[str, int] = {
    "info": 0,
    "warning": 0,
    "critical": 1,
}


class PushoverError(RuntimeError):
    """Raised when the Pushover API returns a non-success response."""


def send_stdout(trigger: Trigger) -> None:
    """Print one notification line to stdout. Always succeeds."""
    print(
        f"[NOTIFY {trigger.severity.upper()}] {trigger.rule_name} ({trigger.day}): "
        f"{trigger.message}"
    )


def send_pushover(trigger: Trigger, token: str, user: str) -> dict[str, Any]:
    """POST one notification to Pushover. Raises PushoverError on failure.

    Returns the parsed JSON response on success (useful for tests that
    want to assert request/response shape without re-implementing the
    transport).
    """
    priority = _PRIORITY_BY_SEVERITY.get(trigger.severity, 0)
    data = urlencode(
        {
            "token": token,
            "user": user,
            "title": f"Health · {trigger.severity}",
            "message": trigger.message,
            "priority": priority,
        }
    ).encode("utf-8")
    req = Request(PUSHOVER_API_URL, data=data, method="POST")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 (constant https URL)
            body = resp.read()
    except Exception as exc:
        raise PushoverError(f"HTTP request to Pushover failed: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PushoverError(f"Pushover returned non-JSON body: {body!r}") from exc
    if not isinstance(parsed, dict) or parsed.get("status") != 1:
        raise PushoverError(f"Pushover API error: {parsed}")
    return parsed
