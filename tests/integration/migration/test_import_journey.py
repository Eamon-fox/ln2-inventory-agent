"""
Module: test_import_journey
Layer: integration/migration
Covers: lib/migration/import.py, app_gui/import_journey.py

统一导入流程与失败处理，验证从文件选择、工作区暂存、
XLSX 预转换到 AI 提示生成的完整导入旅程。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app_gui.import_journey import ImportJourneyService
from app_gui.migration_workspace import MigrationWorkspaceError
from app_gui.xlsx_preconvert import XlsxPreconvertResult


def _build_service():
    workspace = SimpleNamespace(
        stage_input_files=MagicMock(return_value=["D:/migrate/inputs/input.csv"]),
        workspace_root="D:/migrate",
        inputs_dir="D:/migrate/inputs",
        output_yaml_path="D:/migrate/output/ln2_inventory.yaml",
        session_checklist_path="D:/migrate/output/migration_checklist.md",
        normalized_dir="D:/migrate/normalized",
    )
    preconvert = SimpleNamespace(
        convert_staged_files=MagicMock(
            return_value=XlsxPreconvertResult(
                status="ok",
                message="XLSX pre-conversion succeeded.",
                normalized_root="D:/migrate/normalized",
                normalized_assets=[
                    "D:/migrate/normalized/conversion_report.json",
                    "D:/migrate/normalized/input/schema_summary.json",
                    "D:/migrate/normalized/input/sheets/01_Sheet1.csv",
                ],
                report_path="D:/migrate/normalized/conversion_report.json",
            )
        )
    )
    service = ImportJourneyService(
        workspace_service=workspace,
        preconvert_service=preconvert,
    )
    return service, workspace, preconvert


def test_run_cancels_when_no_source_files_selected():
    service, workspace, preconvert = _build_service()
    with patch(
        "app_gui.import_journey.QFileDialog.getOpenFileNames",
        return_value=([], ""),
    ):
        result = service.run(parent=None)

    assert result.ok is False
    assert result.error_code == "user_cancelled"
    assert result.stage == "failed"
    workspace.stage_input_files.assert_not_called()
    preconvert.convert_staged_files.assert_not_called()


def test_run_returns_stage_error_when_workspace_staging_fails():
    service, workspace, preconvert = _build_service()
    workspace.stage_input_files.side_effect = MigrationWorkspaceError("copy failed")
    with patch(
        "app_gui.import_journey.QFileDialog.getOpenFileNames",
        return_value=(["D:/tmp/a.csv"], ""),
    ):
        result = service.run(parent=None)

    assert result.ok is False
    assert result.error_code == "stage_failed"
    assert result.stage == "stage_inputs"
    preconvert.convert_staged_files.assert_not_called()


def test_run_success_stages_inputs_and_hands_off_to_ai():
    service, workspace, preconvert = _build_service()
    with patch(
        "app_gui.import_journey.QFileDialog.getOpenFileNames",
        return_value=(["D:/tmp/a.csv"], ""),
    ):
        result = service.run(parent=None)

    assert result.ok is True
    assert result.stage == "awaiting_ai"
    assert result.error_code == ""
    assert result.workspace_root == workspace.workspace_root
    assert result.output_yaml_path == workspace.output_yaml_path
    assert result.staged_input_paths == ["D:/migrate/inputs/input.csv"]
    assert result.preconvert_status == "ok"
    assert result.preconvert_report_path == "D:/migrate/normalized/conversion_report.json"
    assert result.normalized_assets
    assert result.normalized_root == workspace.normalized_dir
    assert "fs_read" in result.ai_prompt
    assert "use_skill" in result.ai_prompt
    assert "`migration`" in result.ai_prompt
    assert "XLSX pre-conversion" in result.ai_prompt
    assert "conversion_report.json" in result.ai_prompt
    assert "normalized" in result.ai_prompt
    assert "migration_checklist.md" in result.ai_prompt
    assert "repo-relative paths" in result.ai_prompt
    assert "expected_schema.json" in result.ai_prompt
    assert "APPROVE_MAPPING" in result.ai_prompt
    assert "REVISE_MAPPING" in result.ai_prompt
    assert "validate_migration_output" in result.ai_prompt
    assert "validation_report.json" in result.ai_prompt
    assert "import_migration_output" in result.ai_prompt
    assert "target_dataset_name" in result.ai_prompt
    assert "CONFIRM_IMPORT" in result.ai_prompt
    workspace.stage_input_files.assert_called_once_with(["D:/tmp/a.csv"])
    preconvert.convert_staged_files.assert_called_once_with(
        ["D:/migrate/inputs/input.csv"],
        normalized_root="D:/migrate/normalized",
    )
