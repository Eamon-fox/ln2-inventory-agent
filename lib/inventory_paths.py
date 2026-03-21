"""Inventory path policy helpers.

Inventory files are always locked to:
    <data_root>/inventories/<dataset_name>/inventory.yaml
"""

import os
import shutil

from .app_storage import (
    get_install_dir,
    get_inventories_root as _get_data_root_inventories_root,
)

INVENTORIES_DIR_NAME = "inventories"
INVENTORY_FILE_NAME = "inventory.yaml"

_INVALID_DATASET_CHARS = set('<>:"/\\|?*')


class InventoryPathError(ValueError):
    """Raised when an inventory path violates managed-root policy."""

    def __init__(self, message, *, code="inventory_path_error", details=None):
        super().__init__(str(message))
        self.code = str(code or "inventory_path_error")
        self.details = dict(details or {})


def inventory_lock_enabled():
    """Return whether managed inventory path policy is enforced."""
    return True


def get_inventories_root():
    """Return managed inventories root directory."""
    return _get_data_root_inventories_root()


def ensure_inventories_root():
    """Create and return managed inventories root directory."""
    root = get_inventories_root()
    os.makedirs(root, exist_ok=True)
    return root


def inventory_yaml_in_dataset_dir(dataset_dir):
    """Return canonical inventory.yaml path for a dataset directory."""
    return os.path.join(os.path.abspath(str(dataset_dir or "")), INVENTORY_FILE_NAME)


def _norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path or ""))))


def _real_norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.realpath(os.path.abspath(str(path or "")))))


def _is_managed_path_shape(path):
    abs_path = os.path.abspath(str(path or ""))
    if not abs_path:
        return False
    if os.path.basename(abs_path).lower() != INVENTORY_FILE_NAME:
        return False

    dataset_dir = os.path.dirname(abs_path)
    root = get_inventories_root()

    if _norm_path(os.path.dirname(dataset_dir)) != _norm_path(root):
        return False

    # Prevent symlink/path escapes: real dataset dir must remain a direct child of root.
    real_root = _real_norm_path(root)
    real_dataset_dir = _real_norm_path(dataset_dir)
    if _norm_path(os.path.dirname(real_dataset_dir)) != real_root:
        return False

    try:
        if os.path.commonpath([real_dataset_dir, real_root]) != real_root:
            return False
    except ValueError:
        return False

    return True


def is_managed_inventory_yaml_path(path):
    """Return True when path follows managed inventory root policy."""
    return _is_managed_path_shape(path)


def assert_allowed_inventory_yaml_path(path, *, must_exist=False):
    """Validate and normalize inventory YAML path under managed-root policy."""
    abs_path = os.path.abspath(str(path or "").strip())
    if not abs_path:
        raise InventoryPathError("Inventory YAML path is required.")

    ensure_inventories_root()
    if not _is_managed_path_shape(abs_path):
        root = get_inventories_root()
        raise InventoryPathError(
            f"Inventory path must be <inventories>/<dataset>/{INVENTORY_FILE_NAME} under {root}."
        )

    if must_exist and not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path)

    return abs_path


def sanitize_dataset_name(name, *, fallback="inventory"):
    """Normalize user-facing dataset name to a filesystem-safe directory name."""
    raw = str(name or "").strip()
    chars = []
    for ch in raw:
        if ord(ch) < 32 or ch in _INVALID_DATASET_CHARS:
            chars.append("-")
        else:
            chars.append(ch)
    cleaned = "".join(chars).strip().strip(".")
    cleaned = cleaned.rstrip(" ")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned or str(fallback)


def validate_target_dataset_name(name):
    """Validate and normalize one explicit target dataset name."""
    raw = str(name or "").strip()
    if not raw:
        raise InventoryPathError(
            "Dataset name is required.",
            code="invalid_dataset_name",
        )
    normalized = sanitize_dataset_name(raw, fallback="")
    if not normalized:
        raise InventoryPathError(
            "Dataset name is invalid after normalization.",
            code="invalid_dataset_name",
            details={"input": raw},
        )
    return normalized


def allocate_dataset_dir(dataset_name):
    """Return a non-existing managed dataset directory path."""
    root = ensure_inventories_root()
    base = sanitize_dataset_name(dataset_name)
    candidate = os.path.join(root, base)
    i = 2
    while os.path.exists(candidate):
        candidate = os.path.join(root, f"{base}-{i}")
        i += 1
    return candidate


def list_managed_datasets():
    """List managed datasets that contain canonical inventory.yaml."""
    root = get_inventories_root()
    if not os.path.isdir(root):
        return []

    rows = []
    for name in os.listdir(root):
        dataset_dir = os.path.join(root, name)
        if not os.path.isdir(dataset_dir):
            continue
        yaml_path = inventory_yaml_in_dataset_dir(dataset_dir)
        if not os.path.isfile(yaml_path):
            continue
        rows.append({
            "name": name,
            "dataset_dir": dataset_dir,
            "yaml_path": yaml_path,
            "mtime": os.path.getmtime(yaml_path),
        })
    rows.sort(key=lambda row: (row.get("mtime", 0), row.get("name", "")), reverse=True)
    return rows


def latest_managed_inventory_yaml_path():
    """Return newest managed dataset YAML path, or empty string."""
    rows = list_managed_datasets()
    if not rows:
        return ""
    return str(rows[0].get("yaml_path") or "")


def create_managed_dataset_yaml_path(dataset_name):
    """Create managed dataset directory and return canonical inventory.yaml path."""
    dataset_dir = allocate_dataset_dir(dataset_name)
    os.makedirs(dataset_dir, exist_ok=False)
    return inventory_yaml_in_dataset_dir(dataset_dir)


