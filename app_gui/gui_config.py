"""Unified GUI configuration manager.

Canonical config: ~/.ln2agent/config.yaml
Falls back to defaults if file does not exist.
"""

import copy
import os
import sys

import yaml

from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.ln2agent")
DEFAULT_CONFIG_FILE = os.path.join(DEFAULT_CONFIG_DIR, "config.yaml")

DEFAULT_MAX_STEPS = 12


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
    "yaml_path": None,
    "api_keys": {},
    "language": "zh-CN",
    "theme": "light",
    "last_notified_release": "0.0.0",
    "release_notes_preview": "",
    "import_prompt_seen": False,
    "ai": {
        "provider": DEFAULT_PROVIDER,
        "model": None,
        "max_steps": DEFAULT_MAX_STEPS,
        "thinking_enabled": True,
        "custom_prompt": "",
    },
}


def load_gui_config(path=DEFAULT_CONFIG_FILE):
    """Load GUI config from YAML file. Returns dict with defaults merged."""
    def _apply_defaults(cfg):
        provider = cfg.get("ai", {}).get("provider") or DEFAULT_PROVIDER
        if provider not in PROVIDER_DEFAULTS:
            provider = DEFAULT_PROVIDER
        cfg.setdefault("ai", {})["provider"] = provider
        cfg.setdefault("api_keys", {})
        if not isinstance(cfg.get("api_keys"), dict):
            cfg["api_keys"] = {}
        if not str(cfg.get("ai", {}).get("model") or "").strip():
            cfg["ai"]["model"] = PROVIDER_DEFAULTS[provider]["model"]
        cfg["ai"]["thinking_enabled"] = bool(cfg.get("ai", {}).get("thinking_enabled", True))
        if not cfg.get("ai", {}).get("custom_prompt"):
            cfg["ai"]["custom_prompt"] = _load_default_prompt()
        cfg["import_prompt_seen"] = bool(cfg.get("import_prompt_seen", False))
        return cfg

    if not os.path.isfile(path):
        cfg = copy.deepcopy(DEFAULT_GUI_CONFIG)
        return _apply_defaults(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        merged = copy.deepcopy(DEFAULT_GUI_CONFIG)
        for key in ("yaml_path", "api_keys", "language", "theme", "last_notified_release", "release_notes_preview", "import_prompt_seen"):
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


def save_gui_config(config, path=DEFAULT_CONFIG_FILE):
    """Save GUI config to YAML file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
