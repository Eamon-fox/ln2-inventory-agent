"""Unified import journey orchestration for GUI entrypoints."""

import os
from dataclasses import dataclass, field
from typing import Dict, List

from PySide6.QtWidgets import QFileDialog

from app_gui.i18n import t, tr
from app_gui.import_state import ImportJourneyState
from app_gui.migration_workspace import MigrationWorkspaceError, MigrationWorkspaceService
from app_gui.xlsx_preconvert import XlsxPreconvertResult, XlsxPreconvertService


@dataclass
class ImportJourneyResult:
    ok: bool
    stage: str
    message: str
    error_code: str = ""
    staged_input_paths: List[str] = field(default_factory=list)
    workspace_root: str = ""
    output_yaml_path: str = ""
    ai_prompt: str = ""
    normalized_root: str = ""
    normalized_assets: List[str] = field(default_factory=list)
    preconvert_status: str = "skipped"
    preconvert_message: str = ""
    preconvert_report_path: str = ""
    validation_report: Dict[str, object] = field(default_factory=dict)


class ImportJourneyService:
    """Stage migration input files, then hand off migration/import to AI."""

    def __init__(
        self,
        *,
        workspace_service: MigrationWorkspaceService,
        preconvert_service: XlsxPreconvertService = None,
    ):
        self._workspace = workspace_service
        self._preconvert = preconvert_service or XlsxPreconvertService()

    def run(self, *, parent=None) -> ImportJourneyResult:
        state = ImportJourneyState(stage="collect_sources")
        sources = self._pick_source_files(parent)
        if not sources:
            return self._result_from_state(
                state,
                ok=False,
                stage="failed",
                error_code="user_cancelled",
                message=tr("common.cancel"),
            )

        state.source_paths = list(sources)
        state.set_stage("stage_inputs")
        try:
            staged_inputs = self._workspace.stage_input_files(sources)
        except MigrationWorkspaceError as exc:
            return self._result_from_state(
                state,
                ok=False,
                stage="stage_inputs",
                error_code="stage_failed",
                message=t("main.importStageFailed", message=str(exc)),
            )

        state.set_stage("preconvert_inputs")
        preconvert_result = self._run_preconvert(staged_inputs)

        return self._result_from_state(
            state,
            ok=True,
            stage="awaiting_ai",
            message=tr("main.importJourneyStaged"),
            staged_input_paths=staged_inputs,
            workspace_root=self._workspace.workspace_root,
            output_yaml_path=self._workspace.output_yaml_path,
            ai_prompt=self._build_ai_prompt(staged_inputs, preconvert_result),
            normalized_root=preconvert_result.normalized_root,
            normalized_assets=preconvert_result.normalized_assets,
            preconvert_status=preconvert_result.status,
            preconvert_message=preconvert_result.message,
            preconvert_report_path=preconvert_result.report_path,
        )

    def _pick_source_files(self, parent):
        paths, _ = QFileDialog.getOpenFileNames(
            parent,
            tr("main.importSelectSourcesTitle"),
            "",
            tr("main.allFilesFilter"),
        )
        return [str(p or "").strip() for p in (paths or []) if str(p or "").strip()]

    def _run_preconvert(self, staged_inputs: List[str]) -> XlsxPreconvertResult:
        normalized_root = str(getattr(self._workspace, "normalized_dir", "") or "").strip()
        if not normalized_root:
            return XlsxPreconvertResult(
                status="skipped",
                message="Normalized workspace is unavailable; staged files will be used directly.",
            )

        try:
            return self._preconvert.convert_staged_files(
                staged_inputs,
                normalized_root=normalized_root,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return XlsxPreconvertResult(
                status="failed",
                message=f"XLSX pre-conversion failed: {exc}. Fallback to staged raw files.",
                normalized_root=normalized_root,
            )

    def _build_ai_prompt(self, staged_inputs: List[str], preconvert: XlsxPreconvertResult) -> str:
        output_yaml = self._display_path(self._workspace.output_yaml_path)
        input_root = self._display_path(self._workspace.inputs_dir)
        listed_inputs = [f"- {self._display_path(path)}" for path in list(staged_inputs or [])]
        if not listed_inputs:
            listed_inputs = ["- (no files staged)"]
        normalized_root = self._display_path(getattr(preconvert, "normalized_root", ""))
        normalized_assets = [
            f"- {self._display_path(path)}"
            for path in list(getattr(preconvert, "normalized_assets", []) or [])
        ]
        if not normalized_assets:
            normalized_assets = ["- (none)"]
        report_path = self._display_path(getattr(preconvert, "report_path", ""))
        checklist_path = self._display_path(getattr(self._workspace, "session_checklist_path", ""))
        preconvert_status = str(getattr(preconvert, "status", "") or "").strip() or "skipped"
        preconvert_message = str(getattr(preconvert, "message", "") or "").strip()
        if not preconvert_message:
            preconvert_message = "(no message)"
        lines = [
            "Run migration for the staged legacy data files.",
            f"Input workspace: {input_root}",
            f"Target output YAML: {output_yaml}",
            "Staged files:",
            *listed_inputs,
            "",
            "XLSX pre-conversion:",
            f"- status: {preconvert_status}",
            f"- message: {preconvert_message}",
            f"- normalized workspace: {normalized_root or '(none)'}",
            f"- conversion report: {report_path or '(none)'}",
            "Normalized assets:",
            *normalized_assets,
            f"Session checklist: {checklist_path or 'migrate/output/migration_checklist.md'}",
            "",
            "Execution protocol:",
            "1) First call use_skill with `skill_name` set to `migration`.",
            "2) Scope boundary: work ONLY within migrate/inputs/, migrate/normalized/, and migrate/output/. Do NOT read inventories/ or any existing managed dataset unless the user explicitly asks to compare.",
            "3) Follow the returned skill instructions and read any referenced skill documents you need.",
            "4) If a conversion report is available, call fs_read on it and prioritize normalized CSV/schema assets.",
            "5) If pre-conversion is failed/partial or required sheets are missing, fall back to staged raw files.",
            "6) Read and maintain migrate/output/migration_checklist.md as live progress (check items as completed).",
            "7) Run precheck and propose field mapping + schema plan for migrate/output/expected_schema.json, including optional box_tags mapping when source labels exist.",
            "8) Ask user to approve mapping via question, include options `APPROVE_MAPPING` and `REVISE_MAPPING`.",
            "9) Only after user selects `APPROVE_MAPPING`, lock expected_schema and convert source materials into migrate/output/ln2_inventory.yaml.",
            "10) Use validate_migration_output only to verify strict import readiness; if failed, repair and re-run validation.",
            "11) Confirm migrate/output/validation_report.json is refreshed by validate_migration_output, then update checklist status before import confirmation.",
            "12) Ask user for target dataset name via question, then keep that exact answer for `target_dataset_name`.",
            "13) Before importing, call question and include option `CONFIRM_IMPORT` for explicit user approval.",
            "14) Only after user selects CONFIRM_IMPORT, call import_migration_output with confirmation_token=CONFIRM_IMPORT and target_dataset_name=<from step 12>.",
            "15) Report final imported dataset path after the import tool succeeds.",
        ]
        return "\n".join(lines)

    def _display_path(self, path_text) -> str:
        path = str(path_text or "").strip()
        if not path:
            return ""
        absolute = os.path.abspath(path)
        repo_root = self._repo_root()
        if repo_root:
            try:
                relative = os.path.relpath(absolute, repo_root)
                if not relative.startswith(".."):
                    return relative.replace("\\", "/")
            except Exception:
                pass
        return absolute.replace("\\", "/")

    def _repo_root(self) -> str:
        workspace_root = str(getattr(self._workspace, "workspace_root", "") or "").strip()
        if not workspace_root:
            return ""
        return os.path.abspath(os.path.dirname(workspace_root))

    @staticmethod
    def _result_from_state(
        state: ImportJourneyState,
        *,
        ok: bool,
        stage: str,
        message: str,
        error_code: str = "",
        staged_input_paths=None,
        workspace_root: str = "",
        output_yaml_path: str = "",
        ai_prompt: str = "",
        normalized_root: str = "",
        normalized_assets=None,
        preconvert_status: str = "skipped",
        preconvert_message: str = "",
        preconvert_report_path: str = "",
    ) -> ImportJourneyResult:
        state.set_stage(stage)
        state.message = str(message or "")
        state.error_code = str(error_code or "")
        state.source_paths = list(staged_input_paths or state.source_paths or [])
        state.candidate_yaml = str(output_yaml_path or state.candidate_yaml or "")
        return ImportJourneyResult(
            ok=bool(ok),
            stage=state.stage,
            message=state.message,
            error_code=state.error_code,
            staged_input_paths=list(state.source_paths or []),
            workspace_root=str(workspace_root or ""),
            output_yaml_path=state.candidate_yaml,
            ai_prompt=str(ai_prompt or ""),
            normalized_root=str(normalized_root or ""),
            normalized_assets=list(normalized_assets or []),
            preconvert_status=str(preconvert_status or "skipped"),
            preconvert_message=str(preconvert_message or ""),
            preconvert_report_path=str(preconvert_report_path or ""),
            validation_report=dict(state.validation_report or {}),
        )
