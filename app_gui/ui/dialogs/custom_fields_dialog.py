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


class CustomFieldsDialog(QDialog):
    """Visual editor for meta.custom_fields."""

    def __init__(
        self,
        parent=None,
        custom_fields=None,
        display_key=None,
        color_key=None,
        cell_line_options=None,
        cell_line_required=True,
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

        # Scrollable area for everything
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        # Unified fields area (structural + custom)
        fields_group = QGroupBox(tr("main.cfFields"))
        fields_layout = QVBoxLayout(fields_group)
        fields_layout.setContentsMargins(8, 4, 8, 4)
        fields_layout.setSpacing(6)

        # Column header
        header = QWidget()
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.setSpacing(4)
        for text, width in [(tr("main.cfKey"), 140), (tr("main.cfLabel"), 120),
                            (tr("main.cfType"), 70), (tr("main.cfDefault"), 100)]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setProperty("role", "cfHeaderLabel")
            header_l.addWidget(lbl)
        req_lbl = QLabel(tr("main.cfRequired"))
        req_lbl.setProperty("role", "cfHeaderLabel")
        header_l.addWidget(req_lbl)
        action_lbl = QLabel()
        action_lbl.setFixedWidth(60)
        header_l.addWidget(action_lbl)
        fields_layout.addWidget(header)

        _STRUCTURAL_DISPLAY = [
            ("id", "ID", "int", True),
            ("box", "Box", "int", True),
            ("position", "Position", "int", True),
            ("cell_line", "Cell Line", "str", None),
            ("note", "Note", "str", False),
            ("frozen_at", "Frozen At", "date", True),
            ("thaw_events", "Takeout Events", "str", True),
        ]
        self._cell_line_required_cb = None
        for s_key, s_label, s_type, s_required in _STRUCTURAL_DISPLAY:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            k_edit = QLineEdit(s_key); k_edit.setFixedWidth(140); k_edit.setReadOnly(True); k_edit.setEnabled(False)
            row_l.addWidget(k_edit)
            l_edit = QLineEdit(s_label); l_edit.setFixedWidth(120); l_edit.setReadOnly(True); l_edit.setEnabled(False)
            row_l.addWidget(l_edit)
            t_combo = QComboBox(); t_combo.addItem(s_type); t_combo.setFixedWidth(70); t_combo.setEnabled(False)
            row_l.addWidget(t_combo)
            d_edit = QLineEdit(); d_edit.setFixedWidth(100); d_edit.setEnabled(False)
            row_l.addWidget(d_edit)
            r_cb = QCheckBox(tr("main.cfRequired"))
            if s_key == "cell_line":
                r_cb.setChecked(bool(cell_line_required))
                r_cb.setEnabled(True)
                self._cell_line_required_cb = r_cb
            else:
                r_cb.setChecked(bool(s_required))
                r_cb.setEnabled(False)
            row_l.addWidget(r_cb)
            spacer = QWidget(); spacer.setFixedWidth(60)
            row_l.addWidget(spacer)
            fields_layout.addWidget(row_w)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        fields_layout.addLayout(self._rows_layout)

        self._field_rows = []

        fields_to_show = custom_fields if custom_fields else []
        for f in fields_to_show:
            k = f.get("key", "")
            self._add_row(k, f.get("label", ""),
                          f.get("type", "str"), f.get("default"),
                          required=f.get("required", False),
                          original_key=k)

        add_btn = QPushButton(tr("main.cfAdd"))
        add_btn.clicked.connect(lambda: self._add_row())
        fields_layout.addWidget(add_btn)

        scroll_layout.addWidget(fields_group)

        scroll_layout.addStretch()

        # Display key selector
        dk_row = QHBoxLayout()
        dk_row.addWidget(QLabel(tr("main.cfDisplayKey")))
        self._display_key_combo = QComboBox()
        self._refresh_display_key_combo(display_key)
        dk_row.addWidget(self._display_key_combo, 1)
        root.addLayout(dk_row)

        # Color key selector
        ck_row = QHBoxLayout()
        ck_row.addWidget(QLabel(tr("main.cfColorKey")))
        self._color_key_combo = QComboBox()
        self._refresh_color_key_combo(color_key)
        ck_row.addWidget(self._color_key_combo, 1)
        root.addLayout(ck_row)

        # Cell line options editor
        clo_row = QVBoxLayout()
        clo_row.addWidget(QLabel(tr("main.cfCellLineOptions")))
        self._cell_line_options_edit = QTextEdit()
        self._cell_line_options_edit.setMaximumHeight(80)
        self._cell_line_options_edit.setPlaceholderText(tr("main.cfCellLineOptionsPh"))
        if cell_line_options:
            self._cell_line_options_edit.setPlainText("\n".join(cell_line_options))
        else:
            from lib.custom_fields import DEFAULT_CELL_LINE_OPTIONS
            self._cell_line_options_edit.setPlainText("\n".join(DEFAULT_CELL_LINE_OPTIONS))
        root.addLayout(clo_row)
        clo_row.addWidget(self._cell_line_options_edit)

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
        combo.clear()
        # cell_line is always an option for display_key
        combo.addItem("cell_line", "cell_line")
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if current_dk:
            idx = combo.findData(current_dk)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _refresh_color_key_combo(self, current_ck=None):
        combo = self._color_key_combo
        combo.clear()
        # cell_line is always an option for color_key
        combo.addItem("cell_line", "cell_line")
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if current_ck:
            idx = combo.findData(current_ck)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def get_display_key(self):
        return self._display_key_combo.currentData() or ""

    def get_color_key(self):
        return self._color_key_combo.currentData() or "cell_line"

    def get_cell_line_options(self):
        text = self._cell_line_options_edit.toPlainText().strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def get_cell_line_required(self):
        if self._cell_line_required_cb is None:
            return True
        return bool(self._cell_line_required_cb.isChecked())

    def _add_row(self, key="", label="", ftype="str", default=None, *, required=False, original_key=None):
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
        for t in _FIELD_TYPES:
            type_combo.addItem(t, t)
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
        }
        self._field_rows.append(entry)
        self._rows_layout.addWidget(row_widget)

        remove_btn.clicked.connect(lambda: self._remove_row(entry))

    def _remove_row(self, entry):
        if entry not in self._field_rows:
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

    def get_custom_fields(self):
        """Return validated list of custom field dicts.

        Each dict has key/label/type/default/required plus an optional
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
            item = {
                "key": key,
                "label": label,
                "type": ftype,
            }
            if default is not None:
                item["default"] = default
            if req:
                item["required"] = True
            orig = entry.get("original_key")
            if orig and orig != key:
                item["_original_key"] = orig
            result.append(item)
        return result



__all__ = ["CustomFieldsDialog"]
