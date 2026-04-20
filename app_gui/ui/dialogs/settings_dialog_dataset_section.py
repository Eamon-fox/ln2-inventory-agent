from __future__ import annotations

from PySide6.QtCore import QSize, QSignalBlocker
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app_gui.i18n import t, tr
from app_gui.ui.dialogs.common import (
    configure_dialog,
    create_message_box,
    create_wrapping_label,
    show_warning_message,
)
from app_gui.ui.icons import Icons, get_icon


def build_dataset_group(dialog) -> QGroupBox:
    data_group = QGroupBox(tr("settings.data"))
    data_layout = QFormLayout(data_group)

    yaml_row = QHBoxLayout()
    dialog.yaml_edit = QLineEdit(dialog._config.get("yaml_path", ""))
    dialog._initial_yaml_path = dialog._normalize_yaml_path(
        dialog._config.get("yaml_path", "")
    )
    dialog.yaml_edit.setReadOnly(dialog._inventory_path_locked)
    dialog.yaml_new_btn = QPushButton(tr("main.new"))
    dialog.yaml_new_btn.setIcon(get_icon(Icons.FILE_PLUS))
    dialog.yaml_new_btn.setIconSize(QSize(14, 14))
    dialog.yaml_new_btn.setMinimumWidth(60)
    dialog.yaml_new_btn.clicked.connect(dialog._emit_create_new_dataset_request)
    yaml_row.addWidget(dialog.yaml_edit, 1)
    yaml_row.addWidget(dialog.yaml_new_btn)
    data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

    data_root_row = QHBoxLayout()
    dialog.data_root_edit = QLineEdit(dialog._config.get("data_root", ""))
    dialog.data_root_edit.setReadOnly(True)
    dialog.data_root_change_btn = QPushButton(tr("settings.changeDataRoot"))
    dialog.data_root_change_btn.clicked.connect(dialog._emit_change_data_root_request)
    dialog.data_root_change_btn.setEnabled(callable(dialog._on_change_data_root))
    data_root_row.addWidget(dialog.data_root_edit, 1)
    data_root_row.addWidget(dialog.data_root_change_btn)
    data_layout.addRow(tr("settings.dataRoot"), data_root_row)

    dialog.dataset_switch_combo = None
    dialog.dataset_rename_btn = None
    dialog.dataset_delete_btn = None
    switch_row = QHBoxLayout()
    dialog.dataset_switch_combo = dialog._combo_box_cls()
    dialog.dataset_switch_combo.currentIndexChanged.connect(dialog._on_dataset_switch_changed)
    switch_row.addWidget(dialog.dataset_switch_combo, 1)
    dialog.dataset_rename_btn = QPushButton(tr("settings.renameDataset"))
    dialog.dataset_rename_btn.clicked.connect(dialog._emit_rename_dataset_request)
    dialog.dataset_rename_btn.setEnabled(callable(dialog._on_rename_dataset))
    switch_row.addWidget(dialog.dataset_rename_btn)
    dialog.dataset_delete_btn = QPushButton(tr("settings.deleteDataset"))
    dialog.dataset_delete_btn.clicked.connect(dialog._emit_delete_dataset_request)
    dialog.dataset_delete_btn.setEnabled(callable(dialog._on_delete_dataset))
    switch_row.addWidget(dialog.dataset_delete_btn)
    data_layout.addRow(tr("settings.datasetSwitch"), switch_row)
    dialog._refresh_dataset_choices(selected_yaml=dialog.yaml_edit.text().strip())

    lock_hint = QLabel(tr("settings.inventoryFileLockedHint"))
    lock_hint.setProperty("role", "settingsHint")
    lock_hint.setWordWrap(True)
    data_layout.addRow("", lock_hint)

    data_root_hint = QLabel(tr("settings.dataRootHint"))
    data_root_hint.setProperty("role", "settingsHint")
    data_root_hint.setWordWrap(True)
    data_layout.addRow("", data_root_hint)

    tool_row = QHBoxLayout()
    cf_btn = QPushButton(tr("main.manageCustomFields"))
    cf_btn.clicked.connect(dialog._open_custom_fields_editor)
    tool_row.addWidget(cf_btn)

    box_btn = QPushButton(tr("main.manageBoxes"))
    box_btn.clicked.connect(dialog._open_manage_boxes)
    tool_row.addWidget(box_btn)

    import_btn = QPushButton(tr("main.importExistingDataTitle"))
    import_btn.setToolTip(tr("main.importExistingDataHint"))
    import_btn.clicked.connect(dialog._open_import_journey)
    tool_row.addWidget(import_btn)

    dialog.export_csv_btn = QPushButton(tr("operations.exportFullCsv"))
    dialog.export_csv_btn.setIcon(get_icon(Icons.DOWNLOAD))
    dialog.export_csv_btn.setIconSize(QSize(14, 14))
    dialog.export_csv_btn.setToolTip(tr("operations.exportFullCsvHint"))
    dialog.export_csv_btn.clicked.connect(dialog._open_export_inventory_csv)
    dialog.export_csv_btn.setEnabled(callable(dialog._on_export_inventory_csv))
    tool_row.addWidget(dialog.export_csv_btn)

    tool_row.addStretch()
    data_layout.addRow("", tool_row)
    return data_group


