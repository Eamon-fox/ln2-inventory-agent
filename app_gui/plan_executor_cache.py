from __future__ import annotations

import os
import tempfile
from copy import deepcopy

from lib.yaml_ops import load_yaml


_source_yaml_cache: dict = {}


def clear_write_through_cache() -> None:
    from lib.yaml_ops import _write_through_cache

    _write_through_cache.clear()


def load_source_yaml_cached(yaml_path):
    abs_path = os.path.abspath(yaml_path)
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return load_yaml(yaml_path)
    key = (abs_path, mtime)
    cached = _source_yaml_cache.get(key)
    if cached is not None:
        return deepcopy(cached)
    data = load_yaml(yaml_path)
    _source_yaml_cache.clear()
    _source_yaml_cache[key] = data
    return deepcopy(data)


def allocate_preflight_yaml_path(yaml_path: str):
    source_yaml = os.path.abspath(str(yaml_path or "").strip())
    source_dataset_dir = os.path.dirname(source_yaml)
    inventories_root = os.path.dirname(source_dataset_dir)
    preflight_dataset_dir = tempfile.mkdtemp(
        prefix="__preflight__",
        dir=inventories_root,
    )
    return preflight_dataset_dir, os.path.join(preflight_dataset_dir, "inventory.yaml")


_load_source_yaml_cached = load_source_yaml_cached
_allocate_preflight_yaml_path = allocate_preflight_yaml_path
