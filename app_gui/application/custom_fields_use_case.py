"""Application use case for settings custom-fields editing."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lib.custom_fields import get_effective_fields, unsupported_box_fields_issue
from lib.custom_fields_update_service import (
    CustomFieldsUpdateDraft,
    build_custom_fields_update_audit_details,
    drop_removed_fields_from_inventory,
    prepare_custom_fields_update,
    validate_custom_fields_update_draft,
)
from lib.settings_write_gateway import persist_custom_fields_update
from lib.yaml_ops import load_yaml


@dataclass(frozen=True)
class CustomFieldsEditorState:
    """Normalized state used by the custom-fields editor workflow."""

    source_data: Dict[str, Any]
    meta: Dict[str, Any]
    inventory: List[Any]
    existing_fields: List[Dict[str, Any]]
    current_display_key: str
    current_color_key: str


@dataclass(frozen=True)
class CustomFieldsEditorLoadResult:
    """Result of loading one dataset for custom-fields editing."""

    state: CustomFieldsEditorState
    unsupported_issue: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CustomFieldsCommitResult:
    """Result of validating and persisting one prepared update draft."""

    ok: bool
    draft: CustomFieldsUpdateDraft
    meta_errors: List[str]
    warnings: List[str]
    error_code: str
    message: str
    persist_result: Dict[str, Any]
    removed_data_cleaned: bool
    removed_records_count: int


class CustomFieldsUseCase:
    """Coordinate settings custom-fields edits across core services."""

    def load_editor_state(self, *, yaml_path: str) -> CustomFieldsEditorLoadResult:
        try:
            data = load_yaml(yaml_path) or {}
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}

        inventory = data.get("inventory")
        if not isinstance(inventory, list):
            inventory = []

        issue = unsupported_box_fields_issue(meta)
        existing_fields = []
        if not issue:
            existing_fields = get_effective_fields(meta, inventory=inventory)

        state = CustomFieldsEditorState(
            source_data=data,
            meta=meta,
            inventory=inventory,
            existing_fields=existing_fields,
            current_display_key=str(meta.get("display_key") or "").strip(),
            current_color_key=str(meta.get("color_key") or "").strip(),
        )
        return CustomFieldsEditorLoadResult(
            state=state,
            unsupported_issue=issue,
        )

    def prepare_update(
        self,
        *,
        state: CustomFieldsEditorState,
        new_fields: Any,
        requested_display_key: Any,
        requested_color_key: Any,
    ) -> CustomFieldsUpdateDraft:
        return prepare_custom_fields_update(
            meta=state.meta,
            inventory=state.inventory,
            existing_fields=state.existing_fields,
            new_fields=new_fields,
            current_display_key=state.current_display_key,
            current_color_key=state.current_color_key,
            requested_display_key=requested_display_key,
            requested_color_key=requested_color_key,
        )

    def commit_update(
        self,
        *,
        yaml_path: str,
        state: CustomFieldsEditorState,
        draft: CustomFieldsUpdateDraft,
        remove_removed_field_data: bool = False,
    ) -> CustomFieldsCommitResult:
        removed_records_count = 0
        removed_data_cleaned = bool(remove_removed_field_data)
        if removed_data_cleaned:
            removed_records_count = drop_removed_fields_from_inventory(
                draft.pending_inventory,
                draft.removed_keys,
            )

        meta_errors, warnings = validate_custom_fields_update_draft(draft)
        meta_errors = list(meta_errors or [])
        warnings = list(warnings or [])
        if meta_errors:
            return CustomFieldsCommitResult(
                ok=False,
                draft=draft,
                meta_errors=meta_errors,
                warnings=warnings,
                error_code="validation_failed",
                message="Validation failed",
                persist_result={},
                removed_data_cleaned=removed_data_cleaned,
                removed_records_count=removed_records_count,
            )

        pending_data = dict(state.source_data) if isinstance(state.source_data, dict) else {}
        pending_data["meta"] = draft.pending_meta
        pending_data["inventory"] = draft.pending_inventory

        persist_result = persist_custom_fields_update(
            yaml_path=yaml_path,
            pending_data=pending_data,
            audit_details=build_custom_fields_update_audit_details(
                draft,
                removed_data_cleaned=removed_data_cleaned,
                removed_records_count=removed_records_count,
            ),
        )
        normalized_persist_result = dict(persist_result) if isinstance(persist_result, dict) else {}
        return CustomFieldsCommitResult(
            ok=bool(normalized_persist_result.get("ok")),
            draft=draft,
            meta_errors=meta_errors,
            warnings=warnings,
            error_code=str(normalized_persist_result.get("error_code") or ""),
            message=str(normalized_persist_result.get("message") or ""),
            persist_result=normalized_persist_result,
            removed_data_cleaned=removed_data_cleaned,
            removed_records_count=removed_records_count,
        )
