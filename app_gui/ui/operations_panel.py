import json
import os
import tempfile
from datetime import date, datetime
from PySide6.QtCore import Qt, Signal, Slot, QDate, QEvent, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox,
    QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox,
    QAbstractItemView,
    QFormLayout, QDateEdit, QSpinBox, QDoubleSpinBox, QScrollArea, QTextBrowser
)
from app_gui.ui.utils import positions_to_text
from app_gui.ui.theme import get_theme_color
from app_gui.gui_config import load_gui_config
from app_gui.i18n import tr
from app_gui.plan_model import render_operation_sheet
from app_gui.plan_gate import validate_plan_batch
from app_gui.plan_outcome import summarize_plan_execution
from app_gui.audit_guide import build_operation_guide_from_audit_events
from app_gui.plan_executor import preflight_plan, run_plan
from lib.tool_api import parse_batch_entries
from lib.plan_item_factory import (
    build_add_plan_item,
    build_record_plan_item,
    build_rollback_plan_item,
    iter_batch_entries,
    resolve_record_context,
)
from lib.validators import parse_positions
from lib.plan_store import PlanStore

_ACTION_I18N_KEY = {
    "takeout": "overview.takeout",
    "thaw": "overview.thaw",
    "discard": "overview.discard",
    "move": "operations.move",
    "add": "operations.add",
    "edit": "operations.edit",
    "rollback": "operations.rollback",
}


def _localized_action(action: str) -> str:
    """Return localized display text for a canonical action name."""
    key = _ACTION_I18N_KEY.get(action.lower())
    return tr(key) if key else action.capitalize()


