"""
Module: test_path_policy
Layer: contract
Covers: lib/path_policy.py

路径逃逸与安全策略执行，验证仓库读写路径的逃逸检测、
绝对路径拒绝、工作目录作用域限制以及数据集备份路径的安全控制。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.path_policy import (
    PathPolicyError,
    normalize_repo_roots,
    resolve_dataset_backup_read_path,
    resolve_dataset_backup_request_path,
    resolve_repo_read_path,
    resolve_repo_workdir_path,
    resolve_repo_write_path,
)
from tests.managed_paths import ManagedPathTestCase


def test_resolve_repo_read_path_blocks_escape(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(PathPolicyError) as exc:
        resolve_repo_read_path(repo, "../outside.txt")
    assert exc.value.code == "path.escape_detected"


def test_resolve_repo_read_path_blocks_absolute_input(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(PathPolicyError) as exc:
        resolve_repo_read_path(repo, str((tmp_path / "outside.txt").resolve()))
    assert exc.value.code == "path.absolute_not_allowed"


def test_resolve_repo_write_path_requires_migrate_scope(tmp_path):
    repo = tmp_path / "repo"
    migrate = repo / "migrate"
    migrate.mkdir(parents=True)

    allowed = resolve_repo_write_path(repo, migrate, "migrate/data/input.txt")
    assert str(allowed).startswith(str(migrate.resolve()))

    with pytest.raises(PathPolicyError) as denied:
        resolve_repo_write_path(repo, migrate, "README_scope_test_2.txt")
    assert denied.value.code == "path.scope_write_denied"


def test_resolve_repo_workdir_path_defaults_to_migrate(tmp_path):
    repo = tmp_path / "repo"
    migrate = repo / "migrate"
    migrate.mkdir(parents=True)
    repo_root, migrate_root = normalize_repo_roots(repo, migrate)
    resolved = resolve_repo_workdir_path(repo_root, migrate_root, None)
    assert resolved == migrate_root


class PathPolicyDatasetTests(ManagedPathTestCase):
    def test_resolve_dataset_backup_request_path_keeps_scope(self):
        yaml_path = self.ensure_dataset_yaml("dataset-policy-a")
        resolved = resolve_dataset_backup_request_path(yaml_path, "manual.bak", allow_empty=False)
        expected = (Path(yaml_path).resolve().parent / "backups" / "manual.bak").resolve()
        assert resolved == expected

    def test_resolve_dataset_backup_request_path_rejects_outside(self):
        yaml_path = self.ensure_dataset_yaml("dataset-policy-b")
        outside = Path(yaml_path).resolve().parent / "outside.bak"
        with pytest.raises(PathPolicyError) as exc:
            resolve_dataset_backup_request_path(yaml_path, str(outside), allow_empty=False)
        assert exc.value.code == "path.backup_scope_denied"

    def test_resolve_dataset_backup_read_path_requires_existing_file(self):
        yaml_path = self.ensure_dataset_yaml("dataset-policy-c")
        with pytest.raises(PathPolicyError) as exc:
            resolve_dataset_backup_read_path(yaml_path, "missing.bak", must_exist=True, must_be_file=True)
        assert exc.value.code == "path.not_found"

    def test_resolve_dataset_backup_read_path_rejects_directory(self):
        yaml_path = self.ensure_dataset_yaml("dataset-policy-d")
        backup_dir = Path(yaml_path).resolve().parent / "backups" / "folder.bak"
        backup_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(PathPolicyError) as exc:
            resolve_dataset_backup_read_path(yaml_path, str(backup_dir), must_exist=True, must_be_file=True)
        assert exc.value.code == "path.not_file"
