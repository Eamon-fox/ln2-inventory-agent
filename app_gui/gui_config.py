"""Unified GUI configuration manager.

Canonical config: ~/.ln2agent/config.yaml
Falls back to defaults if file does not exist.
"""

import copy
import os
import sys

import yaml

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
    "api_key": None,
    "language": "en",
    "theme": "dark",
    "ai": {
        "model": "deepseek-chat",
        "max_steps": DEFAULT_MAX_STEPS,
        "thinking_enabled": True,
        "custom_prompt": "",
    },
}


def load_gui_config(path=DEFAULT_CONFIG_FILE):
    """Load GUI config from YAML file. Returns dict with defaults merged."""
    if not os.path.isfile(path):
        cfg = copy.deepcopy(DEFAULT_GUI_CONFIG)
        cfg["ai"]["custom_prompt"] = _load_default_prompt()
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        merged = copy.deepcopy(DEFAULT_GUI_CONFIG)
        for key in ("yaml_path", "api_key", "language", "theme"):
            if key in data:
                merged[key] = data[key]
        if "ai" in data and isinstance(data["ai"], dict):
            merged["ai"] = copy.deepcopy(DEFAULT_GUI_CONFIG["ai"])
            for key in ("model", "max_steps", "thinking_enabled", "custom_prompt"):
                if key in data["ai"]:
                    merged["ai"][key] = data["ai"][key]
        if not str(merged["ai"].get("model") or "").strip():
            merged["ai"]["model"] = DEFAULT_GUI_CONFIG["ai"]["model"]
        merged["ai"]["thinking_enabled"] = bool(merged["ai"].get("thinking_enabled", True))
        if not merged["ai"].get("custom_prompt"):
            merged["ai"]["custom_prompt"] = _load_default_prompt()
        return merged
    except Exception:
        cfg = copy.deepcopy(DEFAULT_GUI_CONFIG)
        cfg["ai"]["custom_prompt"] = _load_default_prompt()
        return cfg


def save_gui_config(config, path=DEFAULT_CONFIG_FILE):
    """Save GUI config to YAML file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
