"""Single source of truth for application version and update-check constants."""

APP_VERSION: str = "1.3.3"
APP_RELEASE_URL: str = "https://github.com/Eamon-fox/snowfox/releases"
UPDATE_CHECK_URL: str = "https://snowfox-release.oss-cn-beijing.aliyuncs.com/latest.json"


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
