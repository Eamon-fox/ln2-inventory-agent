"""Best-effort update download statistics reporting."""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

UPDATE_STATS_URL = "https://snowfox.bio/download-stats.php"
UPDATE_STATS_TIMEOUT_SECONDS = 2.5
_LOGGER = logging.getLogger(__name__)


def _normalize_version(version: object) -> str:
    return str(version or "").strip().lstrip("vV")


def _post_update_get_stats(
    version: object,
    source: object,
    *,
    endpoint: str = UPDATE_STATS_URL,
    timeout: float = UPDATE_STATS_TIMEOUT_SECONDS,
) -> None:
    normalized_version = _normalize_version(version)
    normalized_source = str(source or "").strip()
    if not normalized_version or not normalized_source:
        return

    payload = json.dumps(
        {
            "version": normalized_version,
            "source": normalized_source,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        str(endpoint),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SnowFox",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
    except Exception as exc:
        _LOGGER.debug("Ignored update stats report failure: %s", exc)


def report_update_get(version: object, source: str) -> None:
    """Report an update-get event without blocking the update flow."""

    try:
        thread = threading.Thread(
            target=_post_update_get_stats,
            args=(version, source),
            name="snowfox-update-stats",
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        _LOGGER.debug("Ignored update stats report start failure: %s", exc)
