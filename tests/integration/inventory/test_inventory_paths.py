"""
Module: test_inventory_paths
Layer: integration/inventory
Covers: lib/tool_api.py

库存路径解析与文件定位
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.inventory_paths import (
    build_dataset_delete_payload,
    build_dataset_rename_payload,
    InventoryPathError,
    assert_allowed_inventory_yaml_path,
    create_managed_dataset_yaml_path,
    delete_managed_dataset_yaml_path,
    ensure_inventories_root,
    inventory_lock_enabled,
    list_managed_datasets,
    managed_dataset_name_from_yaml_path,
    rename_managed_dataset_yaml_path,
)
from lib import yaml_ops


def _enable_frozen(monkeypatch, install_dir):
    exe_path = install_dir / "SnowFox.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))


def _write_inventory(path):
    payload = {
        "meta": {
            "version": "1.0",
            "box_layout": {
                "rows": 1,
                "cols": 1,
                "box_count": 1,
            },
            "custom_fields": [],
            "cell_line_required": True,
        },
        "inventory": [],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)


def test_assert_allowed_inventory_yaml_path_blocks_external_when_locked(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)

    managed_yaml = create_managed_dataset_yaml_path("dataset-a")
    _write_inventory(managed_yaml)

    assert assert_allowed_inventory_yaml_path(managed_yaml, must_exist=True) == os.path.abspath(managed_yaml)

    outside_yaml = tmp_path / "outside" / "inventory.yaml"
    _write_inventory(str(outside_yaml))
    with pytest.raises(InventoryPathError):
        assert_allowed_inventory_yaml_path(str(outside_yaml), must_exist=True)


def test_list_managed_datasets_without_migration(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)

    dataset_yaml = create_managed_dataset_yaml_path("dataset-b")
    _write_inventory(dataset_yaml)

    rows = list_managed_datasets()
    assert len(rows) == 1
    assert rows[0]["name"].startswith("dataset-b")
    assert rows[0]["yaml_path"] == dataset_yaml

    source_yaml = tmp_path / "legacy" / "legacy.yaml"
    _write_inventory(str(source_yaml))
    with pytest.raises(InventoryPathError):
        assert_allowed_inventory_yaml_path(str(source_yaml), must_exist=True)


def test_inventory_lock_enabled_in_source_mode():
    assert inventory_lock_enabled() is True


def test_yaml_ops_uses_dataset_local_audit_and_backup_paths_when_locked(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    ensure_inventories_root()

    managed_yaml = create_managed_dataset_yaml_path("dataset-local")
    _write_inventory(managed_yaml)

    dataset_dir = os.path.dirname(os.path.abspath(managed_yaml))
    expected_backup_dir = os.path.join(dataset_dir, "backups")
    expected_audit_path = os.path.join(dataset_dir, "audit", "events.jsonl")

    assert yaml_ops.get_instance_backup_dir(managed_yaml) == expected_backup_dir
    assert yaml_ops.get_instance_audit_path(managed_yaml) == expected_audit_path
    assert yaml_ops.get_audit_log_path(managed_yaml) == expected_audit_path


def test_rename_managed_dataset_yaml_path_moves_whole_dataset(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    ensure_inventories_root()

    source_yaml = create_managed_dataset_yaml_path("rename-src")
    _write_inventory(source_yaml)
    source_dir = Path(source_yaml).resolve().parent
    (source_dir / "backups").mkdir(parents=True, exist_ok=True)
    (source_dir / "backups" / "seed.bak").write_text("seed", encoding="utf-8")
    (source_dir / "audit").mkdir(parents=True, exist_ok=True)
    (source_dir / "audit" / "events.jsonl").write_text("{}", encoding="utf-8")

    target_yaml = rename_managed_dataset_yaml_path(source_yaml, "rename-target")
    target_dir = Path(target_yaml).resolve().parent

    assert managed_dataset_name_from_yaml_path(target_yaml) == "rename-target"
    assert not source_dir.exists()
    assert (target_dir / "inventory.yaml").is_file()
    assert (target_dir / "backups" / "seed.bak").is_file()
    assert (target_dir / "audit" / "events.jsonl").is_file()


def test_rename_managed_dataset_yaml_path_rejects_name_conflict(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("rename-src2")
    _write_inventory(source_yaml)
    target_yaml = create_managed_dataset_yaml_path("rename-target2")
    _write_inventory(target_yaml)

    with pytest.raises(InventoryPathError) as exc:
        rename_managed_dataset_yaml_path(source_yaml, "rename-target2")
    assert exc.value.code == "dataset_name_conflict"


def test_rename_managed_dataset_yaml_path_rejects_unchanged_name(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("rename-src3")
    _write_inventory(source_yaml)

    with pytest.raises(InventoryPathError) as exc:
        rename_managed_dataset_yaml_path(source_yaml, "rename-src3")
    assert exc.value.code == "dataset_name_unchanged"


def test_rename_managed_dataset_yaml_path_rejects_invalid_name(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("rename-src-invalid")
    _write_inventory(source_yaml)

    with pytest.raises(InventoryPathError) as exc:
        rename_managed_dataset_yaml_path(source_yaml, "   ")
    assert exc.value.code == "invalid_dataset_name"


def test_rename_payload_contains_old_and_new_paths(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("rename-src4")
    _write_inventory(source_yaml)
    target_yaml = rename_managed_dataset_yaml_path(source_yaml, "rename-target4")

    details = build_dataset_rename_payload(source_yaml, target_yaml)
    assert details["kind"] == "dataset_rename"
    assert details["old_dataset_name"] == "rename-src4"
    assert details["new_dataset_name"] == "rename-target4"
    old_parts = Path(details["old_yaml_path"]).parts
    new_parts = Path(details["new_yaml_path"]).parts
    assert tuple(old_parts[-3:]) == ("inventories", "rename-src4", "inventory.yaml")
    assert tuple(new_parts[-3:]) == ("inventories", "rename-target4", "inventory.yaml")


def test_delete_managed_dataset_yaml_path_removes_dataset_tree(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("delete-src")
    _write_inventory(source_yaml)

    source_dir = Path(source_yaml).resolve().parent
    (source_dir / "backups").mkdir(parents=True, exist_ok=True)
    (source_dir / "backups" / "seed.bak").write_text("seed", encoding="utf-8")
    (source_dir / "audit").mkdir(parents=True, exist_ok=True)
    (source_dir / "audit" / "events.jsonl").write_text("{}", encoding="utf-8")

    deleted = delete_managed_dataset_yaml_path(source_yaml)
    assert deleted["dataset_name"] == "delete-src"
    assert deleted["yaml_path"] == os.path.abspath(source_yaml)
    assert not source_dir.exists()


def test_delete_managed_dataset_yaml_path_maps_delete_failure(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    source_yaml = create_managed_dataset_yaml_path("delete-src-failure")
    _write_inventory(source_yaml)

    def _raise_delete_error(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr("lib.inventory_paths.shutil.rmtree", _raise_delete_error)
    with pytest.raises(InventoryPathError) as exc:
        delete_managed_dataset_yaml_path(source_yaml)
    assert exc.value.code == "dataset_delete_failed"
    assert "dataset_name" in exc.value.details


def test_delete_payload_contains_deleted_and_switched_paths(monkeypatch, tmp_path):
    _enable_frozen(monkeypatch, tmp_path)
    deleted_yaml = create_managed_dataset_yaml_path("delete-src-payload")
    switched_yaml = create_managed_dataset_yaml_path("delete-target-payload")
    _write_inventory(deleted_yaml)
    _write_inventory(switched_yaml)

    details = build_dataset_delete_payload(deleted_yaml, switched_yaml)
    assert details["kind"] == "dataset_delete"
    assert details["deleted_dataset_name"] == "delete-src-payload"
    assert details["switched_dataset_name"] == "delete-target-payload"
    deleted_parts = Path(details["deleted_yaml_path"]).parts
    switched_parts = Path(details["switched_yaml_path"]).parts
    assert tuple(deleted_parts[-3:]) == ("inventories", "delete-src-payload", "inventory.yaml")
    assert tuple(switched_parts[-3:]) == ("inventories", "delete-target-payload", "inventory.yaml")
