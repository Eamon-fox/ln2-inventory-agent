"""Unified runtime configuration for LN2 inventory management.

Configuration precedence:
1) Built-in defaults in this file
2) JSON file from environment variable ``LN2_CONFIG_FILE``
"""

import copy
import json
import os
import sys


CONFIG_ENV_VAR = "LN2_CONFIG_FILE"


def _default_yaml_path():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "ln2_inventory.yaml")
    return os.path.join(os.getcwd(), "ln2_inventory.yaml")


DEFAULT_CONFIG = {
    "yaml_path": _default_yaml_path(),
    "python_path": sys.executable,
    "safety": {
        "backup_dir_name": "ln2_inventory_backups",
        "backup_keep_count": 200,
        "audit_log_file": "ln2_inventory_audit.jsonl",
        "total_empty_warning_threshold": 20,
        "box_empty_warning_threshold": 5,
        "yaml_size_warning_mb": 5,
    },
    "schema": {
        "box_range": [1, 5],
        "position_range": [1, 81],
        "valid_actions": ["取出", "复苏", "扔掉", "移动"],
        "valid_cell_lines": [],
    },
}


def _merge_dict(base, override):
    """Recursively merge ``override`` into ``base`` in-place."""
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def _load_external_config():
    """Load user config JSON from LN2_CONFIG_FILE if provided."""
    config_path = os.environ.get(CONFIG_ENV_VAR)
    if not config_path:
        return {}, None

    expanded = os.path.expanduser(config_path)
    abs_path = os.path.abspath(expanded)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(
            f"warning: failed to load {CONFIG_ENV_VAR}={abs_path}: {exc}",
            file=sys.stderr,
        )
        return {}, None

    if not isinstance(payload, dict):
        print(
            f"warning: {CONFIG_ENV_VAR} must point to a JSON object: {abs_path}",
            file=sys.stderr,
        )
        return {}, None

    return payload, os.path.dirname(abs_path)


def _normalize_paths(config, config_dir=None):
    """Expand user paths and resolve relative paths against config file directory."""
    for key in ("yaml_path", "python_path"):
        value = config.get(key)
        if not value:
            continue

        value = os.path.expanduser(str(value))
        if not os.path.isabs(value) and config_dir:
            value = os.path.abspath(os.path.join(config_dir, value))
        config[key] = os.path.abspath(value)


def _build_runtime_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    external, config_dir = _load_external_config()
    _merge_dict(config, external)
    _normalize_paths(config, config_dir=config_dir)
    return config


RUNTIME_CONFIG = _build_runtime_config()


def get_runtime_config():
    """Return a copy of resolved runtime configuration."""
    return copy.deepcopy(RUNTIME_CONFIG)


def _warn_bad_value(name, value, fallback):
    print(
        f"warning: invalid config value for {name}={value!r}; using {fallback!r}",
        file=sys.stderr,
    )


def _as_int(name, value, fallback):
    try:
        return int(value)
    except Exception:
        _warn_bad_value(name, value, fallback)
        return int(fallback)


def _as_float(name, value, fallback):
    try:
        return float(value)
    except Exception:
        _warn_bad_value(name, value, fallback)
        return float(fallback)


def _as_range(name, value, fallback):
    try:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return int(value[0]), int(value[1])
    except Exception:
        pass
    _warn_bad_value(name, value, fallback)
    return int(fallback[0]), int(fallback[1])


def _as_list(name, value, fallback):
    if isinstance(value, (list, tuple)):
        return list(value)
    _warn_bad_value(name, value, fallback)
    return list(fallback)


# Paths
YAML_PATH = RUNTIME_CONFIG["yaml_path"]
PYTHON_PATH = RUNTIME_CONFIG["python_path"]

# Safety / operations
BACKUP_DIR_NAME = RUNTIME_CONFIG["safety"]["backup_dir_name"]
BACKUP_KEEP_COUNT = _as_int(
    "safety.backup_keep_count",
    RUNTIME_CONFIG["safety"].get("backup_keep_count"),
    DEFAULT_CONFIG["safety"]["backup_keep_count"],
)
AUDIT_LOG_FILE = RUNTIME_CONFIG["safety"]["audit_log_file"]
TOTAL_EMPTY_WARNING_THRESHOLD = _as_int(
    "safety.total_empty_warning_threshold",
    RUNTIME_CONFIG["safety"].get("total_empty_warning_threshold"),
    DEFAULT_CONFIG["safety"]["total_empty_warning_threshold"],
)
BOX_EMPTY_WARNING_THRESHOLD = _as_int(
    "safety.box_empty_warning_threshold",
    RUNTIME_CONFIG["safety"].get("box_empty_warning_threshold"),
    DEFAULT_CONFIG["safety"]["box_empty_warning_threshold"],
)
YAML_SIZE_WARNING_MB = _as_float(
    "safety.yaml_size_warning_mb",
    RUNTIME_CONFIG["safety"].get("yaml_size_warning_mb"),
    DEFAULT_CONFIG["safety"]["yaml_size_warning_mb"],
)

# Schema / validation
BOX_RANGE = _as_range(
    "schema.box_range",
    RUNTIME_CONFIG["schema"].get("box_range"),
    DEFAULT_CONFIG["schema"]["box_range"],
)
POSITION_RANGE = _as_range(
    "schema.position_range",
    RUNTIME_CONFIG["schema"].get("position_range"),
    DEFAULT_CONFIG["schema"]["position_range"],
)
VALID_ACTIONS = _as_list(
    "schema.valid_actions",
    RUNTIME_CONFIG["schema"].get("valid_actions"),
    DEFAULT_CONFIG["schema"]["valid_actions"],
)
VALID_CELL_LINES = _as_list(
    "schema.valid_cell_lines",
    RUNTIME_CONFIG["schema"].get("valid_cell_lines"),
    DEFAULT_CONFIG["schema"]["valid_cell_lines"],
)