class OperationsPanel(QWidget):
    operation_completed = Signal(bool)
    operation_event = Signal(dict)
    status_message = Signal(str, int, str)
    plan_preview_updated = Signal(list)
    plan_hover_item_changed = Signal(object)
    
    def __init__(self, bridge, yaml_path_getter, plan_store=None):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        self._plan_store = plan_store if plan_store is not None else PlanStore()

        self.records_cache = {}
        self.current_operation_mode = "thaw"
        self.query_last_mode = "records"
        self.t_prefill_source = None
        self._default_date_anchor = QDate.currentDate()
        self._last_operation_backup = None
        self._last_executed_plan = []
        self._last_printable_plan = []
        self._plan_preflight_report = None
        self._plan_validation_by_key = {}
        self._plan_hover_row = None
        self._undo_timer = None
        self._undo_remaining = 0
        self._audit_events = []
        self._current_custom_fields = []

        self.setup_ui()

    @property
    def plan_items(self):
        """Read-only snapshot for backward compatibility (tests, external reads)."""
        return self._plan_store.list_items()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        # Mode Selection
        self.op_mode_combo = QComboBox()
        self.op_mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        modes = [
            ("thaw", tr("operations.thaw")),
            ("move", tr("operations.move")),
            ("add", tr("operations.add")),
            ("query", tr("operations.query")),
            ("audit", tr("operations.auditLog")),
        ]
        for mode_key, mode_label in modes:
            self.op_mode_combo.addItem(mode_label, mode_key)
        self.op_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(9, 0, 9, 0)

        self.quick_add_btn = QPushButton(tr("overview.quickAdd"))
        self.quick_add_btn.clicked.connect(lambda: self.set_mode("add"))
        mode_row.addWidget(self.quick_add_btn)

        self.export_full_csv_btn = QPushButton(tr("operations.exportFullCsv"))
        self.export_full_csv_btn.setToolTip(tr("operations.exportFullCsvHint"))
        self.export_full_csv_btn.clicked.connect(self.on_export_inventory_csv)
        mode_row.addWidget(self.export_full_csv_btn)

        mode_row.addStretch()
        mode_row.addWidget(self.op_mode_combo)
        layout.addLayout(mode_row)

        # Stack
        self.op_stack = QStackedWidget()
        self.op_mode_indexes = {
            "add": self.op_stack.addWidget(self._build_add_tab()),
            "thaw": self.op_stack.addWidget(self._build_thaw_tab()),
            "move": self.op_stack.addWidget(self._build_move_tab()),
            "query": self.op_stack.addWidget(self._build_query_tab()),
            "audit": self.op_stack.addWidget(self._build_audit_tab()),
        }
        layout.addWidget(self.op_stack, 2)

        # Plan Queue is always visible to reduce context switching.
        self.plan_panel = self._build_plan_tab()
        layout.addWidget(self.plan_panel, 3)

        # Result Summary Card
        self.result_card = QWidget()
        self.result_card.setObjectName("resultCard")
        self._result_card_base_style = (
            "QWidget#resultCard {"
            " background-color: var(--background-inset);"
            " border: 1px solid var(--border-weak);"
            " border-radius: var(--radius-md);"
            "}"
        )
        self.result_card.setStyleSheet(self._result_card_base_style)
        result_card_layout = QVBoxLayout(self.result_card)
        result_card_layout.setContentsMargins(9, 6, 9, 8)
        result_card_layout.setSpacing(4)

        result_header = QHBoxLayout()
        result_title = QLabel(tr("operations.lastResult"))
        result_title.setStyleSheet("color: var(--text-weak); font-size: 13px; font-weight: bold; border: none;")
        result_header.addWidget(result_title)
        result_header.addStretch()
        self._result_hide_btn = QPushButton(tr("operations.hideResult"))
        self._result_hide_btn.setFixedHeight(20)
        self._result_hide_btn.clicked.connect(lambda: self.result_card.setVisible(False))
        result_header.addWidget(self._result_hide_btn)
        result_card_layout.addLayout(result_header)

        self.result_summary = QTextBrowser()
        self.result_summary.setOpenExternalLinks(False)
        self.result_summary.setMaximumHeight(180)
        self.result_summary.setStyleSheet(
            "QTextBrowser { color: var(--text-strong); border: none;"
            " background: transparent; }"
        )
        self.result_summary.setHtml(tr("operations.noOperations"))
        result_card_layout.addWidget(self.result_summary)

        self.result_card.setVisible(False)
        result_row = QHBoxLayout()
        result_row.setContentsMargins(9, 0, 9, 0)
        result_row.addWidget(self.result_card)
        layout.addLayout(result_row)

        # Undo Button
        self.undo_btn = QPushButton(tr("operations.undoLast"))
        self.undo_btn.setEnabled(False)
        self.undo_btn.setVisible(False)
        self.undo_btn.setStyleSheet("""
            QPushButton {
                background-color: var(--btn-warning);
                color: white;
                font-weight: 500;
                border: 1px solid var(--btn-warning-border);
                border-radius: var(--radius-sm);
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: var(--btn-warning-hover);
            }
            QPushButton:disabled {
                background-color: var(--background-strong);
                color: var(--text-muted);
                border-color: transparent;
            }
        """)
        self.undo_btn.clicked.connect(self.on_undo_last)
        layout.addWidget(self.undo_btn)

        self.set_mode("thaw")

    def _is_dark_theme(self):
        return load_gui_config().get("theme", "dark") != "light"

    def _status_color_hex(self, name):
        return get_theme_color(name, self._is_dark_theme()).name()

    def _set_result_summary_html(self, lines):
        if isinstance(lines, (list, tuple)):
            html = "<br/>".join(str(line) for line in lines)
        else:
            html = str(lines)

        replacements = {
            "var(--status-success)": self._status_color_hex("success"),
            "var(--status-warning)": self._status_color_hex("warning"),
            "var(--status-error)": self._status_color_hex("error"),
            "var(--status-muted)": self._status_color_hex("muted"),
        }
        for token, color_hex in replacements.items():
            html = html.replace(token, color_hex)

        self.result_summary.setText(html)

    def set_mode(self, mode):
        self._ensure_today_defaults()
        target = mode if mode in self.op_mode_indexes else "thaw"
        self.op_stack.setCurrentIndex(self.op_mode_indexes[target])
        self.current_operation_mode = target

        idx = self.op_mode_combo.findData(target)
        if idx >= 0 and idx != self.op_mode_combo.currentIndex():
            self.op_mode_combo.blockSignals(True)
            self.op_mode_combo.setCurrentIndex(idx)
            self.op_mode_combo.blockSignals(False)

    def on_mode_changed(self, _index=None):
        self.set_mode(self.op_mode_combo.currentData())

    def on_toggle_batch_section(self, checked):
        visible = bool(checked)
        if hasattr(self, "t_batch_group"):
            self.t_batch_group.setVisible(visible)
        if hasattr(self, "t_batch_toggle_btn"):
            self.t_batch_toggle_btn.setText(tr("operations.hideBatch") if visible else tr("operations.showBatch"))

    def update_records_cache(self, records_dict):
        normalized = {}

        if isinstance(records_dict, dict):
            items = list(records_dict.items())
        elif isinstance(records_dict, list):
            items = []
            for record in records_dict:
                if isinstance(record, dict):
                    items.append((record.get("id"), record))
        else:
            items = []

        for key, record in items:
            if not isinstance(record, dict):
                continue

            rid = key if key is not None else record.get("id")
            try:
                normalized[int(rid)] = record
            except (TypeError, ValueError):
                continue

        self.records_cache = normalized
        self._refresh_thaw_record_context()
        self._refresh_move_record_context()
        self._refresh_custom_fields()

    def _refresh_custom_fields(self):
        """Reload custom field definitions from YAML meta and rebuild dynamic forms."""
        from lib.custom_fields import get_effective_fields, get_cell_line_options
        from lib.yaml_ops import load_yaml
        try:
            yaml_path = self.yaml_path_getter()
            data = load_yaml(yaml_path)
            meta = data.get("meta", {})
            custom_fields = get_effective_fields(meta)
        except Exception:
            custom_fields = []
            meta = {}
        self._current_custom_fields = custom_fields
        self._rebuild_custom_add_fields(custom_fields)
        self._rebuild_ctx_user_fields("thaw", custom_fields)
        self._rebuild_ctx_user_fields("move", custom_fields)
        self._rebuild_query_fields(custom_fields)
        # Refresh cell_line dropdown options
        self._refresh_cell_line_options(meta)

    def _refresh_cell_line_options(self, meta):
        """Populate the cell_line combo box from meta.cell_line_options."""
        from lib.custom_fields import get_cell_line_options
        combo = getattr(self, "a_cell_line", None)
        if combo is None:
            return
        prev = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")  # allow empty
        for opt in get_cell_line_options(meta):
            combo.addItem(opt)
        if prev:
            idx = combo.findText(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(prev)
        combo.blockSignals(False)

    def _rebuild_query_fields(self, custom_fields):
        """Rebuild user field query inputs in the query form."""
        form = getattr(self, "_query_form", None)
        if form is None:
            return
        # Remove old user field rows
        for key, widget in self._query_field_widgets.items():
            form.removeRow(widget)
        self._query_field_widgets = {}
        # Insert new user field rows
        for fdef in (custom_fields or []):
            key = fdef["key"]
            flabel = fdef.get("label", key)
            widget = QLineEdit()
            form.insertRow(form.rowCount(), flabel, widget)
            self._query_field_widgets[key] = widget

    def _rebuild_ctx_user_fields(self, prefix, custom_fields):
        """Rebuild user field context rows in thaw/move form."""
        if prefix == "thaw":
            form = getattr(self, "_thaw_ctx_form", None)
            widgets = getattr(self, "_thaw_ctx_widgets", {})
            rid_fn = lambda: self.t_id.value()
            refresh_fn = lambda: self._refresh_thaw_record_context()
        else:
            form = getattr(self, "_move_ctx_form", None)
            widgets = getattr(self, "_move_ctx_widgets", {})
            rid_fn = lambda: self.m_id.value()
            refresh_fn = lambda: self._refresh_move_record_context()
        if form is None:
            return
        # Remove old user field rows
        for key, (container, label) in widgets.items():
            form.removeRow(container)
        widgets.clear()
        # Insert new user field rows
        for fdef in (custom_fields or []):
            key = fdef["key"]
            flabel = fdef.get("label", key)
            container, lbl_widget = self._make_editable_field(key, rid_fn, refresh_fn)
            form.insertRow(form.rowCount(), flabel, container)
            widgets[key] = (container, lbl_widget)
        if prefix == "thaw":
            self._thaw_ctx_widgets = widgets
        else:
            self._move_ctx_widgets = widgets

    def _collect_custom_add_values(self):
        """Collect values from custom field widgets in the add form."""
        from lib.custom_fields import coerce_value
        custom_fields = getattr(self, "_current_custom_fields", [])
        if not custom_fields:
            return None
        result = {}
        for field_def in custom_fields:
            key = field_def["key"]
            widget = self._add_custom_widgets.get(key)
            if widget is None:
                continue
            if isinstance(widget, QSpinBox):
                raw = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                raw = widget.value()
            elif isinstance(widget, QDateEdit):
                raw = widget.date().toString("yyyy-MM-dd")
            else:
                raw = widget.text().strip()
            try:
                val = coerce_value(raw, field_def.get("type", "str"))
            except (ValueError, TypeError):
                val = raw if raw else None
            if val is not None:
                result[key] = val
        return result if result else None

    def _apply_thaw_prefill(self, source_info, switch_mode=True):
        payload = dict(source_info or {})
        self.t_prefill_source = payload
        if "record_id" in payload:
            self.t_id.setValue(int(payload["record_id"]))
        self.t_action.setCurrentIndex(0)
        self._refresh_thaw_record_context()
        if switch_mode:
            self.set_mode("thaw")

    def set_prefill(self, source_info):
        self._apply_thaw_prefill(source_info, switch_mode=True)

    def set_prefill_background(self, source_info):
        self._apply_thaw_prefill(source_info, switch_mode=True)

    def set_move_prefill(self, source_info):
        self._m_prefill_position = source_info.get("position")
        if "record_id" in source_info:
            self.m_id.setValue(int(source_info["record_id"]))
        self._refresh_move_record_context()
        self.set_mode("move")

    def set_query_prefill(self, source_info):
        if "box" in source_info:
            self.q_box.setValue(int(source_info["box"]))
        if "position" in source_info:
            self.q_position.setValue(int(source_info["position"]))
        self.set_mode("query")
        self.on_query_records()

    def _apply_add_prefill(self, source_info, switch_mode=True):
        payload = dict(source_info or {})
        if "box" in payload:
            self.a_box.setValue(int(payload["box"]))
        if "position" in payload:
            self.a_positions.setText(str(payload["position"]))
        if switch_mode:
            self.set_mode("add")

    def set_add_prefill(self, source_info):
        """Pre-fill the Add Entry form with box and position from overview."""
        self._apply_add_prefill(source_info, switch_mode=True)

    def set_add_prefill_background(self, source_info):
        """Pre-fill the Add Entry form and switch to Add mode."""
        self._apply_add_prefill(source_info, switch_mode=True)

    def _setup_table(self, table, headers, sortable=True):
        table.setRowCount(0)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        for idx in range(len(headers)):
            mode = QHeaderView.Stretch if idx == len(headers) - 1 else QHeaderView.ResizeToContents
            header.setSectionResizeMode(idx, mode)
        table.setSortingEnabled(bool(sortable))

    def _make_readonly_field(self):
        field = QLineEdit()
        field.setReadOnly(True)
        field.setStyleSheet(
            "QLineEdit[readOnly=\"true\"] {"
            " background: var(--background-inset);"
            " border: none;"
            " color: var(--text-strong);"
            " padding: 2px 4px;"
            "}"
        )
        return field

    _READONLY_STYLE = (
        "QLineEdit[readOnly=\"true\"] {"
        " background: var(--background-inset);"
        " border: none;"
        " color: var(--text-strong);"
        " padding: 2px 4px;"
        "}"
    )
    _EDITING_STYLE = (
        "QLineEdit {"
        " background: var(--background-default);"
        " border: 1px solid var(--accent);"
        " color: var(--text-strong);"
        " padding: 2px 4px;"
        "}"
    )

    def _make_editable_field(self, field_name, record_id_getter, refresh_callback=None):
        """Create a read-only field with lock/unlock/confirm inline edit controls.

        Args:
            field_name: YAML record key (e.g. 'cell_line', 'short_name').
            record_id_getter: callable returning current record ID (int).
            refresh_callback: callable to restore original value on cancel.
        Returns:
            (container_widget, field_widget) — add container to form, use field for setText.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        field = QLineEdit()
        field.setReadOnly(True)
        field.setStyleSheet(self._READONLY_STYLE)
        row.addWidget(field, 1)

        lock_btn = QPushButton("\U0001F512")  # 🔒
        lock_btn.setFixedSize(22, 22)
        lock_btn.setToolTip(tr("operations.edit"))
        lock_btn.setStyleSheet("QPushButton { border: none; padding: 0; font-size: 12px; }")
        row.addWidget(lock_btn)

        confirm_btn = QPushButton("\u2713")  # ✓
        confirm_btn.setFixedSize(22, 22)
        confirm_btn.setVisible(False)
        confirm_btn.setStyleSheet(
            "QPushButton { border: none; padding: 0; font-size: 14px; font-weight: bold; color: var(--status-success); }"
        )
        row.addWidget(confirm_btn)

        def on_lock_toggle():
            if field.isReadOnly():
                # Unlock
                field.setReadOnly(False)
                field.setStyleSheet(self._EDITING_STYLE)
                lock_btn.setText("\U0001F513")  # 🔓
                confirm_btn.setVisible(True)
                field.setFocus()
                field.selectAll()
            else:
                # Re-lock without saving
                field.setReadOnly(True)
                field.setStyleSheet(self._READONLY_STYLE)
                lock_btn.setText("\U0001F512")  # 🔒
                confirm_btn.setVisible(False)
                # Restore original value
                if refresh_callback:
                    refresh_callback()

        def on_confirm():
            rid = record_id_getter()
            new_value = field.text().strip() or None
            record = self._lookup_record(rid)
            if not record:
                self.status_message.emit(tr("operations.recordNotFound"), 3000, "error")
                return
            old_value = record.get(field_name) or None
            old_str = str(old_value) if old_value is not None else ""
            new_str = str(new_value) if new_value is not None else ""
            if old_str == new_str:
                self.status_message.emit(tr("operations.editNoChange"), 2000, "info")
                # Re-lock
                field.setReadOnly(True)
                field.setStyleSheet(self._READONLY_STYLE)
                lock_btn.setText("\U0001F512")
                confirm_btn.setVisible(False)
                return
            yaml_path = self.yaml_path_getter()
            if not yaml_path:
                return
            result = self.bridge.edit_entry(
                yaml_path=yaml_path,
                record_id=rid,
                fields={field_name: new_value},
            )
            if result.get("ok"):
                field.setReadOnly(True)
                field.setStyleSheet(self._READONLY_STYLE)
                lock_btn.setText("\U0001F512")
                confirm_btn.setVisible(False)
                self.status_message.emit(
                    tr("operations.editFieldSaved", field=field_name, before=old_str, after=new_str),
                    4000, "success",
                )
                self.operation_completed.emit(True)
                self.operation_event.emit({
                    "action": "edit_entry",
                    "record_id": rid,
                    "field": field_name,
                    "before": old_str,
                    "after": new_str,
                })
            else:
                self.status_message.emit(
                    tr("operations.editFieldFailed", error=result.get("message", "?")),
                    5000, "error",
                )

        lock_btn.clicked.connect(on_lock_toggle)
        confirm_btn.clicked.connect(on_confirm)

        return container, field

    # --- ADD TAB ---
    def _build_add_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        # Structural fields (always present)
        self.a_box = QSpinBox()
        self.a_box.setRange(1, 99)
        self.a_positions = QLineEdit()
        self.a_positions.setPlaceholderText(tr("operations.positionsPh"))
        self.a_date = QDateEdit()
        self.a_date.setCalendarPopup(True)
        self.a_date.setDisplayFormat("yyyy-MM-dd")
        self.a_date.setDate(QDate.currentDate())

        # Cell line dropdown (structural, optional)
        self.a_cell_line = QComboBox()
        self.a_cell_line.setEditable(True)
        self.a_cell_line.addItem("")  # allow empty

        form.addRow(tr("operations.box"), self.a_box)
        form.addRow(tr("operations.positions"), self.a_positions)
        form.addRow(tr("operations.frozenDate"), self.a_date)
        form.addRow(tr("operations.cellLine"), self.a_cell_line)

        # User fields placeholder — populated by _rebuild_custom_add_fields()
        self._add_custom_form = form
        self._add_custom_widgets = {}

        self.a_apply_btn = QPushButton(tr("operations.add"))
        self._style_stage_button(self.a_apply_btn)
        self.a_apply_btn.clicked.connect(self.on_add_entry)
        a_btn_row = QHBoxLayout()
        a_btn_row.addWidget(self.a_apply_btn)
        form.addRow("", a_btn_row)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _rebuild_custom_add_fields(self, custom_fields):
        """Rebuild user field rows in the add form based on effective fields."""
        form = self._add_custom_form
        # Remove old user field widgets
        for key, widget in self._add_custom_widgets.items():
            form.removeRow(widget)
        self._add_custom_widgets = {}

        if not custom_fields:
            return

        # Insert before the button row (last row)
        for field_def in custom_fields:
            key = field_def["key"]
            label = field_def.get("label", key)
            ftype = field_def.get("type", "str")
            default = field_def.get("default")

            if ftype == "int":
                widget = QSpinBox()
                widget.setRange(-999999, 999999)
                if default is not None:
                    try:
                        widget.setValue(int(default))
                    except (ValueError, TypeError):
                        pass
            elif ftype == "float":
                widget = QDoubleSpinBox()
                widget.setRange(-999999.0, 999999.0)
                widget.setDecimals(3)
                if default is not None:
                    try:
                        widget.setValue(float(default))
                    except (ValueError, TypeError):
                        pass
            elif ftype == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setDisplayFormat("yyyy-MM-dd")
                widget.setDate(QDate.currentDate())
            else:
                widget = QLineEdit()
                if default is not None:
                    widget.setText(str(default))

            # Insert before the last row (button row)
            btn_row_idx = form.rowCount() - 1
            form.insertRow(btn_row_idx, label, widget)
            self._add_custom_widgets[key] = widget

    # --- THAW TAB ---
    def _build_thaw_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        # Editable: record ID
        self.t_id = QSpinBox()
        self.t_id.setRange(1, 999999)
        self.t_id.valueChanged.connect(self._refresh_thaw_record_context)
        form.addRow(tr("operations.recordId"), self.t_id)

        _t_rid = lambda: self.t_id.value()
        _t_refresh = lambda: self._refresh_thaw_record_context()

        # Editable context fields — frozen_at is always present
        t_frozen_w, self.t_ctx_frozen = self._make_editable_field("frozen_at", _t_rid, _t_refresh)

        # Dynamic user field context widgets (populated by _rebuild_thaw_ctx_fields)
        self._thaw_ctx_form = form
        self._thaw_ctx_widgets = {}  # key -> (container_widget, label_widget)

        # Read-only context fields (not editable via inline edit)
        self.t_ctx_box = self._make_readonly_field()
        self.t_ctx_positions = self._make_readonly_field()
        self.t_ctx_events = self._make_readonly_field()
        self.t_ctx_source = self._make_readonly_field()

        # User fields placeholder — will be rebuilt dynamically
        self._thaw_ctx_insert_row = form.rowCount()

        form.addRow(tr("overview.ctxBox"), self.t_ctx_box)
        form.addRow(tr("overview.ctxAllPos"), self.t_ctx_positions)
        form.addRow(tr("overview.ctxFrozen"), t_frozen_w)
        form.addRow(tr("overview.ctxHistory"), self.t_ctx_events)
        form.addRow(tr("overview.ctxSource"), self.t_ctx_source)

        # Editable: target position (populated from record positions)
        self.t_position = QComboBox()
        form.addRow(tr("operations.position"), self.t_position)

        # Editable fields
        self.t_date = QDateEdit()
        self.t_date.setCalendarPopup(True)
        self.t_date.setDisplayFormat("yyyy-MM-dd")
        self.t_date.setDate(QDate.currentDate())
        self.t_note = QLineEdit()

        form.addRow(tr("operations.date"), self.t_date)
        form.addRow(tr("operations.note"), self.t_note)

        # Status
        self.t_ctx_status = QLabel(tr("operations.noPrefill"))
        self.t_ctx_status.setWordWrap(True)
        form.addRow(tr("overview.ctxStatus"), self.t_ctx_status)

        # Kept for compatibility
        self.t_ctx_id = self.t_id
        self.t_ctx_target = self.t_position
        self.t_ctx_check = QLabel()
        self.t_action = QComboBox()  # hidden, kept for compat
        self.t_action.addItem(tr("overview.takeout"), "Takeout")
        self.t_action.addItem(tr("overview.thaw"), "Thaw")
        self.t_action.addItem(tr("overview.discard"), "Discard")

        # Action buttons at bottom
        btn_row = QHBoxLayout()
        self.t_takeout_btn = QPushButton(tr("overview.takeout"))
        self.t_thaw_btn = QPushButton(tr("overview.thaw"))
        self.t_discard_btn = QPushButton(tr("overview.discard"))
        for btn in (self.t_takeout_btn, self.t_thaw_btn, self.t_discard_btn):
            self._style_stage_button(btn)
            btn_row.addWidget(btn)
        self.t_takeout_btn.clicked.connect(lambda: self._record_thaw_with_action("Takeout"))
        self.t_thaw_btn.clicked.connect(lambda: self._record_thaw_with_action("Thaw"))
        self.t_discard_btn.clicked.connect(lambda: self._record_thaw_with_action("Discard"))
        # Keep t_apply_btn as alias for the first button (compat)
        self.t_apply_btn = self.t_takeout_btn
        form.addRow("", btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_thaw_controls(tab)
        layout.addStretch(1)
        return tab

    # --- MOVE TAB ---
    def _build_move_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        # Editable: record ID
        self.m_id = QSpinBox()
        self.m_id.setRange(1, 999999)
        self.m_id.valueChanged.connect(self._refresh_move_record_context)
        form.addRow(tr("operations.recordId"), self.m_id)

        _m_rid = lambda: self.m_id.value()
        _m_refresh = lambda: self._refresh_move_record_context()

        # Editable context fields — frozen_at is always present
        m_frozen_w, self.m_ctx_frozen = self._make_editable_field("frozen_at", _m_rid, _m_refresh)

        # Dynamic user field context widgets (populated by _rebuild_move_ctx_fields)
        self._move_ctx_form = form
        self._move_ctx_widgets = {}  # key -> (container_widget, label_widget)

        # Read-only context fields (not editable via inline edit)
        self.m_ctx_box = self._make_readonly_field()
        self.m_ctx_positions = self._make_readonly_field()
        self.m_ctx_events = self._make_readonly_field()

        # User fields placeholder — will be rebuilt dynamically
        self._move_ctx_insert_row = form.rowCount()

        form.addRow(tr("overview.ctxBox"), self.m_ctx_box)
        form.addRow(tr("overview.ctxAllPos"), self.m_ctx_positions)
        form.addRow(tr("overview.ctxFrozen"), m_frozen_w)
        form.addRow(tr("overview.ctxHistory"), self.m_ctx_events)

        # Editable: move fields
        self.m_from_position = QComboBox()
        self.m_to_position = QSpinBox()
        self.m_to_position.setRange(1, 999)
        self.m_to_position.valueChanged.connect(self._refresh_move_record_context)
        self.m_to_box = QSpinBox()
        self.m_to_box.setRange(0, 99)
        self.m_to_box.setSpecialValueText(tr("operations.sameBox"))

        form.addRow(tr("operations.fromPosition"), self.m_from_position)
        form.addRow(tr("operations.toPosition"), self.m_to_position)
        form.addRow(tr("operations.toBox"), self.m_to_box)

        # Read-only: move direction
        self.m_ctx_target = self._make_readonly_field()
        form.addRow(tr("overview.ctxMove"), self.m_ctx_target)

        # Editable fields
        self.m_date = QDateEdit()
        self.m_date.setCalendarPopup(True)
        self.m_date.setDisplayFormat("yyyy-MM-dd")
        self.m_date.setDate(QDate.currentDate())
        self.m_note = QLineEdit()

        form.addRow(tr("operations.date"), self.m_date)
        form.addRow(tr("operations.note"), self.m_note)

        # Status
        self.m_ctx_status = QLabel(tr("operations.noPrefill"))
        self.m_ctx_status.setWordWrap(True)
        form.addRow(tr("overview.ctxStatus"), self.m_ctx_status)

        # Kept for compatibility
        self.m_ctx_id = self.m_id
        self.m_ctx_check = QLabel()  # hidden, kept for refresh method compat

        # Button at bottom
        m_btn_row = QHBoxLayout()
        self.m_apply_btn = QPushButton(tr("operations.move"))
        self._style_stage_button(self.m_apply_btn)
        self.m_apply_btn.clicked.connect(self.on_record_move)
        m_btn_row.addWidget(self.m_apply_btn)
        form.addRow("", m_btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_move_controls(tab)
        layout.addStretch(1)
        return tab

    def _init_hidden_batch_thaw_controls(self, parent):
        self.t_batch_toggle_btn = QPushButton(tr("operations.showBatch"), parent)
        self.t_batch_toggle_btn.setCheckable(True)
        self.t_batch_toggle_btn.toggled.connect(self.on_toggle_batch_section)
        self.t_batch_toggle_btn.setVisible(False)

        self.t_batch_group = QGroupBox(tr("operations.batchOp"), parent)
        self.t_batch_group.setVisible(False)
        batch_form = QFormLayout(self.t_batch_group)
        self.b_entries = QLineEdit(self.t_batch_group)
        self.b_entries.setPlaceholderText(tr("operations.entriesPh"))
        self.b_date = QDateEdit(self.t_batch_group)
        self.b_date.setCalendarPopup(True)
        self.b_date.setDisplayFormat("yyyy-MM-dd")
        self.b_date.setDate(QDate.currentDate())
        self.b_action = QComboBox(self.t_batch_group)
        self.b_action.addItems([tr("overview.takeout"), tr("overview.thaw"), tr("overview.discard")])
        self.b_note = QLineEdit(self.t_batch_group)
        self.b_table = QTableWidget(self.t_batch_group)
        self.b_table.setColumnCount(2)
        self.b_table.setHorizontalHeaderLabels([tr("operations.recordId"), tr("operations.position")])
        self.b_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.b_table.setRowCount(1)
        self.b_apply_btn = QPushButton(tr("operations.addPlan"), self.t_batch_group)
        self.b_apply_btn.clicked.connect(self.on_batch_thaw)

        batch_form.addRow(tr("operations.entriesText"), self.b_entries)
        batch_form.addRow(tr("operations.orUseTable"), self.b_table)
        batch_form.addRow(tr("operations.date"), self.b_date)
        batch_form.addRow(tr("operations.action"), self.b_action)
        batch_form.addRow(tr("operations.note"), self.b_note)
        batch_form.addRow("", self.b_apply_btn)

    def _init_hidden_batch_move_controls(self, parent):
        self.m_batch_toggle_btn = QPushButton(tr("operations.showBatchMove"), parent)
        self.m_batch_toggle_btn.setCheckable(True)
        self.m_batch_toggle_btn.toggled.connect(self._on_toggle_move_batch_section)
        self.m_batch_toggle_btn.setVisible(False)

        self.m_batch_group = QGroupBox(tr("operations.batchMove"), parent)
        self.m_batch_group.setVisible(False)
        batch_form = QFormLayout(self.m_batch_group)
        self.bm_entries = QLineEdit(self.m_batch_group)
        self.bm_entries.setPlaceholderText(tr("operations.entriesMovePh"))
        self.bm_date = QDateEdit(self.m_batch_group)
        self.bm_date.setCalendarPopup(True)
        self.bm_date.setDisplayFormat("yyyy-MM-dd")
        self.bm_date.setDate(QDate.currentDate())
        self.bm_note = QLineEdit(self.m_batch_group)
        self.bm_table = QTableWidget(self.m_batch_group)
        self.bm_table.setColumnCount(4)
        self.bm_table.setHorizontalHeaderLabels([tr("operations.recordId"), tr("operations.from"), tr("operations.to"), tr("operations.toBox")])
        self.bm_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bm_table.setRowCount(1)
        self.bm_apply_btn = QPushButton(tr("operations.addPlan"), self.m_batch_group)
        self.bm_apply_btn.clicked.connect(self.on_batch_move)

        batch_form.addRow(tr("operations.entriesText"), self.bm_entries)
        batch_form.addRow(tr("operations.orUseTable"), self.bm_table)
        batch_form.addRow(tr("operations.date"), self.bm_date)
        batch_form.addRow(tr("operations.note"), self.bm_note)
        batch_form.addRow("", self.bm_apply_btn)

    # --- PLAN TAB ---
    def _build_plan_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(9, 0, 9, 0)

        self.plan_empty_label = QLabel(tr("operations.emptyPlan"))
        self.plan_empty_label.setAlignment(Qt.AlignCenter)
        self.plan_empty_label.setWordWrap(True)
        self.plan_empty_label.setStyleSheet(
            "color: var(--warning); padding: 16px; font-weight: 500; background-color: var(--background-inset); border: 1px solid var(--border-weak); border-radius: var(--radius-md);"
        )
        layout.addWidget(self.plan_empty_label)

        self.plan_table = QTableWidget()
        self.plan_table.setMouseTracking(True)
        self.plan_table.cellEntered.connect(self._on_plan_cell_entered)
        self._setup_table(
            self.plan_table,
            [tr("operations.colSource"), tr("operations.colAction"), tr("operations.colBox"), tr("operations.colPos"), tr("operations.colToPos"), tr("operations.colToBox"), tr("operations.colLabel"), tr("operations.colNote"), tr("operations.colStatus")],
            sortable=False,
        )
        self.plan_table.viewport().installEventFilter(self)
        self.plan_table.setVisible(False)
        self.plan_table.selectionModel().selectionChanged.connect(
            lambda *_args: self._refresh_plan_toolbar_state()
        )
        layout.addWidget(self.plan_table, 1)

        toolbar = QHBoxLayout()
        self.plan_remove_selected_btn = QPushButton(tr("operations.removeSelected"))
        self.plan_remove_selected_btn.setEnabled(False)
        self.plan_remove_selected_btn.clicked.connect(self.remove_selected_plan_items)
        toolbar.addWidget(self.plan_remove_selected_btn)

        self.plan_exec_btn = QPushButton(tr("operations.executeAll"))
        self._style_execute_button(self.plan_exec_btn)
        self.plan_exec_btn.clicked.connect(self.execute_plan)
        self.plan_exec_btn.setEnabled(False)
        toolbar.addWidget(self.plan_exec_btn)

        self.plan_print_btn = QPushButton(tr("operations.print"))
        self.plan_print_btn.clicked.connect(self.print_plan)
        toolbar.addWidget(self.plan_print_btn)

        self.plan_clear_btn = QPushButton(tr("operations.clear"))
        self.plan_clear_btn.setEnabled(False)
        self.plan_clear_btn.clicked.connect(self.clear_plan)
        toolbar.addWidget(self.plan_clear_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        return tab

    def _on_toggle_move_batch_section(self, checked):
        visible = bool(checked)
        if hasattr(self, "m_batch_group"):
            self.m_batch_group.setVisible(visible)
        if hasattr(self, "m_batch_toggle_btn"):
            self.m_batch_toggle_btn.setText(
                tr("operations.hideBatchMove") if visible else tr("operations.showBatchMove")
            )

    # --- QUERY TAB ---
    def _build_query_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        # Structural query fields (always present)
        self.q_box = QSpinBox()
        self.q_box.setRange(0, 99)
        self.q_box.setSpecialValueText(tr("operations.any"))
        self.q_position = QSpinBox()
        self.q_position.setRange(0, 999)
        self.q_position.setSpecialValueText(tr("operations.any"))

        form.addRow(tr("operations.box"), self.q_box)
        form.addRow(tr("operations.position"), self.q_position)

        # Dynamic user field query inputs — populated by _rebuild_query_fields
        self._query_form = form
        self._query_field_widgets = {}  # key -> QLineEdit

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        query_btn = QPushButton(tr("operations.queryRecords"))
        query_btn.clicked.connect(self.on_query_records)
        btn_row.addWidget(query_btn)

        empty_btn = QPushButton(tr("operations.listEmpty"))
        empty_btn.clicked.connect(self.on_list_empty)
        btn_row.addWidget(empty_btn)
        layout.addLayout(btn_row)

        self.query_info = QLabel(tr("operations.queryInfo"))
        layout.addWidget(self.query_info)

        self.query_table = QTableWidget()
        layout.addWidget(self.query_table, 1)
        self._setup_table(
            self.query_table,
            [
                tr("operations.colId"),
                tr("operations.colCell"),
                tr("operations.colShort"),
                tr("operations.colBox"),
                tr("operations.colPositions"),
                tr("operations.colFrozenAt"),
                tr("operations.colPlasmidId"),
                tr("operations.colNote"),
            ],
            sortable=False,
        )
        return tab

    # --- AUDIT BACKUP ROLLBACK PANEL ---
    def _build_audit_backup_panel(self):
        panel = QGroupBox(tr("operations.auditRollbackAdvanced"))
        layout = QVBoxLayout(panel)

        form = QFormLayout()
        self.rb_backup_path = QLineEdit()
        self.rb_backup_path.setPlaceholderText(tr("operations.backupPh"))

        form.addRow(tr("operations.backupPath"), self.rb_backup_path)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(tr("operations.refreshBackups"))
        refresh_btn.clicked.connect(self.on_refresh_backups)
        btn_row.addWidget(refresh_btn)

        select_btn = QPushButton(tr("operations.useSelected"))
        select_btn.clicked.connect(self.on_use_selected_backup)
        btn_row.addWidget(select_btn)

        rollback_latest_btn = QPushButton(tr("operations.rollbackLatest"))
        rollback_latest_btn.clicked.connect(self.on_rollback_latest)
        btn_row.addWidget(rollback_latest_btn)

        rollback_selected_btn = QPushButton(tr("operations.rollbackSelected"))
        rollback_selected_btn.clicked.connect(self.on_rollback_selected)
        btn_row.addWidget(rollback_selected_btn)
        layout.addLayout(btn_row)

        self.backup_info = QLabel(tr("operations.backupsInfo"))
        layout.addWidget(self.backup_info)

        self.backup_table = QTableWidget()
        layout.addWidget(self.backup_table, 1)
        self._setup_table(
            self.backup_table,
            [tr("operations.backupColIndex"), tr("operations.backupColDate"), tr("operations.backupColSize"), tr("operations.backupColPath")],
            sortable=True,
        )
        return panel

    # --- LOGIC ---

    def _style_execute_button(self, btn):
        btn.setProperty("variant", "danger")

    def _style_stage_button(self, btn):
        btn.setProperty("variant", "primary")

    def _ensure_today_defaults(self):
        today = QDate.currentDate()
        anchor = getattr(self, "_default_date_anchor", today)
        if today == anchor:
            return

        for attr in ("a_date", "t_date", "b_date", "m_date", "bm_date"):
            widget = getattr(self, attr, None)
            if widget is not None and widget.date() == anchor:
                widget.setDate(today)

        self._default_date_anchor = today

    def _lookup_record(self, rid):
        try:
            return self.records_cache.get(int(rid))
        except (ValueError, TypeError):
            return None

    def _refresh_thaw_record_context(self):
        record_id = self.t_id.value()
        record = self._lookup_record(record_id)

        source_text = "-"
        if self.t_prefill_source:
            source_box = self.t_prefill_source.get("box")
            source_prefill = self.t_prefill_source.get("position")
            if source_box is not None and source_prefill is not None:
                source_text = tr("operations.boxSourceText", box=source_box, position=source_prefill)
        self.t_ctx_source.setText(source_text)

        if not record:
            self.t_ctx_status.setText(tr("operations.recordNotFound"))
            self.t_ctx_status.setStyleSheet("color: var(--status-warning);")
            self.t_position.clear()
            for lbl in [self.t_ctx_box, self.t_ctx_positions, self.t_ctx_frozen,
                        self.t_ctx_events]:
                lbl.setText("-")
            for key, (container, lbl) in self._thaw_ctx_widgets.items():
                lbl.setText("-")
            return

        if self.t_prefill_source:
            self.t_ctx_status.setText(tr("operations.recordLoaded"))
        else:
            self.t_ctx_status.setText(tr("operations.recordContextLoaded"))
        self.t_ctx_status.setStyleSheet("color: var(--status-success);")

        self.t_ctx_box.setText(str(record.get("box") or "-"))

        positions = record.get("positions") or []
        self.t_ctx_positions.setText(positions_to_text(positions))
        self.t_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
        # Populate dynamic user field context
        for key, (container, lbl) in self._thaw_ctx_widgets.items():
            lbl.setText(str(record.get(key) or "-"))

        # Populate position combo
        prev = self.t_position.currentData()
        self.t_position.blockSignals(True)
        self.t_position.clear()
        for p in sorted(int(x) for x in positions):
            self.t_position.addItem(str(p), p)
        # Restore previous selection or prefill
        restore = None
        if self.t_prefill_source:
            restore = self.t_prefill_source.get("position")
        if restore is None:
            restore = prev
        if restore is not None:
            idx = self.t_position.findData(int(restore))
            if idx >= 0:
                self.t_position.setCurrentIndex(idx)
        self.t_position.blockSignals(False)

        # History
        events = record.get("thaw_events") or []
        if events:
            last = events[-1]
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_pos = positions_to_text(last.get("positions") or [])
            self.t_ctx_events.setText(
                tr(
                    "operations.historySummary",
                    count=len(events),
                    date=last_date,
                    action=last_action,
                    positions=last_pos,
                )
            )
        else:
            self.t_ctx_events.setText(tr("operations.noHistory"))

    def _confirm_execute(self, title, details):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText(tr("operations.confirmModify"))
        msg.setInformativeText(details)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        return msg.exec() == QMessageBox.Yes

    @staticmethod
    def _format_size_bytes(size_bytes):
        try:
            value = float(size_bytes)
        except (TypeError, ValueError):
            return "-"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while value >= 1024.0 and idx < len(units) - 1:
            value /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(value)} {units[idx]}"
        return f"{value:.1f} {units[idx]}"

    def _build_rollback_confirmation_lines(
        self,
        *,
        backup_path,
        yaml_path,
        source_event=None,
        include_action_prefix=True,
    ):
        yaml_abs = os.path.abspath(str(yaml_path or ""))
        raw_backup = str(backup_path or "").strip()
        backup_abs = os.path.abspath(raw_backup) if raw_backup else ""
        backup_label = os.path.basename(backup_abs) if backup_abs else tr("operations.planRollbackLatest")

        lines = []
        restore_line = tr("operations.planRollbackRestore", backup=backup_label)
        if include_action_prefix:
            restore_line = f"{tr('operations.rollback')}: {restore_line}"
        lines.append(restore_line)
        lines.append(tr("operations.planRollbackYamlPath", path=yaml_abs or "-"))

        if backup_abs:
            lines.append(tr("operations.planRollbackBackupPath", path=backup_abs))
            try:
                stat = os.stat(backup_abs)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = self._format_size_bytes(stat.st_size)
                lines.append(tr("operations.planRollbackBackupMeta", mtime=mtime, size=size))
            except Exception:
                lines.append(tr("operations.planRollbackBackupMissing", path=backup_abs))

        if isinstance(source_event, dict) and source_event:
            timestamp = str(source_event.get("timestamp") or "-")
            action = str(source_event.get("action") or "-")
            trace_id = str(source_event.get("trace_id") or "-")
            lines.append(
                tr(
                    "operations.planRollbackSourceEvent",
                    timestamp=timestamp,
                    action=action,
                    trace_id=trace_id,
                )
            )
        return lines

    def on_add_entry(self):
        self._ensure_today_defaults()
        positions_text = self.a_positions.text().strip()

        try:
            positions = parse_positions(positions_text)
        except ValueError as exc:
            self.status_message.emit(str(exc), 5000, "error")
            return

        # Collect all user field values into a single dict
        fields = self._collect_custom_add_values() or {}

        # cell_line is structural but passed through fields (tool_api extracts it)
        cl = self.a_cell_line.currentText().strip()
        if cl:
            fields["cell_line"] = cl

        item = build_add_plan_item(
            box=self.a_box.value(),
            positions=positions,
            frozen_at=self.a_date.date().toString("yyyy-MM-dd"),
            fields=fields,
            source="human",
        )
        self.add_plan_items([item])

    def _record_thaw_with_action(self, action_text):
        idx = self.t_action.findData(action_text)
        if idx >= 0:
            self.t_action.setCurrentIndex(idx)
        else:
            self.t_action.setCurrentText(action_text)
        self.on_record_thaw()

    def on_record_thaw(self):
        self._ensure_today_defaults()
        action_text = self.t_action.currentData() or self.t_action.currentText()

        record = self._lookup_record(self.t_id.value())
        fallback_box = int((self.t_prefill_source or {}).get("box", 0) or 0)
        box, label = resolve_record_context(record, fallback_box=fallback_box)
        item = build_record_plan_item(
            action=action_text,
            record_id=self.t_id.value(),
            position=self.t_position.currentData(),
            box=box,
            label=label,
            date_str=self.t_date.date().toString("yyyy-MM-dd"),
            note=self.t_note.text().strip() or None,
            source="human",
            payload_action=action_text,
        )
        self.add_plan_items([item])

    def on_record_move(self):
        self._ensure_today_defaults()

        from_pos = self.m_from_position.currentData()
        to_pos = self.m_to_position.value()
        to_box = self.m_to_box.value() if self.m_to_box.value() > 0 else None
        if from_pos == to_pos and to_box is None:
            self.status_message.emit(tr("operations.moveMustDiffer"), 4000, "error")
            return

        record = self._lookup_record(self.m_id.value())
        box, label = resolve_record_context(record, fallback_box=0)
        item = build_record_plan_item(
            action="move",
            record_id=self.m_id.value(),
            position=from_pos,
            box=box,
            label=label,
            date_str=self.m_date.date().toString("yyyy-MM-dd"),
            note=self.m_note.text().strip() or None,
            to_position=to_pos,
            to_box=to_box,
            source="human",
            payload_action="Move",
        )
        self.add_plan_items([item])

    def _collect_move_batch_from_table(self):
        """Collect move entries from the move batch table. Returns list of 3- or 4-tuples or None."""
        entries = []
        for row in range(self.bm_table.rowCount()):
            id_item = self.bm_table.item(row, 0)
            from_item = self.bm_table.item(row, 1)
            to_item = self.bm_table.item(row, 2)
            to_box_item = self.bm_table.item(row, 3)

            if not id_item or not from_item or not to_item:
                continue

            id_text = id_item.text().strip()
            from_text = from_item.text().strip()
            to_text = to_item.text().strip()

            if not id_text or not from_text or not to_text:
                continue

            try:
                entry = (int(id_text), int(from_text), int(to_text))
                if to_box_item:
                    tb_text = to_box_item.text().strip()
                    if tb_text:
                        entry = entry + (int(tb_text),)
                entries.append(entry)
            except ValueError as exc:
                raise ValueError(
                    tr("operations.invalidMoveRow", row=row + 1)
                ) from exc

        return entries if entries else None

    def on_batch_move(self):
        self._ensure_today_defaults()

        try:
            entries = self._collect_move_batch_from_table()
        except ValueError as exc:
            self.status_message.emit(str(exc), 3000, "error")
            return

        if entries is None:
            entries_text = self.bm_entries.text().strip()
            try:
                entries = parse_batch_entries(entries_text)
            except ValueError as exc:
                self.status_message.emit(str(exc), 3000, "error")
                return

        date_str = self.bm_date.date().toString("yyyy-MM-dd")
        note = self.bm_note.text().strip() or None

        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            from_pos = int(normalized.get("position", 0) or 0)
            to_pos = normalized.get("to_position")
            to_box = normalized.get("to_box")
            if to_pos is None:
                continue

            record = self._lookup_record(rid)
            box, label = resolve_record_context(record, fallback_box=0)
            items.append(
                build_record_plan_item(
                    action="move",
                    record_id=rid,
                    position=from_pos,
                    box=box,
                    label=label,
                    date_str=date_str,
                    note=note,
                    to_position=to_pos,
                    to_box=to_box,
                    source="human",
                    payload_action="Move",
                )
            )

        self.add_plan_items(items)

    def _refresh_move_record_context(self):
        if not hasattr(self, "m_ctx_status"):
            return

        record_id = self.m_id.value()
        to_pos = self.m_to_position.value()
        record = self._lookup_record(record_id)

        if not record:
            self.m_ctx_status.setText(tr("operations.recordNotFound"))
            self.m_ctx_status.setStyleSheet("color: var(--status-warning);")
            self.m_from_position.clear()
            self.m_ctx_target.setText("-")
            for lbl in [self.m_ctx_box, self.m_ctx_positions, self.m_ctx_frozen,
                        self.m_ctx_events]:
                lbl.setText("-")
            for key, (container, lbl) in self._move_ctx_widgets.items():
                lbl.setText("-")
            return

        self.m_ctx_status.setText(tr("operations.recordContextLoaded"))
        self.m_ctx_status.setStyleSheet("color: var(--status-success);")
        self.m_ctx_box.setText(str(record.get("box") or "-"))

        positions = record.get("positions") or []
        self.m_ctx_positions.setText(positions_to_text(positions))
        self.m_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
        # Populate dynamic user field context
        for key, (container, lbl) in self._move_ctx_widgets.items():
            lbl.setText(str(record.get(key) or "-"))

        # Populate from-position combo
        prev = self.m_from_position.currentData()
        self.m_from_position.blockSignals(True)
        self.m_from_position.clear()
        for p in sorted(int(x) for x in positions):
            self.m_from_position.addItem(str(p), p)
        restore = getattr(self, "_m_prefill_position", None)
        if restore is None:
            restore = prev
        if restore is not None:
            idx = self.m_from_position.findData(int(restore))
            if idx >= 0:
                self.m_from_position.setCurrentIndex(idx)
        self._m_prefill_position = None
        self.m_from_position.blockSignals(False)

        from_pos = self.m_from_position.currentData()
        self.m_ctx_target.setText(f"{from_pos} -> {to_pos}")

        events = record.get("thaw_events") or []
        if events:
            last = events[-1]
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_pos = positions_to_text(last.get("positions") or [])
            self.m_ctx_events.setText(
                tr(
                    "operations.historySummary",
                    count=len(events),
                    date=last_date,
                    action=last_action,
                    positions=last_pos,
                )
            )
        else:
            self.m_ctx_events.setText(tr("operations.noHistory"))

    def _collect_batch_from_table(self):
        """Collect entries from the mini-table. Returns list of tuples or None if empty."""
        entries = []
        for row in range(self.b_table.rowCount()):
            id_item = self.b_table.item(row, 0)
            pos_item = self.b_table.item(row, 1)

            if not id_item or not pos_item:
                continue

            id_text = id_item.text().strip()
            pos_text = pos_item.text().strip()

            if not id_text or not pos_text:
                continue

            try:
                entries.append((int(id_text), int(pos_text)))
            except ValueError as exc:
                raise ValueError(
                    tr("operations.invalidBatchRow", row=row + 1)
                ) from exc

        return entries if entries else None

    def on_batch_thaw(self):
        self._ensure_today_defaults()

        # Try table first, fall back to text input
        try:
            entries = self._collect_batch_from_table()
        except ValueError as exc:
            self.status_message.emit(str(exc), 3000, "error")
            return

        if entries is None:
            entries_text = self.b_entries.text().strip()
            try:
                entries = parse_batch_entries(entries_text)
            except ValueError as exc:
                self.status_message.emit(str(exc), 3000, "error")
                return

        action_text = self.b_action.currentText()
        date_str = self.b_date.date().toString("yyyy-MM-dd")
        note = self.b_note.text().strip() or None

        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            pos = int(normalized.get("position", 0) or 0)
            record = self._lookup_record(rid)
            box, label = resolve_record_context(record, fallback_box=0)
            items.append(
                build_record_plan_item(
                    action=action_text,
                    record_id=rid,
                    position=pos,
                    box=box,
                    label=label,
                    date_str=date_str,
                    note=note,
                    source="human",
                    payload_action=action_text,
                )
            )

        self.add_plan_items(items)

    def _handle_response(self, response, context):
        payload = response if isinstance(response, dict) else {}
        self._display_result_summary(response, context)

        ok = payload.get("ok", False)
        msg = payload.get("message", tr("operations.unknownResult"))

        if ok:
            self.status_message.emit(tr("operations.contextSuccess", context=context), 3000, "success")
            self.operation_completed.emit(True)
            # Enable undo if backup_path available
            backup_path = payload.get("backup_path")
            if backup_path:
                self._last_operation_backup = backup_path
                self._enable_undo(timeout_sec=30)
        else:
            self.status_message.emit(tr("operations.contextFailed", context=context, error=msg), 5000, "error")
            self.operation_completed.emit(False)

    def _display_result_summary(self, response, context):
        """Show a human-readable summary card for the operation result."""
        payload = response if isinstance(response, dict) else {}
        ok = payload.get("ok", False)
        preview = payload.get("preview", {}) or {}
        result = payload.get("result", {}) or {}

        if ok:
            lines = [f"<b style='color: var(--status-success);'>{tr('operations.contextResultSuccess', context=context)}</b>"]

            if context == "Add Entry":
                new_ids = result.get("new_ids") or []
                new_id = result.get("new_id", "?")
                fields = preview.get("fields") or {}
                from lib.custom_fields import get_display_key
                dk = get_display_key(None)
                cell = str(fields.get("cell_line", ""))
                short = str(fields.get(dk, ""))
                box = preview.get("box", "")
                positions = preview.get("positions", [])
                pos_text = ",".join(str(p) for p in positions)
                if new_ids:
                    ids_text = ", ".join(str(i) for i in new_ids)
                    lines.append(
                        tr(
                            "operations.addedTubesSummary",
                            count=len(new_ids),
                            ids=ids_text,
                            cell=cell,
                            short=short,
                            box=box,
                            positions=pos_text,
                        )
                    )
                else:
                    lines.append(
                        tr(
                            "operations.addedTubeSummary",
                            id=new_id,
                            cell=cell,
                            short=short,
                            box=box,
                            positions=pos_text,
                        )
                    )

            elif context == "Single Operation":
                rid = preview.get("record_id", "?")
                action = preview.get("action_en", preview.get("action_cn", ""))
                pos = preview.get("position", "?")
                to_pos = preview.get("to_position")
                before = preview.get("positions_before", [])
                after = preview.get("positions_after", [])
                if to_pos is not None:
                    lines.append(tr("operations.operationRowActionWithTarget", rid=rid, action=action, pos=pos, to_pos=to_pos))
                else:
                    lines.append(
                        tr("operations.operationRowActionWithPosition", rid=rid, action=action, pos=pos)
                    )
                if before or after:
                    lines.append(
                        tr(
                            "operations.operationPositionsTransition",
                            before=",".join(str(p) for p in before),
                            after=",".join(str(p) for p in after),
                        )
                    )

            elif context == "Batch Operation":
                count = result.get("count", preview.get("count", 0))
                ids = result.get("record_ids", [])
                lines.append(
                    tr(
                        "operations.processedBatchEntries",
                        count=count,
                        ids=", ".join(str(i) for i in ids),
                    )
                )

            elif context == "Rollback" or context == "Undo":
                restored = result.get("restored_from", "?")
                lines.append(
                    tr("operations.restoredFrom", path=os.path.basename(str(restored)))
                )

            self._set_result_summary_html(lines)
            self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", "var(--success)"))
        else:
            msg = payload.get("message", tr("operations.unknownError"))
            error_code = payload.get("error_code", "")
            lines = [f"<b style='color: var(--status-error);'>{tr('operations.contextResultFailed', context=context)}</b>"]
            lines.append(str(msg))
            if error_code:
                lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.codeLabel', code=error_code)}</span>")
            self._set_result_summary_html(lines)
            self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", "var(--error)"))

        self.result_card.setVisible(True)

    # --- PLAN OPERATIONS ---

    def eventFilter(self, obj, event):
        """Handle plan table hover-leave to clear Overview execution preview."""
        try:
            if hasattr(self, "plan_table") and obj is self.plan_table.viewport():
                if event.type() == QEvent.Leave:
                    self._emit_plan_hover_item(None)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _emit_plan_hover_item(self, item):
        if item is None:
            if self._plan_hover_row is not None:
                self._plan_hover_row = None
                self.plan_hover_item_changed.emit(None)
            return

        self.plan_hover_item_changed.emit(item)

    def _get_selected_plan_rows(self):
        if not hasattr(self, "plan_table") or self.plan_table is None:
            return []
        model = self.plan_table.selectionModel()
        if model is None:
            return []
        rows = set()
        for model_index in model.selectedIndexes():
            row = model_index.row()
            if 0 <= row < self._plan_store.count():
                rows.add(row)
        return sorted(rows)

    def _refresh_plan_toolbar_state(self):
        if not hasattr(self, "plan_table"):
            return

        rows = self._get_selected_plan_rows()
        has_selected = bool(rows)
        has_items = bool(self._plan_store.count())
        first = rows[0] if has_selected else -1
        last = rows[-1] if has_selected else -1

        if not has_selected:
            self.plan_remove_selected_btn.setEnabled(False)
        else:
            self.plan_remove_selected_btn.setEnabled(True)

        self.plan_clear_btn.setEnabled(has_items)

    def _select_plan_rows(self, rows):
        if not hasattr(self, "plan_table"):
            return

        self.plan_table.clearSelection()
        for row in sorted(set(rows)):
            if 0 <= row < self.plan_table.rowCount():
                self.plan_table.selectRow(row)

    @Slot()
    def _on_store_changed(self):
        """Slot invoked (via QueuedConnection) when PlanStore mutates from any thread."""
        self._refresh_after_plan_items_changed(emit_preview=True)

    def _refresh_after_plan_items_changed(self, emit_preview=True):
        self._plan_hover_row = None
        self._emit_plan_hover_item(None)
        self._run_plan_preflight(trigger="edit")
        self._refresh_plan_table()
        self._update_execute_button_state()
        if emit_preview:
            self.plan_preview_updated.emit(self._plan_store.list_items())
        self._refresh_plan_toolbar_state()

    def _on_plan_cell_entered(self, row, _col):
        if row < 0 or row >= self._plan_store.count():
            return
        if row == self._plan_hover_row:
            return
        self._plan_hover_row = row
        items = self._plan_store.list_items()
        if row < len(items):
            self._emit_plan_hover_item(items[row])

    def remove_selected_plan_items(self):
        rows = self._get_selected_plan_rows()
        if not rows:
            self.status_message.emit(tr("operations.planNoSelection"), 2000, "warning")
            return

        items = self._plan_store.list_items()
        removed_items = [items[r] for r in rows if 0 <= r < len(items)]
        removed_count = self._plan_store.remove_by_indices(rows)
        if removed_count == 0:
            self.status_message.emit(tr("operations.planNoRemoved"), 2000, "warning")
            return
        self.status_message.emit(
            tr("operations.planRemovedCount", count=removed_count), 2000, "info"
        )

        action_counts = {}
        sample = []
        for item in removed_items:
            action = str(item.get("action") or "?")
            action_counts[action] = action_counts.get(action, 0) + 1
            if len(sample) < 8:
                label = item.get("label") or item.get("record_id") or "-"
                box = item.get("box")
                pos = item.get("position")
                desc = f"{action} {label}"
                if box not in (None, "") and pos not in (None, ""):
                    desc += f" @ Box {box}:{pos}"
                sample.append(desc)

        self._emit_operation_event(
            {
                "type": "plan_removed",
                "source": "operations_panel",
                "removed_count": removed_count,
                "total_count": self._plan_store.count(),
                "action_counts": action_counts,
                "sample": sample,
            }
        )

    def _remove_plan_rows(self, rows):
        if not rows:
            return 0
        removed_count = self._plan_store.remove_by_indices(rows)
        return removed_count

    def _plan_item_key(self, item):
        """Generate a unique key for plan item deduplication."""
        return PlanStore.item_key(item)

    def add_plan_items(self, items):
        """Validate and add items to the plan staging area (with dedup)."""
        incoming = list(items or [])

        incoming_has_rollback = any(
            str(it.get("action") or "").lower() == "rollback" for it in incoming
        )
        existing_has_rollback = self._plan_store.has_rollback()

        # Rollback is intentionally constrained: it must be executed alone.
        # Enforce early here (in addition to shared plan gate / executor checks),
        # so the plan queue stays clean and predictable.
        if incoming_has_rollback and self._plan_store.count() and not existing_has_rollback:
            self.status_message.emit(
                tr("operations.planRejectedRollbackSolo"),
                4000,
                "error",
            )
            return
        if incoming_has_rollback and existing_has_rollback:
            self.status_message.emit(
                tr("operations.planRejectedRollbackDuplicate"),
                4000,
                "error",
            )
            return
        if not incoming_has_rollback and existing_has_rollback:
            self.status_message.emit(
                tr("operations.planRejectedRollbackExisting"),
                4000,
                "error",
            )
            return

        gate = validate_plan_batch(
            items=incoming,
            yaml_path=self.yaml_path_getter(),
            bridge=self.bridge,
            run_preflight=False,
        )
        for blocked in gate.get("blocked_items", []):
            err = blocked.get("message") or blocked.get("error_code") or "invalid plan item"
            self.status_message.emit(tr("operations.planRejected", error=err), 4000, "error")

        accepted = list(gate.get("accepted_items") or [])
        if not accepted:
            return

        added = self._plan_store.add(accepted)

        if added:
            self._run_plan_preflight(trigger="add")
            self._refresh_plan_table()
            self._update_execute_button_state()
            self.plan_preview_updated.emit(self._plan_store.list_items())
            self.status_message.emit(tr("operations.planAddedCount", count=added), 2000, "info")

            action_counts = {}
            sample = []
            for item in accepted:
                action = str(item.get("action") or "?")
                action_counts[action] = action_counts.get(action, 0) + 1
                if len(sample) < 8:
                    label = item.get("label") or item.get("record_id") or "-"
                    box = item.get("box")
                    pos = item.get("position")
                    desc = f"{action} {label}"
                    if box not in (None, "") and pos not in (None, ""):
                        desc += f" @ Box {box}:{pos}"
                    to_pos = item.get("to_position")
                    to_box = item.get("to_box")
                    if to_pos not in (None, ""):
                        if to_box not in (None, ""):
                            desc += f" -> Box {to_box}:{to_pos}"
                        else:
                            desc += f" -> {to_pos}"
                    sample.append(desc)

            self._emit_operation_event(
                {
                    "type": "plan_staged",
                    "source": "operations_panel",
                    "added_count": added,
                    "total_count": self._plan_store.count(),
                    "action_counts": action_counts,
                    "sample": sample,
                }
            )

    def _run_plan_preflight(self, trigger="manual"):
        """Run preflight validation on current plan items."""
        self._plan_validation_by_key = {}
        plan_items = self._plan_store.list_items()
        if not plan_items:
            self._plan_preflight_report = None
            return

        yaml_path = self.yaml_path_getter()
        if not os.path.isfile(yaml_path):
            self._plan_preflight_report = {"ok": True, "blocked": False, "items": [], "stats": {"total": len(plan_items), "ok": len(plan_items), "blocked": 0}}
            return

        report = preflight_plan(yaml_path, plan_items, self.bridge)

        self._plan_preflight_report = report
        for r in report.get("items", []):
            item = r.get("item")
            if item:
                key = self._plan_item_key(item)
                self._plan_validation_by_key[key] = {
                    "ok": r.get("ok"),
                    "blocked": r.get("blocked"),
                    "error_code": r.get("error_code"),
                    "message": r.get("message"),
                }

    def _update_execute_button_state(self):
        """Enable/disable Execute button based on preflight results."""
        if not self._plan_store.count():
            self.plan_exec_btn.setEnabled(False)
            return

        has_blocked = any(
            v.get("blocked") for v in self._plan_validation_by_key.values()
        )
        self.plan_exec_btn.setEnabled(not has_blocked)
        if has_blocked:
            blocked_count = sum(1 for v in self._plan_validation_by_key.values() if v.get("blocked"))
            self.plan_exec_btn.setText(
                tr("operations.executePlanBlocked", count=blocked_count)
            )
        else:
            self.plan_exec_btn.setText(tr("operations.executeAll"))

    def _refresh_plan_table(self):
        has_items = bool(self._plan_store.count())
        self.plan_empty_label.setVisible(not has_items)
        self.plan_table.setVisible(has_items)
        self._plan_hover_row = None
        self._emit_plan_hover_item(None)

        self._setup_table(
            self.plan_table,
            [tr("operations.colSource"), tr("operations.colAction"), tr("operations.colBox"), tr("operations.colPos"), tr("operations.colToPos"), tr("operations.colToBox"), tr("operations.colLabel"), tr("operations.colNote"), tr("operations.colStatus")],
            sortable=False,
        )

        plan_items = self._plan_store.list_items()
        yaml_path_for_rollback = os.path.abspath(str(self.yaml_path_getter()))
        for row, item in enumerate(plan_items):
            self.plan_table.insertRow(row)
            action_text = str(item.get("action", "") or "")
            action_norm = action_text.lower()
            is_rollback = action_norm == "rollback"

            self.plan_table.setItem(row, 0, QTableWidgetItem(item.get("source", "")))
            self.plan_table.setItem(row, 1, QTableWidgetItem(_localized_action(action_text)))

            if is_rollback:
                box_text = ""
                pos_text = ""
                to_pos = None
                to_box = None
            else:
                box_text = item.get("box", "")
                pos_val = item.get("position", "")
                pos_text = "" if pos_val in (None, "") else str(pos_val)
                to_pos = item.get("to_position")
                to_box = item.get("to_box")

            self.plan_table.setItem(row, 2, QTableWidgetItem("" if box_text in (None, "") else str(box_text)))
            self.plan_table.setItem(row, 3, QTableWidgetItem(pos_text))
            self.plan_table.setItem(row, 4, QTableWidgetItem(str(to_pos) if to_pos else ""))
            self.plan_table.setItem(row, 5, QTableWidgetItem(str(to_box) if to_box else ""))

            payload = item.get("payload") or {}
            label_text = str(item.get("label", "") or "")
            backup_path = payload.get("backup_path")
            source_event = payload.get("source_event") if isinstance(payload, dict) else None
            rollback_tooltip = ""
            if is_rollback:
                rollback_lines = self._build_rollback_confirmation_lines(
                    backup_path=backup_path,
                    yaml_path=yaml_path_for_rollback,
                    source_event=source_event,
                    include_action_prefix=False,
                )
                rollback_tooltip = "\n".join(rollback_lines)
                backup_label = (
                    os.path.basename(str(backup_path))
                    if backup_path
                    else tr("operations.planRollbackLatest")
                )
                label_text = f"{tr('operations.rollback')}: {backup_label}"
            label_item = QTableWidgetItem(label_text)
            if is_rollback and rollback_tooltip:
                label_item.setToolTip(rollback_tooltip)
            self.plan_table.setItem(row, 6, label_item)

            if is_rollback:
                note = ""
                if isinstance(source_event, dict) and source_event:
                    note = tr(
                        "operations.planRollbackSourceEvent",
                        timestamp=str(source_event.get("timestamp") or "-"),
                        action=str(source_event.get("action") or "-"),
                        trace_id=str(source_event.get("trace_id") or "-"),
                    )
                elif backup_path:
                    backup_abs = os.path.abspath(str(backup_path))
                    try:
                        stat = os.stat(backup_abs)
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                        size = self._format_size_bytes(stat.st_size)
                        note = tr("operations.planRollbackBackupMeta", mtime=mtime, size=size)
                    except Exception:
                        note = tr("operations.planRollbackBackupMissing", path=backup_abs)
                note_item = QTableWidgetItem(str(note))
                if rollback_tooltip:
                    note_item.setToolTip(rollback_tooltip)
                self.plan_table.setItem(row, 7, note_item)
            else:
                note = (payload.get("note", "") if isinstance(payload, dict) else "") or ""
                self.plan_table.setItem(row, 7, QTableWidgetItem(str(note)))

            key = self._plan_item_key(item)
            validation = self._plan_validation_by_key.get(key, {})
            status_item = QTableWidgetItem()
            is_dark = load_gui_config().get("theme", "dark") == "dark"
            if validation.get("blocked"):
                status_item.setText(tr("operations.planStatusBlocked"))
                status_item.setForeground(get_theme_color("error", is_dark))
                status_item.setToolTip(validation.get("message", ""))
            elif validation.get("ok"):
                status_item.setText(tr("operations.planStatusReady"))
                status_item.setForeground(get_theme_color("success", is_dark))
            else:
                status_item.setText("-")
            self.plan_table.setItem(row, 8, status_item)

        self._refresh_plan_toolbar_state()

    def execute_plan(self):
        """Execute all staged plan items after user confirmation."""
        if not self._plan_store.count():
            self.status_message.emit(tr("operations.planNoItemsToExecute"), 3000, "error")
            return

        # Always re-run preflight right before execution to avoid stale validation.
        self._run_plan_preflight(trigger="execute")

        if self._plan_preflight_report and self._plan_preflight_report.get("blocked"):
            blocked_count = self._plan_preflight_report.get("stats", {}).get("blocked", 0)
            self.status_message.emit(
                tr("operations.planExecuteBlocked", count=blocked_count),
                4000,
                "error",
            )
            self._emit_operation_event({
                "type": "plan_execute_blocked",
                "source": "operations_panel",
                "blocked_count": blocked_count,
                "report": self._plan_preflight_report,
            })
            return

        yaml_path = os.path.abspath(str(self.yaml_path_getter()))
        summary_lines = []
        plan_items = self._plan_store.list_items()
        for item in plan_items:
            action = item.get("action", "?")
            label = item.get("label", "?")
            pos = item.get("position", "?")
            if str(action).lower() == "rollback":
                payload = item.get("payload") or {}
                summary_lines.extend(
                    self._build_rollback_confirmation_lines(
                        backup_path=payload.get("backup_path"),
                        yaml_path=yaml_path,
                        source_event=payload.get("source_event"),
                        include_action_prefix=True,
                    )
                )
                continue

            line = f"  {action}: {label} @ Box {item.get('box', '?')}:{pos}"
            to_pos = item.get("to_position")
            to_box = item.get("to_box")
            if to_pos:
                if to_box:
                    line += f" \u2192 Box {to_box}:{to_pos}"
                else:
                    line += f" \u2192 {to_pos}"
            summary_lines.append(line)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(tr("operations.executePlanTitle"))
        msg.setText(tr("operations.executePlanConfirm", count=len(plan_items)))
        msg.setInformativeText("\n".join(summary_lines[:20]))
        if len(summary_lines) > 20:
            msg.setDetailedText("\n".join(summary_lines))
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        if msg.exec() != QMessageBox.Yes:
            return

        original_plan = list(plan_items)
        report = run_plan(yaml_path, plan_items, self.bridge, mode="execute")

        results = []
        for r in report.get("items", []):
            status = "OK" if r.get("ok") else "FAIL"
            info = r.get("response") or {}
            if status == "FAIL":
                info = {
                    "message": r.get("message"),
                    "error_code": r.get("error_code"),
                }
            results.append((status, r.get("item"), info))

        remaining = report.get("remaining_items", [])
        fail_count = sum(1 for r in results if r[0] == "FAIL")
        rollback_info = None

        if fail_count:
            rollback_info = self._attempt_atomic_rollback(yaml_path, results)
            self._plan_store.replace_all(original_plan)
        elif remaining:
            self._plan_store.replace_all(remaining)
        else:
            self._plan_store.clear()

        self._run_plan_preflight(trigger="post_execute")
        self._refresh_plan_table()
        self._update_execute_button_state()
        self.plan_preview_updated.emit(self._plan_store.list_items())
        execution_stats = summarize_plan_execution(report, rollback_info)
        self._show_plan_result(
            results,
            remaining,
            report=report,
            rollback_info=rollback_info,
        )

        executed_items = [r[1] for r in results if r[0] == "OK"]
        if execution_stats.get("rollback_ok"):
            executed_items = []
        if executed_items:
            self._last_printable_plan = list(executed_items)

        if report.get("ok") and any(r[0] == "OK" for r in results):
            self.operation_completed.emit(True)
        elif fail_count:
            self.operation_completed.emit(False)

        last_backup = report.get("backup_path")
        if last_backup and executed_items:
            self._last_operation_backup = last_backup
            self._last_executed_plan = list(executed_items)
            self._enable_undo(timeout_sec=30)

        self._emit_operation_event({
            "type": "plan_executed",
            "source": "operations_panel",
            "ok": report.get("ok"),
            "stats": {
                **(report.get("stats") or {}),
                "applied": execution_stats.get("applied_count", 0),
                "failed": execution_stats.get("fail_count", 0),
                "rolled_back": bool(execution_stats.get("rollback_ok")),
            },
            "summary": self._build_execution_summary_text(execution_stats),
            "report": report,
            "rollback": rollback_info,
        })

    def _attempt_atomic_rollback(self, yaml_path, results):
        """Best-effort rollback to the first backup of this execute run."""
        first_backup = None
        for status, _item, info in results:
            if status != "OK" or not isinstance(info, dict):
                continue
            backup_path = info.get("backup_path")
            if backup_path:
                first_backup = backup_path
                break

        if not first_backup:
            return {
                "attempted": False,
                "ok": False,
                "message": tr("operations.noRollbackBackup"),
            }

        rollback_fn = getattr(self.bridge, "rollback", None)
        if not callable(rollback_fn):
            return {
                "attempted": False,
                "ok": False,
                "message": tr("operations.bridgeNoRollback"),
                "backup_path": first_backup,
            }

        try:
            response = rollback_fn(yaml_path=yaml_path, backup_path=first_backup)
        except Exception as exc:
            return {
                "attempted": True,
                "ok": False,
                "message": tr("operations.rollbackException", error=exc),
                "backup_path": first_backup,
            }

        payload = response if isinstance(response, dict) else {}
        if payload.get("ok"):
            self.status_message.emit(tr("operations.executionRolledBack"), 5000, "warning")
            return {
                "attempted": True,
                "ok": True,
                "message": tr("operations.executionRolledBack"),
                "backup_path": first_backup,
            }

        return {
            "attempted": True,
            "ok": False,
            "message": payload.get("message", tr("operations.rollbackUnknown")),
            "error_code": payload.get("error_code"),
            "backup_path": first_backup,
        }

    def _emit_operation_event(self, event):
        """Emit an operation event for AI panel to consume."""
        event["timestamp"] = datetime.now().isoformat()
        self.operation_event.emit(event)

    def emit_external_operation_event(self, event):
        """Public helper for non-plan modules to emit operation events."""
        if not isinstance(event, dict):
            return
        self._emit_operation_event(dict(event))

    def _build_execution_summary_text(self, execution_stats):
        """Build a user-facing summary for execution event payloads."""
        if execution_stats.get("fail_count", 0) <= 0:
            applied = execution_stats.get("applied_count", 0)
            total = execution_stats.get("total_count", 0)
            return tr("operations.planExecutionSuccessSummary", applied=applied, total=total)

        total = execution_stats.get("total_count", 0)
        fail = execution_stats.get("fail_count", 0)
        applied = execution_stats.get("applied_count", 0)
        if execution_stats.get("rollback_ok"):
            return tr("operations.planExecutionAtomicRollback", fail=fail, total=total)

        rollback_message = execution_stats.get("rollback_message", "")
        if execution_stats.get("rollback_attempted"):
            suffix = tr("operations.rollbackFailedSuffix", reason=rollback_message) if rollback_message else ""
        elif rollback_message:
            suffix = tr("operations.rollbackUnavailableSuffix", reason=rollback_message)
        else:
            suffix = ""
        return tr(
            "operations.planExecutionFailedSummary",
            fail=fail,
            total=total,
            applied=applied,
            suffix=suffix,
        )

    def _show_plan_result(self, results, remaining, report=None, rollback_info=None):
        execution_stats = summarize_plan_execution(report, rollback_info)
        ok_count = execution_stats.get("ok_count", sum(1 for r in results if r[0] == "OK"))
        fail_count = execution_stats.get("fail_count", sum(1 for r in results if r[0] == "FAIL"))
        applied_count = execution_stats.get("applied_count", ok_count)

        if fail_count:
            fail_item = [r for r in results if r[0] == "FAIL"][-1]
            error_msg = fail_item[2].get("message", "Unknown error")
            title_html = f"<b style='color: var(--status-error);'>{tr('operations.planExecutionStopped')}</b>"
            if execution_stats.get("rollback_ok"):
                title_html = f"<b style='color: var(--status-warning);'>{tr('operations.planExecutionRolledBack')}</b>"
            lines = [
                title_html,
                tr(
                    "operations.planExecutionStats",
                    attempted_ok=ok_count,
                    failed=fail_count,
                    applied=applied_count,
                ),
                tr("operations.planExecutionError", error=error_msg),
                f"<span style='color: var(--status-muted);'>{tr('operations.planExecutionRetry')}</span>",
            ]
            if isinstance(rollback_info, dict) and rollback_info:
                if execution_stats.get("rollback_ok"):
                    lines.append(
                        f"<span style='color: var(--status-success);'>{tr('operations.planExecutionRollbackApplied')}</span>"
                    )
                elif execution_stats.get("rollback_attempted"):
                    lines.append(
                        f"<span style='color: var(--status-error);'>{tr('operations.planExecutionRollbackFailed', reason=rollback_info.get('message', 'unknown error'))}</span>"
                    )
                elif execution_stats.get("rollback_message"):
                    lines.append(
                        f"<span style='color: var(--status-warning);'>{tr('operations.planExecutionRollbackUnavailable', reason=execution_stats.get('rollback_message'))}</span>"
                    )
            self._set_result_summary_html(lines)
            border_color = "var(--warning)" if execution_stats.get("rollback_ok") else "var(--error)"
            self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", border_color))
        else:
            lines = [
                f"<b style='color: var(--status-success);'>{tr('operations.planExecutionSuccess')}</b>",
                tr("operations.planExecutionSuccessSummary", applied=applied_count, total=applied_count),
            ]
            self._set_result_summary_html(lines)
            self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", "var(--success)"))

        self.result_card.setVisible(True)

    def print_plan(self):
        items_to_print = self._plan_store.list_items() or self._last_printable_plan
        if not items_to_print:
            self.status_message.emit(tr("operations.noPlanToPrint"), 3000, "error")
            return

        if not self._plan_store.count():
            self.status_message.emit(tr("operations.planEmptyPrintingLast"), 2500, "info")

        self._print_operation_sheet(items_to_print, opened_message=tr("operations.planPrintOpened"))

    def _print_operation_sheet(self, items, opened_message=None):
        if opened_message is None:
            opened_message = tr("operations.operationSheetOpened")
        html = render_operation_sheet(items)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))
        self.status_message.emit(opened_message, 2000, "info")

    def clear_plan(self):
        cleared_items = self._plan_store.clear()
        self._plan_validation_by_key = {}
        self._plan_preflight_report = None
        self._refresh_plan_table()
        self._update_execute_button_state()
        self.plan_preview_updated.emit(self._plan_store.list_items())
        self.status_message.emit(tr("operations.planCleared"), 2000, "info")

        if cleared_items:
            action_counts = {}
            sample = []
            for item in cleared_items:
                action = str(item.get("action") or "?")
                action_counts[action] = action_counts.get(action, 0) + 1

                if len(sample) < 8:
                    label = item.get("label") or item.get("record_id") or "-"
                    box = item.get("box")
                    pos = item.get("position")
                    desc = f"{action} {label}"
                    if box not in (None, "") and pos not in (None, ""):
                        desc += f" @ Box {box}:{pos}"
                    to_pos = item.get("to_position")
                    to_box = item.get("to_box")
                    if to_pos not in (None, ""):
                        if to_box not in (None, ""):
                            desc += f" -> Box {to_box}:{to_pos}"
                        else:
                            desc += f" -> {to_pos}"
                    sample.append(desc)

            self._emit_operation_event(
                {
                    "type": "plan_cleared",
                    "source": "operations_panel",
                    "cleared_count": len(cleared_items),
                    "action_counts": action_counts,
                    "sample": sample,
                }
            )

    # --- Query & Rollback Stubs (simplified) ---
    def on_query_records(self):
        box = self.q_box.value()
        box_val = box if box > 0 else None
        pos = self.q_position.value()
        pos_val = pos if pos > 0 else None

        # Collect dynamic user field filters
        field_filters = {}
        for key, widget in self._query_field_widgets.items():
            val = widget.text().strip()
            if val:
                field_filters[key] = val

        response = self.bridge.query_inventory(
            self.yaml_path_getter(),
            box=box_val,
            position=pos_val,
            **field_filters,
        )

        payload = response if isinstance(response, dict) else {}
        result = payload.get("result", {})
        records = []
        if isinstance(result, dict):
            records = result.get("records", [])
        elif isinstance(result, list):
            records = result
        if not isinstance(records, list):
            records = []

        self._render_query_results(records)
        self.query_last_mode = "records"

        if not payload.get("ok", False):
            self.status_message.emit(
                tr(
                    "operations.queryFailed",
                    error=payload.get("message", tr("operations.unknownResult")),
                ),
                5000,
                "error",
            )

    def on_list_empty(self):
        box = self.q_box.value()
        box_val = box if box > 0 else None
        response = self.bridge.list_empty_positions(self.yaml_path_getter(), box=box_val)

        payload = response if isinstance(response, dict) else {}
        result = payload.get("result", {})
        boxes = []
        if isinstance(result, dict):
            boxes = result.get("boxes", [])
        elif isinstance(result, list):
            boxes = result
        if not isinstance(boxes, list):
            boxes = []

        self._render_empty_results(boxes)
        self.query_last_mode = "empty"

        if not payload.get("ok", False):
            self.status_message.emit(
                tr(
                    "operations.listEmptyFailed",
                    error=payload.get("message", tr("operations.unknownResult")),
                ),
                5000,
                "error",
            )

    def _render_query_results(self, records):
        custom_fields = getattr(self, "_current_custom_fields", [])
        # Structural columns + dynamic user field columns
        headers = [
            tr("operations.colId"),
            tr("operations.colBox"),
            tr("operations.colPositions"),
            tr("operations.colFrozenAt"),
        ]
        for cf in custom_fields:
            headers.append(cf.get("label", cf["key"]))

        self._setup_table(self.query_table, headers)
        rows = [rec for rec in records if isinstance(rec, dict)]
        for row, rec in enumerate(rows):
            self.query_table.insertRow(row)
            self.query_table.setItem(row, 0, QTableWidgetItem(str(rec.get("id"))))
            self.query_table.setItem(row, 1, QTableWidgetItem(str(rec.get("box"))))
            self.query_table.setItem(row, 2, QTableWidgetItem(positions_to_text(rec.get("positions"))))
            self.query_table.setItem(row, 3, QTableWidgetItem(str(rec.get("frozen_at"))))
            for ci, cf in enumerate(custom_fields):
                self.query_table.setItem(row, 4 + ci, QTableWidgetItem(str(rec.get(cf["key"], ""))))
        self.query_info.setText(tr("operations.foundRecords", count=len(rows)))

    def _render_empty_results(self, boxes):
        self._setup_table(
            self.query_table,
            [tr("operations.colBox"), tr("operations.colEmptyTotal"), tr("operations.colPositions")],
            sortable=False,
        )
        for row, item in enumerate(boxes):
            self.query_table.insertRow(row)
            self.query_table.setItem(row, 0, QTableWidgetItem(str(item.get("box"))))
            self.query_table.setItem(row, 1, QTableWidgetItem(f"{item.get('empty_count')}/{item.get('total_slots')}"))
            
            pos_list = item.get("empty_positions", [])
            preview = ",".join(str(p) for p in pos_list[:20])
            if len(pos_list) > 20: preview += "..."
            self.query_table.setItem(row, 2, QTableWidgetItem(preview))
        self.query_info.setText(tr("operations.foundBoxesWithEmptySlots", count=len(boxes)))

    def on_export_inventory_csv(self):
        yaml_path = self.yaml_path_getter()
        default_name = f"inventory_full_{date.today().isoformat()}.csv"
        suggested_path = default_name
        if yaml_path:
            yaml_abs = os.path.abspath(os.fspath(yaml_path))
            base_name = os.path.splitext(os.path.basename(yaml_abs))[0] or "inventory"
            suggested_path = os.path.join(
                os.path.dirname(yaml_abs),
                f"{base_name}_full_{date.today().isoformat()}.csv",
            )

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("operations.exportDialogTitle"),
            suggested_path,
            tr("operations.exportCsvFilter"),
        )
        if not path:
            return

        if not str(path).lower().endswith(".csv"):
            path = f"{path}.csv"

        response = self.bridge.export_inventory_csv(
            yaml_path,
            output_path=path,
        )
        payload = response if isinstance(response, dict) else {}
        if payload.get("ok"):
            result = payload.get("result", {})
            exported_path = result.get("path") if isinstance(result, dict) else None
            count = result.get("count") if isinstance(result, dict) else None
            if isinstance(count, int):
                self.status_message.emit(
                    tr("operations.exportedToWithCount", count=count, path=exported_path or path),
                    3000,
                    "success",
                )
            else:
                self.status_message.emit(tr("operations.exportedTo", path=exported_path or path), 3000, "success")
            return

        self.status_message.emit(
            tr(
                "operations.exportFailed",
                error=payload.get("message", tr("operations.unknownError")),
            ),
            5000,
            "error",
        )

    def on_refresh_backups(self):
        # Implementation for refresh backups
        resp = self.bridge.list_backups(self.yaml_path_getter())
        backups = resp.get("result", {}).get("backups", [])
        self._setup_table(
            self.backup_table,
            [tr("operations.backupColIndex"), tr("operations.backupColDate"), tr("operations.backupColSize"), tr("operations.backupColPath")],
            sortable=True,
        )
        for row, path in enumerate(backups):
            self.backup_table.insertRow(row)
            try:
                stat = os.stat(path)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = str(stat.st_size)
            except:
                mtime, size = "-", "-"
            self.backup_table.setItem(row, 0, QTableWidgetItem(str(row+1)))
            self.backup_table.setItem(row, 1, QTableWidgetItem(mtime))
            self.backup_table.setItem(row, 2, QTableWidgetItem(size))
            self.backup_table.setItem(row, 3, QTableWidgetItem(path))
        self.backup_info.setText(tr("operations.foundBackups", count=len(backups)))

    def on_use_selected_backup(self):
        row = self.backup_table.currentRow()
        if row >= 0:
            path = self.backup_table.item(row, 3).text()
            self.rb_backup_path.setText(path)

    def on_rollback_latest(self):
        resp = self.bridge.list_backups(self.yaml_path_getter())
        backups = resp.get("result", {}).get("backups", []) if isinstance(resp, dict) else []
        if not backups:
            self.status_message.emit(tr("operations.noBackupsFound"), 4000, "error")
            return
        self._stage_rollback(backups[0])

    def on_rollback_selected(self):
        path = self.rb_backup_path.text().strip()
        if not path:
            self.status_message.emit(tr("operations.selectBackupPathFirst"), 3000, "error")
            return
        self._stage_rollback(path)

    def _stage_rollback(self, backup_path):
        """Stage rollback into Plan (human-in-the-loop)."""
        item = build_rollback_plan_item(
            backup_path=backup_path,
            source="human",
        )
        self.add_plan_items([item])

    # --- AUDIT TAB ---
    def _build_audit_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        filter_form = QFormLayout()

        self.audit_start_date = QDateEdit()
        self.audit_start_date.setCalendarPopup(True)
        self.audit_start_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_start_date.setDate(QDate.currentDate().addDays(-7))
        filter_form.addRow(tr("operations.from"), self.audit_start_date)

        self.audit_end_date = QDateEdit()
        self.audit_end_date.setCalendarPopup(True)
        self.audit_end_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_end_date.setDate(QDate.currentDate())
        filter_form.addRow(tr("operations.to"), self.audit_end_date)

        self.audit_action_filter = QComboBox()
        self.audit_action_filter.addItem(tr("operations.all"), "All")
        self.audit_action_filter.addItem(tr("operations.auditActionAddEntry"), "add_entry")
        self.audit_action_filter.addItem(tr("operations.auditActionRecordThaw"), "record_thaw")
        self.audit_action_filter.addItem(tr("operations.auditActionBatchThaw"), "batch_thaw")
        self.audit_action_filter.addItem(tr("operations.auditActionRollback"), "rollback")
        filter_form.addRow(tr("operations.auditAction"), self.audit_action_filter)

        self.audit_status_filter = QComboBox()
        self.audit_status_filter.addItem(tr("operations.all"), "All")
        self.audit_status_filter.addItem(tr("operations.auditStatusSuccess"), "success")
        self.audit_status_filter.addItem(tr("operations.auditStatusFailed"), "failed")
        filter_form.addRow(tr("operations.auditStatus"), self.audit_status_filter)

        layout.addLayout(filter_form)

        btn_row = QHBoxLayout()
        load_btn = QPushButton(tr("operations.loadAuditLog"))
        load_btn.clicked.connect(self.on_load_audit)
        btn_row.addWidget(load_btn)

        self.audit_guide_btn = QPushButton(tr("operations.auditGuideFromSelected"))
        self.audit_guide_btn.clicked.connect(self.on_generate_audit_guide)
        btn_row.addWidget(self.audit_guide_btn)

        self.audit_print_selected_btn = QPushButton(tr("operations.auditPrintSelectedGuide"))
        self.audit_print_selected_btn.clicked.connect(self.on_print_selected_audit_guide)
        btn_row.addWidget(self.audit_print_selected_btn)

        self.audit_rollback_selected_btn = QPushButton(tr("operations.auditRollbackFromSelected"))
        self.audit_rollback_selected_btn.clicked.connect(self.on_stage_rollback_from_selected_audit)
        btn_row.addWidget(self.audit_rollback_selected_btn)

        self.audit_backup_toggle_btn = QPushButton(tr("operations.showAdvancedRollback"))
        self.audit_backup_toggle_btn.clicked.connect(self.on_toggle_audit_backup_panel)
        btn_row.addWidget(self.audit_backup_toggle_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.audit_backup_panel = self._build_audit_backup_panel()
        self.audit_backup_panel.setVisible(False)
        layout.addWidget(self.audit_backup_panel)

        self.audit_info = QLabel(tr("operations.clickLoadAudit"))
        layout.addWidget(self.audit_info)

        self.audit_table = QTableWidget()
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audit_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.audit_table, 1)
        self._setup_table(
            self.audit_table,
            [tr("operations.colTimestamp"), tr("operations.colAction"), tr("operations.colActor"), tr("operations.colStatus"), tr("operations.colChannel"), tr("operations.colDetails")],
            sortable=True,
        )
        self.audit_table.cellClicked.connect(self._on_audit_row_clicked)

        return tab

    def on_toggle_audit_backup_panel(self):
        visible = not self.audit_backup_panel.isVisible()
        self.audit_backup_panel.setVisible(visible)
        self.audit_backup_toggle_btn.setText(
            tr("operations.hideAdvancedRollback") if visible else tr("operations.showAdvancedRollback")
        )
        if visible and self.backup_table.rowCount() == 0:
            self.on_refresh_backups()

    def on_load_audit(self):
        """Load and display audit events from JSONL file."""
        yaml_path = self.yaml_path_getter()
        yaml_abs = os.path.abspath(yaml_path)
        from lib.config import AUDIT_LOG_FILE
        audit_path = os.path.join(os.path.dirname(yaml_abs), AUDIT_LOG_FILE)

        if not os.path.isfile(audit_path):
            self.audit_info.setText(tr("operations.auditFileNotFound", path=audit_path))
            return

        start = self.audit_start_date.date().toString("yyyy-MM-dd")
        end = self.audit_end_date.date().toString("yyyy-MM-dd")
        action_filter = self.audit_action_filter.currentData() or self.audit_action_filter.currentText()
        status_filter = self.audit_status_filter.currentData() or self.audit_status_filter.currentText()

        events = []
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = ev.get("timestamp", "")[:10]
                    if ts < start or ts > end:
                        continue
                    if action_filter != "All" and ev.get("action") != action_filter:
                        continue
                    if status_filter != "All" and ev.get("status") != status_filter:
                        continue

                    events.append(ev)
        except Exception as exc:
            self.audit_info.setText(tr("operations.failedToLoadAudit", error=exc))
            return

        # Newest first
        events.reverse()
        self._audit_events = events

        self._setup_table(
            self.audit_table,
            [
                tr("operations.colTimestamp"),
                tr("operations.colAction"),
                tr("operations.colActor"),
                tr("operations.colStatus"),
                tr("operations.colChannel"),
                tr("operations.colDetails"),
            ],
            sortable=True,
        )
        for row, ev in enumerate(events):
            self.audit_table.insertRow(row)
            ts_item = QTableWidgetItem(ev.get("timestamp", ""))
            ts_item.setData(Qt.UserRole, row)
            self.audit_table.setItem(row, 0, ts_item)
            self.audit_table.setItem(row, 1, QTableWidgetItem(ev.get("action", "")))
            self.audit_table.setItem(row, 2, QTableWidgetItem(ev.get("actor_type", "")))
            self.audit_table.setItem(row, 3, QTableWidgetItem(ev.get("status", "")))
            self.audit_table.setItem(row, 4, QTableWidgetItem(ev.get("channel", "")))

            details = ev.get("details") or {}
            error = ev.get("error") or {}
            if ev.get("status") == "failed":
                summary = str(error.get("message", ""))[:80] if error else str(details)[:80]
            else:
                summary = json.dumps(details, ensure_ascii=False)[:80] if details else ""
            self.audit_table.setItem(row, 5, QTableWidgetItem(summary))

        self.audit_info.setText(
            tr("operations.auditEventsShown", count=len(events), start=start, end=end)
        )

    def _on_audit_row_clicked(self, row, _col):
        """Show summary of selected audit event."""
        if row >= len(self._audit_events):
            return
        ev = self._audit_events[row]
        action = str(ev.get("action") or "")
        status = str(ev.get("status") or "")
        actor = str(ev.get("actor_id") or "")
        channel = str(ev.get("channel") or "")
        ts = str(ev.get("timestamp") or "")

        details = ev.get("details") or {}
        error = ev.get("error") or {}
        backup_path = ev.get("backup_path") or ""

        title_color = "var(--status-success)" if status == "success" else "var(--status-error)"
        lines = [f"<b style='color: {title_color};'>{tr('operations.audit')}：{action} ({status})</b>"]
        if ts:
            lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.timeLabel')}</span> {ts}")
        if actor:
            lines.append(
                f"<span style='color: var(--status-muted);'>{tr('operations.actorLabel')}</span> {actor} ({channel})"
            )
        if backup_path:
            lines.append(
                f"<span style='color: var(--status-muted);'>{tr('operations.backupLabel')}</span> {os.path.basename(str(backup_path))}"
            )

        if status == "failed" and isinstance(error, dict) and error:
            if error.get("error_code"):
                lines.append(
                    f"<span style='color: var(--status-muted);'>{tr('operations.errorLabel')}</span> {error.get('error_code')}"
                )
            if error.get("message"):
                lines.append(str(error.get("message")))
        elif isinstance(details, dict) and details:
            try:
                preview = json.dumps(details, ensure_ascii=False)
            except Exception:
                preview = str(details)
            lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.detailsLabel')}</span> {preview}")

        self._set_result_summary_html(lines)
        border = "var(--success)" if status == "success" else "var(--error)"
        self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", border))
        self.result_card.setVisible(True)

    def _get_selected_audit_events(self):
        model = self.audit_table.selectionModel()
        if model is None:
            return []
        selected = []
        for idx in model.selectedRows():
            row = idx.row()
            item = self.audit_table.item(row, 0)
            source_idx = item.data(Qt.UserRole) if item is not None else row
            try:
                event_idx = int(source_idx)
            except (TypeError, ValueError):
                event_idx = row
            if 0 <= event_idx < len(self._audit_events):
                selected.append((event_idx, self._audit_events[event_idx]))

        dedup = {}
        for event_idx, event in selected:
            dedup[event_idx] = event
        ordered = [dedup[key] for key in sorted(dedup)]
        return ordered

    def _build_audit_source_event(self, event):
        if not isinstance(event, dict):
            return {}
        source_event = {}
        for key in ("timestamp", "action", "trace_id", "session_id", "actor_id", "channel"):
            value = event.get(key)
            if value not in (None, ""):
                source_event[str(key)] = value
        return source_event

    def _apply_generated_audit_guide(self, guide, selected_count, print_now=False):
        items = list(guide.get("items") or [])
        warnings = list(guide.get("warnings") or [])
        stats = dict(guide.get("stats") or {})

        if not items:
            lines = [
                f"<b style='color: var(--status-error);'>{tr('operations.noPrintableFromSelection')}</b>",
                tr("operations.selectedEvents", count=selected_count),
            ]
            if warnings:
                preview = "<br/>".join(str(w) for w in warnings[:3])
                more = (
                    f"<br/><span style='color: var(--status-muted);'>{tr('operations.moreWarnings', count=len(warnings) - 3)}</span>"
                    if len(warnings) > 3
                    else ""
                )
                lines.append(
                    f"{tr('operations.warningsLabel')} {len(warnings)}<br/>{preview}{more}"
                )
            self._set_result_summary_html(lines)
            self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", "var(--error)"))
            self.result_card.setVisible(True)
            self.status_message.emit(tr("operations.noPrintableAuditGuide"), 3500, "error")
            return

        self._last_printable_plan = list(items)
        lines = [
            f"<b style='color: var(--status-success);'>{tr('operations.auditGuideGenerated')}</b>",
            tr("operations.selectedEvents", count=selected_count),
            tr("operations.finalOperations", count=len(items)),
        ]
        if warnings:
            preview = "<br/>".join(str(w) for w in warnings[:3])
            more = (
                f"<br/><span style='color: var(--status-muted);'>{tr('operations.moreWarnings', count=len(warnings) - 3)}</span>"
                if len(warnings) > 3
                else ""
            )
            lines.append(
                f"{tr('operations.warningsLabel')} {len(warnings)}<br/>{preview}{more}"
            )
        self._set_result_summary_html(lines)
        self.result_card.setStyleSheet(self._result_card_base_style.replace("var(--border-weak)", "var(--success)"))
        self.result_card.setVisible(True)
        self.status_message.emit(
            tr("operations.generatedFinalOperations", count=len(items)),
            2500,
            "info",
        )

        if print_now:
            self._print_operation_sheet(items, tr("operations.auditGuideOpened"))

    def on_generate_audit_guide(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.status_message.emit(tr("operations.selectAuditRowsFirst"), 2500, "error")
            return
        guide = build_operation_guide_from_audit_events(selected_events)
        self._apply_generated_audit_guide(guide, selected_count=len(selected_events), print_now=False)

    def on_print_selected_audit_guide(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.status_message.emit(tr("operations.selectAuditRowsFirst"), 2500, "error")
            return
        guide = build_operation_guide_from_audit_events(selected_events)
        self._apply_generated_audit_guide(guide, selected_count=len(selected_events), print_now=True)

    def on_stage_rollback_from_selected_audit(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.status_message.emit(tr("operations.selectAuditRowsFirst"), 2500, "error")
            return
        if len(selected_events) != 1:
            self.status_message.emit(tr("operations.selectSingleAuditRow"), 3000, "error")
            return

        event = selected_events[0]
        backup_path = str(event.get("backup_path") or "").strip()
        if not backup_path:
            self.status_message.emit(tr("operations.selectedAuditNoBackup"), 3000, "error")
            return

        item = build_rollback_plan_item(
            backup_path=backup_path,
            source="human",
            source_event=self._build_audit_source_event(event),
        )
        self.add_plan_items([item])

        staged = any(
            str(it.get("action") or "").lower() == "rollback"
            and str((it.get("payload") or {}).get("backup_path") or "") == backup_path
            for it in self._plan_store.list_items()
        )
        if staged:
            self.status_message.emit(
                tr("operations.auditRollbackStaged", backup=os.path.basename(str(backup_path))),
                2500,
                "info",
            )

    # --- UNDO ---

    def _enable_undo(self, timeout_sec=30):
        """Enable the undo button with an auto-disable countdown."""
        self.undo_btn.setVisible(True)
        self.undo_btn.setEnabled(True)
        self._undo_remaining = timeout_sec
        self.undo_btn.setText(
            tr(
                "operations.undoLastWithCountdown",
                operation=tr("operations.undoLast"),
                seconds=self._undo_remaining,
            )
        )

        if self._undo_timer is not None:
            self._undo_timer.stop()

        self._undo_timer = QTimer(self)
        self._undo_timer.timeout.connect(self._undo_tick)
        self._undo_timer.start(1000)

    def _undo_tick(self):
        self._undo_remaining -= 1
        if self._undo_remaining <= 0:
            self._disable_undo()
        else:
            self.undo_btn.setText(
                tr(
                    "operations.undoLastWithCountdown",
                    operation=tr("operations.undoLast"),
                    seconds=self._undo_remaining,
                )
            )

    def _disable_undo(self):
        if self._undo_timer is not None:
            self._undo_timer.stop()
            self._undo_timer = None
        self.undo_btn.setEnabled(False)
        self.undo_btn.setVisible(False)
        self.undo_btn.setText(tr("operations.undoLast"))
        self._last_operation_backup = None
        self._last_executed_plan = []

    def on_undo_last(self):
        if not self._last_operation_backup:
            self.status_message.emit(tr("operations.noOperationToUndo"), 3000, "error")
            return

        yaml_path = os.path.abspath(str(self.yaml_path_getter()))
        confirm_lines = self._build_rollback_confirmation_lines(
            backup_path=self._last_operation_backup,
            yaml_path=yaml_path,
            include_action_prefix=False,
        )
        if not self._confirm_execute(
            tr("operations.undo"),
            "\n".join(confirm_lines),
        ):
            return

        executed_plan_backup = list(self._last_executed_plan)
        response = self.bridge.rollback(
            self.yaml_path_getter(),
            backup_path=self._last_operation_backup,
        )
        self._disable_undo()
        self._handle_response(response, tr("operations.undo"))
        if response.get("ok") and executed_plan_backup:
            self._plan_store.replace_all(executed_plan_backup)
            self._refresh_plan_table()

            action_counts = {}
            for item in executed_plan_backup:
                action = str(item.get("action") or "?")
                action_counts[action] = action_counts.get(action, 0) + 1
            self._emit_operation_event(
                {
                    "type": "plan_restored",
                    "source": "operations_panel",
                    "restored_count": len(executed_plan_backup),
                    "action_counts": action_counts,
                }
            )
