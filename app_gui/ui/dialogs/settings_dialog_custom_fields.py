from __future__ import annotations

import os

from PySide6.QtWidgets import QDialog, QMessageBox

from app_gui.error_localizer import localize_error
from app_gui.i18n import t, tr
from app_gui.ui.dialogs.common import create_message_box, show_warning_message
from app_gui.ui.dialogs.settings_dialog_formatters import (
    format_removed_field_preview_details,
    format_removed_field_preview_summary,
)


def open_custom_fields_editor(
    dialog,
    *,
    destructive_button_cls,
    warning_func=show_warning_message,
) -> None:
    yaml_path = dialog.yaml_edit.text().strip()
    if not yaml_path or not os.path.isfile(yaml_path):
        warning_func(
            dialog,
            title=tr("common.info"),
            text=t("main.fileNotFound", path=yaml_path),
        )
        return

    load_result = dialog._custom_fields_use_case.load_editor_state(yaml_path=yaml_path)
    editor_state = load_result.state
    meta = editor_state.meta
    unsupported_issue = load_result.unsupported_issue
    if unsupported_issue:
        warning_func(
            dialog,
            title=tr("main.customFieldsTitle"),
            text=localize_error(
                unsupported_issue.get("error_code"),
                unsupported_issue.get("message"),
                details=unsupported_issue.get("details"),
            ),
        )
        return

    dialog_cls = dialog._custom_fields_dialog_cls
    if dialog_cls is None:
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog as dialog_cls
    picker = dialog_cls(
        dialog,
        custom_fields=editor_state.existing_fields,
        display_key=editor_state.current_display_key,
        color_key=editor_state.current_color_key,
    )
    if picker.exec() != QDialog.Accepted:
        return

    draft = dialog._custom_fields_use_case.prepare_update(
        state=editor_state,
        new_fields=picker.get_custom_fields(),
        requested_display_key=picker.get_display_key(),
        requested_color_key=picker.get_color_key(),
    )

    if draft.blocked_renames:
        sample_lines = []
        for item in draft.blocked_renames[:20]:
            reason = str(item.get("reason") or "").strip()
            kind = "fixed system field" if reason == "fixed_system_field" else "structural field"
            sample_lines.append(
                f"{item.get('from_key', '?')} -> {item.get('to_key', '?')}: target is a {kind}"
            )
        hidden_count = len(draft.blocked_renames) - len(sample_lines)
        detail_text = "\n".join(sample_lines)
        if hidden_count > 0:
            detail_text += f"\n... and {hidden_count} more blocked rename(s)"
        warning_func(
            dialog,
            title=tr("main.customFieldsTitle"),
            text=(
                "Field rename blocked. Fixed/system field names cannot be used as "
                f"rename targets.\n\n{detail_text}\n\nPlease choose a different custom field key."
            ),
        )
        return

    if draft.rename_conflicts:
        sample_lines = []
        for item in draft.rename_conflicts[:20]:
            sample_lines.append(
                f"id={item.get('record_id', '?')}: "
                f"{item['from_key']}={item['from_value']!r} vs {item['to_key']}={item['to_value']!r}"
            )
        hidden_count = len(draft.rename_conflicts) - len(sample_lines)
        detail_text = "\n".join(sample_lines)
        if hidden_count > 0:
            detail_text += f"\n... and {hidden_count} more conflict(s)"
        warning_func(
            dialog,
            title=tr("main.customFieldsTitle"),
            text=(
                "Field rename conflict detected. "
                f"The target field already contains different values.\n\n{detail_text}\n\n"
                "Please resolve conflicts in data before renaming."
            ),
        )
        return

    removed_data_cleaned = False
    if draft.removed_field_previews:
        box_layout = meta.get("box_layout") if isinstance(meta.get("box_layout"), dict) else None
        names = ", ".join(preview.field_key for preview in draft.removed_field_previews)
        detailed_text = None
        if any(preview.hidden_count for preview in draft.removed_field_previews):
            detailed_text = format_removed_field_preview_details(
                draft.removed_field_previews,
                layout=box_layout,
            )
        msg = create_message_box(
            dialog,
            title=tr("main.customFieldsTitle"),
            text=t("main.cfRemoveDataPrompt", fields=names),
            informative_text=format_removed_field_preview_summary(
                draft.removed_field_previews,
                layout=box_layout,
            ),
            detailed_text=detailed_text,
            icon=QMessageBox.Warning,
        )
        btn_clean = destructive_button_cls(tr("main.cfRemoveDataClean"), msg)
        btn_cancel = destructive_button_cls(tr("common.cancel"), msg)
        msg.addButton(btn_clean, QMessageBox.DestructiveRole)
        msg.addButton(btn_cancel, QMessageBox.RejectRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec()
        if msg.clickedButton() != btn_clean:
            return

        confirm_phrase = "DELETE"
        if not dialog._confirm_phrase_dialog(
            title=tr("main.customFieldsTitle"),
            prompt_text=t("main.cfRemoveDataConfirm", phrase=confirm_phrase),
            phrase=confirm_phrase,
            strip_input=True,
        ):
            return
        removed_data_cleaned = True

    commit_result = dialog._custom_fields_use_case.commit_update(
        yaml_path=yaml_path,
        state=editor_state,
        draft=draft,
        remove_removed_field_data=removed_data_cleaned,
    )
    if commit_result.meta_errors:
        dialog._show_validation_blocked_result(
            dialog._validation_failed_result(
                commit_result.meta_errors,
                prefix="Validation failed",
            )
        )
        return

    if not commit_result.ok:
        warning_func(
            dialog,
            title=tr("main.customFieldsTitle"),
            text=str(commit_result.message or "Failed to save custom fields."),
        )
        return

    dialog._notify_data_changed(yaml_path=yaml_path, meta=draft.pending_meta)
