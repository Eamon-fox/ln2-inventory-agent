from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app_gui.application.feedback_reporter import (
    FEEDBACK_MAX_MESSAGE_LENGTH,
    _normalize_feedback_message,
    post_feedback,
)


def test_post_feedback_posts_json_with_short_timeout():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"ok": true}'

    with patch(
        "app_gui.application.feedback_reporter.urllib.request.urlopen",
        return_value=response,
    ) as mock_urlopen:
        result = post_feedback(
            "Please add CSV import validation.",
            endpoint="https://example.invalid/feedback.php",
            timeout=2.0,
            app_version="v1.3.12",
            language="zh-CN",
        )

    request = mock_urlopen.call_args.args[0]
    assert result == {"ok": True}
    assert request.full_url == "https://example.invalid/feedback.php"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["message"] == "Please add CSV import validation."
    assert payload["app"] == "SnowFox"
    assert payload["version"] == "v1.3.12"
    assert payload["language"] == "zh-CN"
    assert set(payload["platform"]) == {"system", "release", "machine"}
    assert mock_urlopen.call_args.kwargs["timeout"] == 2.0
    response.read.assert_called_once_with(8192)


def test_post_feedback_rejects_empty_message_without_network():
    with patch("app_gui.application.feedback_reporter.urllib.request.urlopen") as mock_urlopen:
        result = post_feedback("  ")

    assert result == {"ok": False, "error_code": "empty_message"}
    mock_urlopen.assert_not_called()


def test_post_feedback_swallows_network_errors():
    with patch(
        "app_gui.application.feedback_reporter.urllib.request.urlopen",
        side_effect=RuntimeError("server failed"),
    ):
        result = post_feedback("Something happened")

    assert result == {"ok": False, "error_code": "network_error"}


def test_normalize_feedback_message_caps_length():
    assert len(_normalize_feedback_message("x" * (FEEDBACK_MAX_MESSAGE_LENGTH + 10))) == (
        FEEDBACK_MAX_MESSAGE_LENGTH
    )

