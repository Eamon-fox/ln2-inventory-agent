"""Single source of truth for application version and update-check constants."""

from __future__ import annotations

import sys
from typing import Mapping

APP_VERSION: str = "1.3.11"
APP_RELEASE_URL: str = "https://snowfox.bio/download.html"
UPDATE_CHECK_URL: str = "https://snowfox-release.oss-cn-beijing.aliyuncs.com/latest.json"

DEFAULT_RELEASE_PLATFORM: str = "windows"
PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
}


def parse_version(v: str) -> tuple:
    """Parse version string like '1.0.2' to tuple (1, 0, 2) for comparison."""
    try:
        normalized = str(v or "").strip().lstrip("vV")
        return tuple(int(x) for x in normalized.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_version_newer(new_version: str, old_version: str) -> bool:
    """Return True if *new_version* > *old_version* using semver comparison."""
    return parse_version(new_version) > parse_version(old_version)


def current_release_platform(system_platform: str | None = None) -> str:
    """Normalize the current runtime platform to the release metadata key."""
    value = str(system_platform or sys.platform).lower()
    if value.startswith("win"):
        return "windows"
    if value == "darwin":
        return "macos"
    return DEFAULT_RELEASE_PLATFORM


def resolve_platform_release_info(
    payload: Mapping[str, object] | None,
    *,
    system_platform: str | None = None,
) -> dict[str, object]:
    """Return the effective release metadata for the current platform.

    `latest.json.download_url` remains the legacy compatibility field. Newer
    clients prefer `latest.json.platforms.<platform>.download_url`.
    """

    platform_key = current_release_platform(system_platform)
    download_url = ""
    auto_update = platform_key == "windows"

    if isinstance(payload, Mapping):
        platforms = payload.get("platforms")
        if isinstance(platforms, Mapping):
            platform_payload = platforms.get(platform_key)
            if isinstance(platform_payload, Mapping):
                candidate_url = platform_payload.get("download_url")
                if isinstance(candidate_url, str):
                    download_url = candidate_url.strip()
                candidate_auto_update = platform_payload.get("auto_update")
                if isinstance(candidate_auto_update, bool):
                    auto_update = candidate_auto_update

        if not download_url:
            legacy_url = payload.get("download_url")
            if isinstance(legacy_url, str):
                download_url = legacy_url.strip()

    return {
        "platform_key": platform_key,
        "platform_name": PLATFORM_DISPLAY_NAMES.get(platform_key, platform_key),
        "download_url": download_url,
        "auto_update": auto_update,
    }
