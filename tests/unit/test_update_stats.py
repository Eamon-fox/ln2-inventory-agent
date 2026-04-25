from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app_gui.application.update_stats import (
    _post_update_get_stats,
    report_update_get,
)


def test_post_update_get_stats_posts_json_with_short_timeout():
    response = MagicMock()
    response.__enter__.return_value = response

    with patch(
        "app_gui.application.update_stats.urllib.request.urlopen",
        return_value=response,
    ) as mock_urlopen:
        _post_update_get_stats(
            "v1.3.12",
            "auto_update_start",
            endpoint="https://example.invalid/download-stats.php",
            timeout=2.0,
        )

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "https://example.invalid/download-stats.php"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "version": "1.3.12",
        "source": "auto_update_start",
    }
    assert mock_urlopen.call_args.kwargs["timeout"] == 2.0
    response.read.assert_called_once_with(1)


def test_post_update_get_stats_swallows_network_errors():
    with patch(
        "app_gui.application.update_stats.urllib.request.urlopen",
        side_effect=RuntimeError("server failed"),
    ):
        _post_update_get_stats("1.3.12", "manual_update_start")


def test_report_update_get_starts_daemon_thread():
    thread = MagicMock()
    with patch(
        "app_gui.application.update_stats.threading.Thread",
        return_value=thread,
    ) as mock_thread:
        report_update_get("1.3.12", "auto_update_start")

    mock_thread.assert_called_once()
    kwargs = mock_thread.call_args.kwargs
    assert kwargs["target"] is _post_update_get_stats
    assert kwargs["args"] == ("1.3.12", "auto_update_start")
    assert kwargs["daemon"] is True
    thread.start.assert_called_once()
