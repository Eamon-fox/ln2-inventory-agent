"""Unified GUI configuration manager."""

import copy
import os
import sys

import yaml

from agent.agent_defaults import AGENT_HISTORY_MAX_TURNS, DEFAULT_MAX_STEPS
from app_gui.application.ai_provider_catalog import (
    DEFAULT_AI_PROVIDER,
    default_ai_model,
    normalize_ai_model,
    normalize_ai_provider,
)
from app_gui.application.open_api.contracts import LOCAL_OPEN_API_DEFAULT_PORT
from lib.app_storage import (
    get_legacy_config_file,
    get_user_config_dir,
    get_user_config_file,
    normalize_data_root,
)

DEFAULT_CONFIG_DIR = get_user_config_dir()
DEFAULT_CONFIG_FILE = get_user_config_file()
LEGACY_CONFIG_FILE = get_legacy_config_file()

MAX_AGENT_STEPS = 120
AI_HISTORY_LIMIT = 2000
AI_OPERATION_CONTEXT_LIMIT = 20
AI_OPERATION_EVENT_POOL_LIMIT = 20


def _resolve_assets_dir():
    """Return the assets directory, works both in dev and PyInstaller frozen mode."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "app_gui", "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _load_default_prompt():
    """Load bundled default_prompt.txt if it exists."""
    path = os.path.join(_resolve_assets_dir(), "default_prompt.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

DEFAULT_GUI_CONFIG = {
    "data_root": None,
    "yaml_path": None,
    "api_keys": {},
    "language": "zh-CN",
    "theme": "light",
    "ui_scale": 1.0,
    "open_api": {
        "enabled": False,
        "port": LOCAL_OPEN_API_DEFAULT_PORT,
    },
    "last_notified_release": "0.0.0",
    "release_notes_preview": "",
    "import_onboarding_seen": False,
    "ai": {
        "provider": DEFAULT_AI_PROVIDER,
        "model": None,
        "max_steps": DEFAULT_MAX_STEPS,
        "thinking_enabled": True,
        "custom_prompt": "",
    },
}


def config_file_exists(path=None):
    target = str(path or "").strip() or DEFAULT_CONFIG_FILE
    if os.path.isfile(target):
        return True
    if os.path.abspath(target) == os.path.abspath(DEFAULT_CONFIG_FILE):
        return os.path.isfile(LEGACY_CONFIG_FILE)
    return False


def load_gui_config(path=None):
    """Load GUI config from YAML file. Returns dict with defaults merged."""
    def _apply_defaults(cfg):
        cfg["data_root"] = normalize_data_root(cfg.get("data_root")) or None
        provider = normalize_ai_provider(cfg.get("ai", {}).get("provider"))
        cfg.setdefault("ai", {})["provider"] = provider
        cfg.setdefault("api_keys", {})
        if not isinstance(cfg.get("api_keys"), dict):
            cfg["api_keys"] = {}
        cfg.setdefault("open_api", {})
        if not isinstance(cfg.get("open_api"), dict):
            cfg["open_api"] = {}
        cfg["open_api"]["enabled"] = bool(cfg.get("open_api", {}).get("enabled", False))
        try:
            port = int(cfg.get("open_api", {}).get("port", LOCAL_OPEN_API_DEFAULT_PORT))
        except Exception:
            port = LOCAL_OPEN_API_DEFAULT_PORT
        cfg["open_api"]["port"] = port if port > 0 else LOCAL_OPEN_API_DEFAULT_PORT
        cfg["ai"]["model"] = normalize_ai_model(provider, cfg.get("ai", {}).get("model"))
        cfg["ai"]["thinking_enabled"] = bool(cfg.get("ai", {}).get("thinking_enabled", True))
        if not cfg.get("ai", {}).get("custom_prompt"):
            cfg["ai"]["custom_prompt"] = _load_default_prompt()
        cfg["import_onboarding_seen"] = bool(cfg.get("import_onboarding_seen", False))
        return cfg

    candidate_path = str(path or "").strip() or DEFAULT_CONFIG_FILE
    if not os.path.isfile(candidate_path) and os.path.abspath(candidate_path) == os.path.abspath(DEFAULT_CONFIG_FILE):
        candidate_path = LEGACY_CONFIG_FILE if os.path.isfile(LEGACY_CONFIG_FILE) else candidate_path

    if not os.path.isfile(candidate_path):
        cfg = copy.deepcopy(DEFAULT_GUI_CONFIG)
        return _apply_defaults(cfg)
    try:
        with open(candidate_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        merged = copy.deepcopy(DEFAULT_GUI_CONFIG)
        for key in (
            "data_root",
            "yaml_path",
            "api_keys",
            "language",
            "theme",
            "ui_scale",
            "open_api",
            "last_notified_release",
            "release_notes_preview",
            "import_onboarding_seen",
            "migration_mode_notice_suppressed",
        ):
            if key in data:
                merged[key] = data[key]
        if "ai" in data and isinstance(data["ai"], dict):
            merged["ai"] = copy.deepcopy(DEFAULT_GUI_CONFIG["ai"])
            for key in ("provider", "model", "max_steps", "thinking_enabled", "custom_prompt"):
                if key in data["ai"]:
                    merged["ai"][key] = data["ai"][key]
        return _apply_defaults(merged)
    except Exception:
        cfg = copy.deepcopy(DEFAULT_GUI_CONFIG)
        return _apply_defaults(cfg)


def save_gui_config(config, path=None):
    """Save GUI config to YAML file."""
    target = str(path or "").strip() or DEFAULT_CONFIG_FILE
    payload = copy.deepcopy(DEFAULT_GUI_CONFIG)
    if isinstance(config, dict):
        for key, value in config.items():
            if key == "ai" and isinstance(value, dict):
                payload["ai"].update(value)
            else:
                payload[key] = value
    payload["data_root"] = normalize_data_root(payload.get("data_root")) or None
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        f.flush()  # Ensure data is written to disk
        os.fsync(f.fileno())  # Force write to disk