def refresh_dataset_choices(dialog, selected_yaml="") -> None:
    combo = getattr(dialog, "dataset_switch_combo", None)
    if combo is None:
        return
    items, selected_idx = dialog._settings_dataset_use_case.build_dataset_choices(
        selected_yaml=selected_yaml or dialog.yaml_edit.text().strip(),
    )
    with QSignalBlocker(combo):
        combo.clear()
        for label, path in items:
            combo.addItem(label, path)
        if selected_idx >= 0:
            combo.setCurrentIndex(selected_idx)
    if dialog.dataset_rename_btn is not None:
        dialog.dataset_rename_btn.setEnabled(bool(items) and callable(dialog._on_rename_dataset))
    if dialog.dataset_delete_btn is not None:
        dialog.dataset_delete_btn.setEnabled(bool(items) and callable(dialog._on_delete_dataset))


def on_dataset_switch_changed(dialog) -> None:
    if dialog.dataset_switch_combo is None:
        return
    selected_path = dialog.dataset_switch_combo.currentData()
    if selected_path:
        dialog.yaml_edit.setText(str(selected_path))
        dialog._refresh_yaml_path_validity()


def emit_create_new_dataset_request(dialog) -> None:
    if not callable(dialog._on_create_new_dataset):
        return
    new_path = dialog._on_create_new_dataset(update_window=True)
    if new_path:
        dialog.yaml_edit.setText(dialog._normalize_yaml_path(new_path))
        dialog._refresh_dataset_choices(selected_yaml=new_path)


def emit_change_data_root_request(dialog) -> None:
    if not callable(dialog._on_change_data_root):
        return
    result = dialog._on_change_data_root(dialog.data_root_edit.text().strip())
    if not isinstance(result, dict):
        return
    new_root = str(result.get("data_root") or "").strip()
    new_yaml = str(result.get("yaml_path") or "").strip()
    if new_root:
        dialog.data_root_edit.setText(new_root)
        dialog._config["data_root"] = new_root
    if new_yaml:
        dialog.yaml_edit.setText(dialog._normalize_yaml_path(new_yaml))
        dialog._initial_yaml_path = dialog._normalize_yaml_path(new_yaml)
    dialog._refresh_dataset_choices(
        selected_yaml=new_yaml or dialog.yaml_edit.text().strip(),
    )


def emit_rename_dataset_request(
    dialog,
    *,
    qinputdialog_cls,
    warning_func=show_warning_message,
) -> None:
    if not callable(dialog._on_rename_dataset):
        return

    current_yaml = dialog._normalize_yaml_path(dialog.yaml_edit.text().strip())
    if not current_yaml:
        return

    default_name = dialog._settings_dataset_use_case.managed_dataset_name(
        yaml_path=current_yaml,
    )
    new_name, ok = qinputdialog_cls.getText(
        dialog,
        tr("settings.renameDataset"),
        tr("settings.renameDatasetPrompt"),
        text=default_name,
    )
    if not ok:
        return

    try:
        new_path = dialog._on_rename_dataset(current_yaml, str(new_name or ""))
    except Exception as exc:
        warning_func(
            dialog,
            title=tr("settings.renameDataset"),
            text=t("settings.renameDatasetFailed", error=str(exc)),
        )
        return

    if new_path:
        dialog.yaml_edit.setText(dialog._normalize_yaml_path(new_path))
        dialog._refresh_dataset_choices(selected_yaml=new_path)


