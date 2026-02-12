"""Unified GUI configuration manager.

Canonical config: ~/.ln2agent/config.yaml
Falls back to defaults if file does not exist.
"""

import copy
import os

import yaml

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.ln2agent")
DEFAULT_CONFIG_FILE = os.path.join(DEFAULT_CONFIG_DIR, "config.yaml")

DEFAULT_GUI_CONFIG = {
    "yaml_path": None,
    "actor_id": "gui-user",
    "api_key": None,
    "language": "en",
    "theme": "dark",
    "ai": {
        "model": "deepseek-chat",
        "max_steps": 8,
    },
}


def load_gui_config(path=DEFAULT_CONFIG_FILE):
    """Load GUI config from YAML file. Returns dict with defaults merged."""
    if not os.path.isfile(path):
        return copy.deepcopy(DEFAULT_GUI_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        merged = copy.deepcopy(DEFAULT_GUI_CONFIG)
        for key in ("yaml_path", "actor_id", "api_key", "language", "theme"):
            if key in data:
                merged[key] = data[key]
        if "ai" in data and isinstance(data["ai"], dict):
            merged["ai"] = copy.deepcopy(DEFAULT_GUI_CONFIG["ai"])
            for key in ("model", "max_steps"):
                if key in data["ai"]:
                    merged["ai"][key] = data["ai"][key]
        if not str(merged["ai"].get("model") or "").strip():
            merged["ai"]["model"] = DEFAULT_GUI_CONFIG["ai"]["model"]
        return merged
    except Exception:
        return copy.deepcopy(DEFAULT_GUI_CONFIG)


def save_gui_config(config, path=DEFAULT_CONFIG_FILE):
    """Save GUI config to YAML file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
