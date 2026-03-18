"""
Module: test_path_context
Layer: integration/migration
Covers: migrate/path_context.py

Verify migration helper paths stay anchored to repo-relative locations.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "migrate" / "path_context.py"


def _load_module():
    spec = spec_from_file_location("migrate.path_context", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_path_context_exposes_repo_relative_migration_paths():
    module = _load_module()

    assert module.REPO_ROOT == ROOT
    assert module.MIGRATE_ROOT == ROOT / "migrate"
    assert module.INPUTS_DIR == ROOT / "migrate" / "inputs"
    assert module.NORMALIZED_DIR == ROOT / "migrate" / "normalized"
    assert module.OUTPUT_DIR == ROOT / "migrate" / "output"
    assert module.DEFAULT_SOURCE_SHEET == ROOT / "migrate" / "normalized" / "source" / "sheets" / "01_Sheet1.csv"
    assert module.OUTPUT_YAML == ROOT / "migrate" / "output" / "ln2_inventory.yaml"
