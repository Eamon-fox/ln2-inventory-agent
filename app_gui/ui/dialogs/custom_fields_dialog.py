"""Custom fields dialog extracted from main window module."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import t, tr

_FIELD_TYPES = ["str", "int", "float", "date"]
_SYSTEM_NOTE_KEY = "note"
_OPTIONS_EMPTY_TEXT = "..."


def _merge_legacy_cell_line_into_fields(custom_fields, cell_line_options, cell_line_required):
    """Build effective fields using custom definitions + optional legacy policy."""
    from lib.custom_fields import get_effective_fields

    meta = {"custom_fields": list(custom_fields or [])}
    if cell_line_options is not None:
        meta["cell_line_options"] = list(cell_line_options or [])
    if cell_line_required is not None:
        meta["cell_line_required"] = bool(cell_line_required)
    return get_effective_fields(meta)


class CustomFieldsDialog(QDialog):
    """Visual editor for meta.custom_fields."""

    def __init__(
        self,
        parent=None,
        custom_fields=None,
        display_key=None,
        color_key=None,
        cell_line_options=None,
        cell_line_required=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("main.customFieldsTitle"))
        self.setMinimumWidth(620)
        self.setMinimumHeight(400)

        root = QVBoxLayout(self)

        desc = QLabel(tr("main.customFieldsDesc"))
        desc.setWordWrap(True)
        desc.setProperty("role", "dialogHint")
        root.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        fields_group = QGroupBox(tr("main.cfFields"))
        fields_layout = QVBoxLayout(fields_group)
        fields_layout.setContentsMargins(8, 4, 8, 4)
        fields_layout.setSpacing(6)

        header = QWidget()
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.setSpacing(4)
        for text, width in [
            (tr("main.cfKey"), 140),
            (tr("main.cfLabel"), 120),
            (tr("main.cfType"), 70),
            (tr("main.cfDefault"), 100),
        ]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setProperty("role", "cfHeaderLabel")
            header_l.addWidget(lbl)
        req_lbl = QLabel(tr("main.cfRequired"))
        req_lbl.setProperty("role", "cfHeaderLabel")
        header_l.addWidget(req_lbl)
        action_lbl = QLabel()
        action_lbl.setFixedWidth(100)
        header_l.addWidget(action_lbl)
        fields_layout.addWidget(header)

        structural_display = [
            ("id", "ID", "int", True),
            ("box", "Box", "int", True),
            ("position", "Position", "int", True),
            ("frozen_at", "Frozen At", "date", True),
            ("thaw_events", "Takeout Events", "str", True),
        ]
        for s_key, s_label, s_type, s_required in structural_display:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            k_edit = QLineEdit(s_key)
            k_edit.setFixedWidth(140)
            k_edit.setReadOnly(True)
            k_edit.setEnabled(False)
            row_l.addWidget(k_edit)

            l_edit = QLineEdit(s_label)
            l_edit.setFixedWidth(120)
            l_edit.setReadOnly(True)
            l_edit.setEnabled(False)
            row_l.addWidget(l_edit)

            t_combo = QComboBox()
            t_combo.addItem(s_type)
            t_combo.setFixedWidth(70)
            t_combo.setEnabled(False)
            row_l.addWidget(t_combo)

            d_edit = QLineEdit()
            d_edit.setFixedWidth(100)
            d_edit.setEnabled(False)
            row_l.addWidget(d_edit)

            r_cb = QCheckBox(tr("main.cfRequired"))
            r_cb.setChecked(bool(s_required))
            r_cb.setEnabled(False)
            row_l.addWidget(r_cb)

            spacer = QWidget()
            spacer.setFixedWidth(100)
            row_l.addWidget(spacer)
            fields_layout.addWidget(row_w)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        fields_layout.addLayout(self._rows_layout)

        self._field_rows = []

        effective = _merge_legacy_cell_line_into_fields(
            custom_fields,
            cell_line_options,
            cell_line_required,
        )
        for field in effective:
            key = field.get("key", "")
            self._add_row(
                key,
                field.get("label", ""),
                field.get("type", "str"),
                field.get("default"),
                required=field.get("required", False),
                options=field.get("options"),
                original_key=key,
            )

        add_btn = QPushButton(tr("main.cfAdd"))
        add_btn.clicked.connect(self._on_add_row_clicked)
        fields_layout.addWidget(add_btn)

        scroll_layout.addWidget(fields_group)
        scroll_layout.addStretch()

        dk_row = QHBoxLayout()
        dk_row.addWidget(QLabel(tr("main.cfDisplayKey")))
        self._display_key_combo = QComboBox()
        self._refresh_display_key_combo(display_key)
        dk_row.addWidget(self._display_key_combo, 1)
        root.addLayout(dk_row)

        ck_row = QHBoxLayout()
        ck_row.addWidget(QLabel(tr("main.cfColorKey")))
        self._color_key_combo = QComboBox()
        self._refresh_color_key_combo(color_key)
        ck_row.addWidget(self._color_key_combo, 1)
        root.addLayout(ck_row)
        self._sync_selector_combos()

        buttons = QDialogButtonBox()
        ok_btn = QPushButton(tr("common.ok"))
        ok_btn.clicked.connect(self.accept)
        buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.clicked.connect(self.reject)
        buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        root.addWidget(buttons)

    def _refresh_display_key_combo(self, current_dk=None):
        combo = self._display_key_combo
        previous = current_dk if current_dk is not None else combo.currentData()
        combo.clear()
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if previous:
            idx = combo.findData(previous)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _refresh_color_key_combo(self, current_ck=None):
        combo = self._color_key_combo
        previous = current_ck if current_ck is not None else combo.currentData()
        combo.clear()
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if previous:
            idx = combo.findData(previous)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def get_display_key(self):
        return self._display_key_combo.currentData() or ""

    def get_color_key(self):
        return self._color_key_combo.currentData() or ""

    def get_cell_line_options(self):
        """Backward compat: extract options from the cell_line field row."""
        for entry in self._field_rows:
            if entry["key"].text().strip() == "cell_line":
                return list(entry.get("_options_data") or [])
        return []

    def get_cell_line_required(self):
        """Backward compat: extract required from the cell_line field row."""
        for entry in self._field_rows:
            if entry["key"].text().strip() == "cell_line":
                return bool(entry["required"].isChecked())
        return False

    def _add_row(
        self,
        key="",
        label="",
        ftype="str",
        default=None,
        *,
        required=False,
        options=None,
        original_key=None,
    ):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        key_edit = QLineEdit(key)
        key_edit.setPlaceholderText(tr("main.cfKeyPh"))
        key_edit.setFixedWidth(140)
        row_layout.addWidget(key_edit)

        label_edit = QLineEdit(label)
        label_edit.setPlaceholderText(tr("main.cfLabelPh"))
        label_edit.setFixedWidth(120)
        row_layout.addWidget(label_edit)

        type_combo = QComboBox()
        for field_type in _FIELD_TYPES:
            type_combo.addItem(field_type, field_type)
        idx = type_combo.findData(ftype)
        if idx >= 0:
            type_combo.setCurrentIndex(idx)
        type_combo.setFixedWidth(70)
        row_layout.addWidget(type_combo)

        default_edit = QLineEdit(str(default) if default is not None else "")
        default_edit.setPlaceholderText(tr("main.cfDefaultPh"))
        default_edit.setFixedWidth(100)
        row_layout.addWidget(default_edit)

        required_cb = QCheckBox(tr("main.cfRequired"))
        required_cb.setChecked(bool(required))
        row_layout.addWidget(required_cb)

        opts_list = list(options) if options else []
        opts_btn = QPushButton(str(len(opts_list)) if opts_list else _OPTIONS_EMPTY_TEXT)
        opts_btn.setFixedWidth(36)
        opts_btn.setToolTip(tr("main.cfEditOptions"))
        row_layout.addWidget(opts_btn)

        remove_btn = QPushButton(tr("main.cfRemove"))
        remove_btn.setFixedWidth(60)
        row_layout.addWidget(remove_btn)

        entry = {
            "widget": row_widget,
            "key": key_edit,
            "label": label_edit,
            "type": type_combo,
            "default": default_edit,
            "required": required_cb,
            "original_key": original_key,
            "_options_data": opts_list,
            "_options_btn": opts_btn,
        }

        is_note = key_edit.text().strip() == _SYSTEM_NOTE_KEY
        entry["_is_system_note"] = bool(is_note)
        if is_note:
            key_edit.setReadOnly(True)
            idx_note = type_combo.findData("str")
            if idx_note >= 0:
                type_combo.setCurrentIndex(idx_note)
            type_combo.setEnabled(False)
            default_edit.clear()
            default_edit.setEnabled(False)
            required_cb.setChecked(False)
            required_cb.setEnabled(False)
            opts_btn.setEnabled(False)
            remove_btn.setEnabled(False)

        self._field_rows.append(entry)
        self._rows_layout.addWidget(row_widget)

        opts_btn.clicked.connect(lambda: self._edit_options(entry))
        remove_btn.clicked.connect(lambda: self._remove_row(entry))
        key_edit.textChanged.connect(lambda _text: self._sync_selector_combos())
        self._sync_selector_combos()

    def _edit_options(self, entry):
        """Open a small dialog to edit options for a field."""
        if entry.get("_is_system_note"):
            return
        dlg = QDialog(self)
        field_key = entry["key"].text().strip() or "?"
        dlg.setWindowTitle(t("main.cfFieldOptionsTitle", field=field_key))
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)

        hint = QLabel(tr("main.cfFieldOptionsHint"))
        hint.setWordWrap(True)
        hint.setProperty("role", "dialogHint")
        layout.addWidget(hint)

        text_edit = QTextEdit()
        text_edit.setMaximumHeight(120)
        current_opts = entry.get("_options_data") or []
        text_edit.setPlainText("\n".join(str(option) for option in current_opts))
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return

        raw_text = text_edit.toPlainText().strip()
        if raw_text:
            new_opts = [line.strip() for line in raw_text.splitlines() if line.strip()]
        else:
            new_opts = []
        entry["_options_data"] = new_opts
        entry["_options_btn"].setText(str(len(new_opts)) if new_opts else _OPTIONS_EMPTY_TEXT)

    def _remove_row(self, entry):
        if entry not in self._field_rows:
            return
        if entry.get("_is_system_note"):
            return
        key_name = entry["key"].text().strip() or "?"
        reply = QMessageBox.question(
            self,
            tr("main.customFieldsTitle"),
            t("main.cfRemoveConfirm", field=key_name),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        self._field_rows.remove(entry)
        entry["widget"].setParent(None)
        entry["widget"].deleteLater()
        self._sync_selector_combos()

    def _on_add_row_clicked(self):
        self._add_row()
        self._sync_selector_combos()

    def _sync_selector_combos(self):
        if not hasattr(self, "_display_key_combo") or not hasattr(self, "_color_key_combo"):
            return
        current_dk = self._display_key_combo.currentData()
        current_ck = self._color_key_combo.currentData()
        self._refresh_display_key_combo(current_dk)
        self._refresh_color_key_combo(current_ck)

    def get_custom_fields(self):
        """Return validated list of custom field dicts.

        Each dict has key/label/type/default/required/options plus an optional
        ``_original_key`` when the key was renamed from an existing field.
        """
        from lib.custom_fields import STRUCTURAL_FIELD_KEYS

        result = []
        seen = set()
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if not key or not key.isidentifier():
                continue
            if key in STRUCTURAL_FIELD_KEYS or key in seen:
                continue
            seen.add(key)

            label = entry["label"].text().strip() or key
            ftype = entry["type"].currentData() or "str"
            default_text = entry["default"].text().strip()
            default = default_text if default_text else None
            req = entry["required"].isChecked()
            opts = entry.get("_options_data") or []

            item = {
                "key": key,
                "label": label,
                "type": ftype,
            }
            if key == _SYSTEM_NOTE_KEY:
                item["type"] = "str"
                item["multiline"] = True
                default = None
                req = False
                opts = []

            if default is not None:
                item["default"] = default
            if req:
                item["required"] = True
            if opts:
                item["options"] = list(opts)

            orig = entry.get("original_key")
            if orig and orig != key:
                item["_original_key"] = orig
            result.append(item)
        return result


__all__ = ["CustomFieldsDialog"]
