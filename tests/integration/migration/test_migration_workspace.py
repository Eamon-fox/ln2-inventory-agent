"""
Module: test_migration_workspace
Layer: integration/migration
Covers: app_gui/migration_workspace.py

迁移工作区暂存与路径管理，验证工作区初始化、输入文件暂存、
输出清理、会话检查清单重置以及内部模板引导机制。
"""

import os
from pathlib import Path
import tempfile

import pytest

from app_gui.migration_workspace import MigrationWorkspaceError, MigrationWorkspaceService


def _create_workspace(root: Path):
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    template = root.parent / "agent_skills" / "migration" / "assets" / "acceptance_checklist_en.md"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        "# Session Checklist\n\n- [ ] Item A\n",
        encoding="utf-8",
    )


def test_workspace_init_requires_existing_root():
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "missing"
        with pytest.raises(MigrationWorkspaceError):
            MigrationWorkspaceService(str(missing))


def test_workspace_init_bootstraps_from_internal_layout_when_available():
    with tempfile.TemporaryDirectory() as td:
        install_root = Path(td) / "SnowFox"
        internal_migrate = install_root / "_internal" / "migrate"
        (internal_migrate / "inputs").mkdir(parents=True, exist_ok=True)
        (internal_migrate / "output").mkdir(parents=True, exist_ok=True)
        (internal_migrate / "README.md").write_text("workspace", encoding="utf-8")

        internal_template = (
            install_root
            / "_internal"
            / "agent_skills"
            / "migration"
            / "assets"
            / "acceptance_checklist_en.md"
        )
        internal_template.parent.mkdir(parents=True, exist_ok=True)
        internal_template.write_text("# Checklist\n", encoding="utf-8")

        requested_root = install_root / "migrate"
        svc = MigrationWorkspaceService(str(requested_root))

        assert os.path.samefile(svc.workspace_root, requested_root)
        assert (install_root / "migrate" / "inputs").is_dir()
        assert (install_root / "migrate" / "output").is_dir()
        assert Path(svc.session_checklist_path).parts[-3:] == (
            "migrate",
            "output",
            "migration_checklist.md",
        )

        src = Path(td) / "input.csv"
        src.write_text("A", encoding="utf-8")
        svc.stage_input_files([str(src)])
        assert (requested_root / "output" / "migration_checklist.md").is_file()


def test_workspace_init_recreates_missing_runtime_dirs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        root.mkdir(parents=True, exist_ok=True)
        template = root.parent / "agent_skills" / "migration" / "assets" / "acceptance_checklist_en.md"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("# Session Checklist\n", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))

        assert os.path.samefile(svc.workspace_root, root)
        assert (root / "inputs").is_dir()
        assert (root / "normalized").is_dir()
        assert (root / "output").is_dir()


def test_stage_input_files_resets_inputs_and_copies_sources():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        stale = root / "inputs" / "stale.txt"
        stale.write_text("old", encoding="utf-8")

        src_a = Path(td) / "a.csv"
        src_b = Path(td) / "b.csv"
        src_a.write_text("A", encoding="utf-8")
        src_b.write_text("B", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        copied = svc.stage_input_files([str(src_a), str(src_b)])

        assert len(copied) == 2
        copied_names = sorted(Path(p).name for p in copied)
        assert copied_names == ["a.csv", "b.csv"]
        assert not stale.exists()
        assert (root / "inputs" / "a.csv").read_text(encoding="utf-8") == "A"
        assert (root / "inputs" / "b.csv").read_text(encoding="utf-8") == "B"


def test_stage_input_files_dedupes_target_names():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        src_dir_1 = Path(td) / "x"
        src_dir_2 = Path(td) / "y"
        src_dir_1.mkdir()
        src_dir_2.mkdir()
        src_1 = src_dir_1 / "dup.txt"
        src_2 = src_dir_2 / "dup.txt"
        src_1.write_text("first", encoding="utf-8")
        src_2.write_text("second", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        copied = svc.stage_input_files([str(src_1), str(src_2)])

        copied_names = sorted(Path(p).name for p in copied)
        assert copied_names == ["dup.txt", "dup_2.txt"]


def test_stage_input_files_requires_existing_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        svc = MigrationWorkspaceService(str(root))

        with pytest.raises(MigrationWorkspaceError):
            svc.stage_input_files([os.path.join(td, "missing.csv")])


def test_stage_input_files_clears_stale_output_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        (root / "output" / "README.md").write_text("keep", encoding="utf-8")
        stale_yaml = root / "output" / "ln2_inventory.yaml"
        stale_report = root / "output" / "conversion_report.md"
        stale_normalized = root / "normalized" / "stale.csv"
        stale_yaml.write_text("old yaml", encoding="utf-8")
        stale_report.write_text("old report", encoding="utf-8")
        stale_normalized.parent.mkdir(parents=True, exist_ok=True)
        stale_normalized.write_text("old csv", encoding="utf-8")

        src = Path(td) / "input.csv"
        src.write_text("A", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        copied = svc.stage_input_files([str(src)])

        assert len(copied) == 1
        assert not stale_yaml.exists()
        assert not stale_report.exists()
        assert not stale_normalized.exists()
        assert (root / "output" / "README.md").exists()
        assert (root / "output" / "migration_checklist.md").is_file()
        assert (root / "normalized").is_dir()


def test_stage_input_files_resets_session_checklist_from_template():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        src = Path(td) / "input.csv"
        src.write_text("A", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        svc.stage_input_files([str(src)])

        checklist = root / "output" / "migration_checklist.md"
        assert checklist.is_file()
        assert "- [ ] Item A" in checklist.read_text(encoding="utf-8")


def test_stage_input_files_overwrites_existing_session_checklist():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        checklist = root / "output" / "migration_checklist.md"
        checklist.write_text("# Old\n\n- [x] Done\n", encoding="utf-8")

        src = Path(td) / "input.csv"
        src.write_text("A", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        svc.stage_input_files([str(src)])

        text = checklist.read_text(encoding="utf-8")
        assert "- [x] Done" not in text
        assert "- [ ] Item A" in text


def test_stage_input_files_fails_when_checklist_template_missing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "migrate"
        _create_workspace(root)
        template = root.parent / "agent_skills" / "migration" / "assets" / "acceptance_checklist_en.md"
        template.unlink()

        src = Path(td) / "input.csv"
        src.write_text("A", encoding="utf-8")

        svc = MigrationWorkspaceService(str(root))
        with pytest.raises(MigrationWorkspaceError):
            svc.stage_input_files([str(src)])
