"""Filesystem path helpers for inventory YAML operations.

Low-level, dependency-light helpers shared by the ``yaml_ops`` facade and its
sibling ``yaml_ops_*`` modules. Keeping these here breaks import cycles: the
facade, backup, audit and stats modules all depend on path resolution but none
of those depend back on this module.
"""
import os

from .config import YAML_PATH
from .inventory_paths import assert_allowed_inventory_yaml_path


def _abs_path(path):
    """Return absolute filesystem path."""
    return os.path.abspath(os.fspath(path if path is not None else YAML_PATH))


def _normalize_path_for_guard(path):
    """Normalize path for guard comparisons across case/slash variants."""
    return os.path.normcase(os.path.normpath(_abs_path(path)))


def get_instance_backup_dir(yaml_path):
    """Return the backup directory for a specific inventory instance.

    Returns:
        str: Path like <dataset_dir>/backups
    """
    yaml_abs = _abs_path(yaml_path)
    managed_yaml = assert_allowed_inventory_yaml_path(yaml_abs)
    dataset_dir = os.path.dirname(managed_yaml)
    return os.path.join(dataset_dir, "backups")


def get_instance_audit_path(yaml_path):
    """Return the audit log path for a specific inventory instance.

    Returns:
        str: Path like <dataset_dir>/audit/events.jsonl
    """
    yaml_abs = _abs_path(yaml_path)
    managed_yaml = assert_allowed_inventory_yaml_path(yaml_abs)
    dataset_dir = os.path.dirname(managed_yaml)
    return os.path.join(dataset_dir, "audit", "events.jsonl")