def rename_managed_dataset_yaml_path(yaml_path, new_dataset_name):
    """Rename one managed dataset directory and return new inventory.yaml path."""
    source_yaml = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
    source_yaml = os.path.abspath(str(source_yaml))
    source_dataset_dir = os.path.dirname(source_yaml)
    source_name = os.path.basename(source_dataset_dir)

    target_name = validate_target_dataset_name(new_dataset_name)
    if target_name == source_name:
        raise InventoryPathError(
            "Dataset name is unchanged.",
            code="dataset_name_unchanged",
            details={"dataset_name": source_name},
        )

    root = ensure_inventories_root()
    target_dataset_dir = os.path.join(root, target_name)
    if os.path.exists(target_dataset_dir):
        raise InventoryPathError(
            f"Target dataset already exists: {target_name}",
            code="dataset_name_conflict",
            details={"target_dataset_name": target_name},
        )

    try:
        os.rename(source_dataset_dir, target_dataset_dir)
    except Exception as exc:
        raise InventoryPathError(
            f"Failed to rename dataset directory: {exc}",
            code="dataset_rename_failed",
            details={
                "source_dataset_dir": source_dataset_dir,
                "target_dataset_dir": target_dataset_dir,
            },
        ) from exc

    target_yaml = inventory_yaml_in_dataset_dir(target_dataset_dir)
    try:
        return assert_allowed_inventory_yaml_path(target_yaml, must_exist=True)
    except Exception as exc:
        raise InventoryPathError(
            f"Renamed dataset path validation failed: {exc}",
            code="dataset_rename_failed",
            details={
                "source_dataset_dir": source_dataset_dir,
                "target_dataset_dir": target_dataset_dir,
                "target_yaml_path": target_yaml,
            },
        ) from exc


def build_dataset_rename_payload(old_yaml_path, new_yaml_path):
    """Return normalized audit details for one dataset-rename operation."""
    old_yaml_abs = os.path.abspath(str(old_yaml_path or ""))
    new_yaml_abs = os.path.abspath(str(new_yaml_path or ""))
    old_name = managed_dataset_name_from_yaml_path(old_yaml_abs) if old_yaml_abs else ""
    new_name = managed_dataset_name_from_yaml_path(new_yaml_abs) if new_yaml_abs else ""
    return {
        "kind": "dataset_rename",
        "old_dataset_name": old_name,
        "new_dataset_name": new_name,
        "old_yaml_path": old_yaml_abs,
        "new_yaml_path": new_yaml_abs,
    }


def delete_managed_dataset_yaml_path(yaml_path):
    """Delete one managed dataset directory and return deleted metadata."""
    source_yaml = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
    source_yaml = os.path.abspath(str(source_yaml))
    dataset_dir = os.path.dirname(source_yaml)
    dataset_name = os.path.basename(dataset_dir)
    try:
        shutil.rmtree(dataset_dir)
    except Exception as exc:
        raise InventoryPathError(
            f"Failed to delete dataset directory: {exc}",
            code="dataset_delete_failed",
            details={
                "dataset_name": dataset_name,
                "dataset_dir": dataset_dir,
                "yaml_path": source_yaml,
            },
        ) from exc
    return {
        "dataset_name": dataset_name,
        "dataset_dir": dataset_dir,
        "yaml_path": source_yaml,
    }


def build_dataset_delete_payload(deleted_yaml_path, switched_yaml_path=""):
    """Return normalized audit details for one dataset-delete operation."""
    deleted_yaml_abs = os.path.abspath(str(deleted_yaml_path or ""))
    switched_yaml_abs = os.path.abspath(str(switched_yaml_path or "")) if switched_yaml_path else ""
    deleted_name = managed_dataset_name_from_yaml_path(deleted_yaml_abs) if deleted_yaml_abs else ""
    switched_name = managed_dataset_name_from_yaml_path(switched_yaml_abs) if switched_yaml_abs else ""
    return {
        "kind": "dataset_delete",
        "deleted_dataset_name": deleted_name,
        "deleted_yaml_path": deleted_yaml_abs,
        "switched_dataset_name": switched_name,
        "switched_yaml_path": switched_yaml_abs,
    }


def managed_dataset_name_from_yaml_path(yaml_path):
    """Return dataset directory name from managed yaml path."""
    abs_path = os.path.abspath(str(yaml_path or ""))
    return os.path.basename(os.path.dirname(abs_path))


def normalize_inventory_yaml_path(path_text) -> str:
    """Normalize inventory YAML path to an absolute path.

    Returns empty string for empty/None input.
    """
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    return os.path.abspath(raw)


def build_dataset_combo_items(rows, current_yaml: str = ""):
    """Build (name, yaml_path) pairs and locate current selection index.

    Parameters
    ----------
    rows : list[dict]
        Output of :func:`list_managed_datasets`.
    current_yaml : str
        Currently active YAML path (will be normalized for comparison).

    Returns
    -------
    tuple[list[tuple[str, str]], int]
        ``(items, selected_index)`` where *items* are ``(display_name, yaml_path)``
        pairs and *selected_index* is the 0-based index of the item matching
        *current_yaml* (``0`` as fallback when not found).
    """
    current_norm = normalize_inventory_yaml_path(current_yaml)
    items: list[tuple[str, str]] = []
    selected_idx = 0
    for row in rows:
        name = str(row.get("name") or "").strip()
        yaml_path = normalize_inventory_yaml_path(row.get("yaml_path"))
        if not yaml_path:
            continue
        if not name:
            name = os.path.basename(os.path.dirname(yaml_path)) or yaml_path
        items.append((name, yaml_path))

    if items and current_norm:
        for i, (_name, yp) in enumerate(items):
            if yp == current_norm:
                selected_idx = i
                break

    return items, selected_idx