def confirm_phrase_dialog(
    dialog,
    *,
    title,
    prompt_text,
    phrase,
    line_edit_cls,
    dialog_cls,
    label_cls=QLabel,
    button_cls=QPushButton,
    dialog_button_box_cls=QDialogButtonBox,
    strip_input=False,
):
    confirm_dlg = dialog_cls(dialog)
    confirm_dlg.setWindowTitle(title)
    configure_dialog(confirm_dlg)
    confirm_layout = QVBoxLayout(confirm_dlg)

    if label_cls is QLabel:
        confirm_label = create_wrapping_label(prompt_text)
    else:
        confirm_label = label_cls(prompt_text)
        confirm_label.setWordWrap(True)
    confirm_layout.addWidget(confirm_label)

    confirm_input = line_edit_cls()
    confirm_input.setPlaceholderText(phrase)
    confirm_layout.addWidget(confirm_input)

    confirm_buttons = dialog_button_box_cls()
    ok_btn = button_cls(tr("common.ok"))
    ok_btn.setEnabled(False)
    ok_btn.clicked.connect(confirm_dlg.accept)
    confirm_buttons.addButton(ok_btn, dialog_button_box_cls.AcceptRole)
    cancel_btn = button_cls(tr("common.cancel"))
    cancel_btn.clicked.connect(confirm_dlg.reject)
    confirm_buttons.addButton(cancel_btn, dialog_button_box_cls.RejectRole)
    confirm_layout.addWidget(confirm_buttons)

    def _matches(text):
        candidate = str(text or "")
        if strip_input:
            candidate = candidate.strip()
        return candidate == phrase

    confirm_input.textChanged.connect(lambda txt: ok_btn.setEnabled(_matches(txt)))
    if confirm_dlg.exec() != dialog_cls.Accepted:
        return False
    return _matches(confirm_input.text())


def emit_delete_dataset_request(
    dialog,
    *,
    warning_func=show_warning_message,
) -> None:
    if not callable(dialog._on_delete_dataset):
        return

    current_yaml = dialog._normalize_yaml_path(dialog.yaml_edit.text().strip())
    if not current_yaml:
        return

    dataset_name = dialog._settings_dataset_use_case.managed_dataset_name(
        yaml_path=current_yaml,
    )

    if not dialog._confirm_delete_dataset_initial(dataset_name):
        return

    confirm_phrase = t("settings.deleteDatasetPhrase", name=dataset_name)
    phrase_prompt = t("settings.deleteDatasetPhrasePrompt", phrase=confirm_phrase)
    if not dialog._confirm_phrase_dialog(
        title=tr("settings.deleteDataset"),
        prompt_text=phrase_prompt,
        phrase=confirm_phrase,
        strip_input=False,
    ):
        return

    if not dialog._confirm_delete_dataset_final(dataset_name):
        return

    try:
        new_path = dialog._on_delete_dataset(current_yaml)
    except Exception as exc:
        warning_func(
            dialog,
            title=tr("settings.deleteDataset"),
            text=t("settings.deleteDatasetFailed", error=str(exc)),
        )
        return

    if new_path:
        dialog.yaml_edit.setText(dialog._normalize_yaml_path(new_path))
        dialog._refresh_dataset_choices(selected_yaml=new_path)


def confirm_delete_dataset_initial(dialog, dataset_name, *, message_box_cls=QMessageBox):
    first_confirm = create_message_box(
        dialog,
        title=tr("settings.deleteDataset"),
        text=t("settings.deleteDatasetPrompt", name=dataset_name),
        informative_text=tr("settings.deleteDatasetPromptDetail"),
        icon=message_box_cls.Warning,
        message_box_cls=message_box_cls,
    )
    delete_btn = first_confirm.addButton(
        tr("settings.deleteDatasetAction"),
        message_box_cls.DestructiveRole,
    )
    cancel_btn = first_confirm.addButton(tr("common.cancel"), message_box_cls.RejectRole)
    first_confirm.setDefaultButton(cancel_btn)
    first_confirm.exec()
    return first_confirm.clickedButton() == delete_btn


def confirm_delete_dataset_final(dialog, dataset_name, *, message_box_cls=QMessageBox):
    final_confirm = create_message_box(
        dialog,
        title=tr("settings.deleteDataset"),
        text=t("settings.deleteDatasetFinalPrompt", name=dataset_name),
        icon=message_box_cls.Critical,
        message_box_cls=message_box_cls,
    )
    final_delete_btn = final_confirm.addButton(
        tr("settings.deleteDatasetAction"),
        message_box_cls.DestructiveRole,
    )
    cancel_btn = final_confirm.addButton(tr("common.cancel"), message_box_cls.RejectRole)
    final_confirm.setDefaultButton(cancel_btn)
    final_confirm.exec()
    return final_confirm.clickedButton() == final_delete_btn
