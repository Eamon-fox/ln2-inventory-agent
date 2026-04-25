"""Best-effort user feedback submission for the settings dialog."""

from __future__ import annotations

import json
import logging
import platform
import urllib.error
import urllib.request

FEEDBACK_ENDPOINT_URL = "https://snowfox.bio/feedback.php"
FEEDBACK_TIMEOUT_SECONDS = 5.0
FEEDBACK_MAX_MESSAGE_LENGTH = 4000

_LOGGER = logging.getLogger(__name__)


def _normalize_feedback_message(message: object) -> str:
    text = str(message or "").strip()
    return text[:FEEDBACK_MAX_MESSAGE_LENGTH]


def _platform_payload() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


def post_feedback(
    message: object,
    *,
    endpoint: str = FEEDBACK_ENDPOINT_URL,
    timeout: float = FEEDBACK_TIMEOUT_SECONDS,
    app_version: object = "",
    language: object = "",
) -> dict[str, object]:
    """Submit feedback synchronously and return a compact result dict."""

    normalized_message = _normalize_feedback_message(message)
    if not normalized_message:
        return {"ok": False, "error_code": "empty_message"}

    payload = {
        "message": normalized_message,
        "app": "SnowFox",
        "version": str(app_version or "").strip(),
        "language": str(language or "").strip(),
        "platform": _platform_payload(),
    }
    request = urllib.request.Request(
        str(endpoint),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SnowFox",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8192)
    except urllib.error.HTTPError as exc:
        raw = exc.read(8192)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except Exception:
            decoded = {}
        error_code = decoded.get("error") if isinstance(decoded, dict) else None
        return {
            "ok": False,
            "error_code": str(error_code or exc.code or "http_error"),
        }
    except Exception as exc:
        _LOGGER.debug("Feedback submission failed: %s", exc)
        return {"ok": False, "error_code": "network_error"}

    try:
        decoded = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        decoded = {}
    if isinstance(decoded, dict) and decoded.get("ok") is False:
        return {
            "ok": False,
            "error_code": str(decoded.get("error") or "server_error"),
        }
    return {"ok": True}

