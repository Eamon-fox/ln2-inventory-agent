"""Shared application storage-path helpers.

This module separates:
- install root: bundled executable/resources (read-mostly)
- config root: small per-user config
- data root: user-chosen writable inventory/workspace root
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml


APP_DIR_NAME = "SnowFox"
CONFIG_ROOT_ENV_VAR = "SNOWFOX_CONFIG_ROOT"
DATA_ROOT_ENV_VAR = "SNOWFOX_DATA_ROOT"

_SESSION_DATA_ROOT: Optional[str] = None


def get_install_dir() -> str:
    """Return install directory (or project root in source mode)."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(os.path.dirname(sys.executable))
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def get_legacy_config_dir() -> str:
    return os.path.join(get_install_dir(), "config")


def get_legacy_config_file() -> str:
    return os.path.join(get_legacy_config_dir(), "config.yaml")


def get_legacy_data_root() -> str:
    return get_install_dir()


def _platform_config_base() -> str:
    env_root = str(os.environ.get(CONFIG_ROOT_ENV_VAR) or "").strip()
    if env_root:
        return os.path.abspath(os.path.expanduser(env_root))

    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support")
    if os.name == "nt":
        return os.path.abspath(
            os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        )
    return os.path.join(home, ".config")


def get_user_config_dir() -> str:
    return os.path.join(_platform_config_base(), APP_DIR_NAME)


def get_user_config_file() -> str:
    return os.path.join(get_user_config_dir(), "config.yaml")


def normalize_data_root(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    return os.path.abspath(os.path.expanduser(raw))


def set_session_data_root(path: str) -> str:
    global _SESSION_DATA_ROOT
    _SESSION_DATA_ROOT = normalize_data_root(path)
    return str(_SESSION_DATA_ROOT or "")


def clear_session_data_root() -> None:
    global _SESSION_DATA_ROOT
    _SESSION_DATA_ROOT = None


def _read_yaml_map(path: str) -> dict:
    target = os.path.abspath(str(path or ""))
    if not target or not os.path.isfile(target):
        return {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_configured_data_root(config_path: str = "") -> str:
    target = str(config_path or "").strip() or get_user_config_file()
    payload = _read_yaml_map(target)
    return normalize_data_root(payload.get("data_root"))


def resolve_data_root(*, config_path: str = "", fallback_to_legacy: bool = True) -> str:
    if _SESSION_DATA_ROOT:
        return str(_SESSION_DATA_ROOT)

    env_root = normalize_data_root(os.environ.get(DATA_ROOT_ENV_VAR, ""))
    if env_root:
        return env_root

    configured = load_configured_data_root(config_path=config_path)
    if configured:
        return configured

    if fallback_to_legacy:
        return get_legacy_data_root()
    return ""


def get_inventories_root(*, data_root: str = "", fallback_to_legacy: bool = True) -> str:
    root = normalize_data_root(data_root) or resolve_data_root(
        fallback_to_legacy=fallback_to_legacy
    )
    return os.path.join(root, "inventories") if root else ""


def get_migrate_root(*, data_root: str = "", fallback_to_legacy: bool = True) -> str:
    root = normalize_data_root(data_root) or resolve_data_root(
        fallback_to_legacy=fallback_to_legacy
    )
    return os.path.join(root, "migrate") if root else ""


def get_legacy_inventories_root() -> str:
    return os.path.join(get_legacy_data_root(), "inventories")


def get_legacy_migrate_root() -> str:
    return os.path.join(get_legacy_data_root(), "migrate")


def ensure_data_root_layout(data_root: str) -> str:
    root = normalize_data_root(data_root)
    if not root:
        raise ValueError("data_root is required")
    os.makedirs(root, exist_ok=True)
    os.makedirs(get_inventories_root(data_root=root, fallback_to_legacy=False), exist_ok=True)
    os.makedirs(get_migrate_root(data_root=root, fallback_to_legacy=False), exist_ok=True)
    return root


def has_any_legacy_data() -> bool:
    for candidate in (get_legacy_inventories_root(), get_legacy_migrate_root()):
        if os.path.exists(candidate):
            return True
    legacy_config = get_legacy_config_file()
    return os.path.isfile(legacy_config)


def _copy_tree_if_present(source_root: str, target_root: str, name: str) -> None:
    source = os.path.join(source_root, name)
    if not os.path.exists(source):
        return
    target = os.path.join(target_root, name)
    if os.path.exists(target):
        # Allow empty pre-created directory roots, but reject merges.
        if os.path.isdir(target) and not os.listdir(target):
            os.rmdir(target)
        else:
            raise ValueError(f"target already contains {name}: {target}")
    shutil.copytree(source, target)


def migrate_data_root(source_root: str, target_root: str) -> dict:
    source = normalize_data_root(source_root)
    target = normalize_data_root(target_root)
    if not source:
        raise ValueError("source_root is required")
    if not target:
        raise ValueError("target_root is required")
    if source == target:
        return {
            "data_root": target,
            "inventories_root": get_inventories_root(data_root=target, fallback_to_legacy=False),
            "migrate_root": get_migrate_root(data_root=target, fallback_to_legacy=False),
        }

    ensure_data_root_layout(target)
    _copy_tree_if_present(source, target, "inventories")
    _copy_tree_if_present(source, target, "migrate")
    return {
        "data_root": target,
        "inventories_root": get_inventories_root(data_root=target, fallback_to_legacy=False),
        "migrate_root": get_migrate_root(data_root=target, fallback_to_legacy=False),
    }


def remap_inventory_yaml_path(yaml_path: str, *, source_root: str, target_root: str) -> str:
    current = os.path.abspath(str(yaml_path or "").strip())
    source = normalize_data_root(source_root)
    target = normalize_data_root(target_root)
    if not current or not source or not target:
        return ""
    inventories_root = Path(get_inventories_root(data_root=source, fallback_to_legacy=False))
    try:
        rel = Path(current).relative_to(inventories_root)
    except Exception:
        return ""
    return os.path.abspath(
        os.path.join(get_inventories_root(data_root=target, fallback_to_legacy=False), os.fspath(rel))
    )
