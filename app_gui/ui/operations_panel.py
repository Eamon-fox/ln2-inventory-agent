import json
import os
import csv
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QDate, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, 
    QHeaderView, QFileDialog, QMessageBox, QGroupBox, 
    QFormLayout, QDateEdit, QSpinBox, QTextEdit
)
from app_gui.ui.utils import positions_to_text
from lib.tool_api import parse_batch_entries
from lib.validators import parse_positions

class OperationsPanel(QWidget):
    operation_completed = Signal(bool) # success?
    status_message = Signal(str, int, str) # msg, timeout, level
    
    def __init__(self, bridge, yaml_path_getter):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        
        self.records_cache = {}
        self.current_operation_mode = "thaw"
        self.query_last_mode = "records"
        self.t_prefill_source = None
        self._default_date_anchor = QDate.currentDate()
        self._last_operation_backup = None
        self._undo_timer = None
        self._undo_remaining = 0
        self._audit_events = []

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Mode Selection
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Manual Action"))
        mode_row.addStretch()

        self.op_mode_combo = QComboBox()
        modes = [
            ("thaw", "Takeout"),
            ("add", "Add Entry"),
            ("query", "Query"),
            ("rollback", "Rollback"),
            ("audit", "Audit Log"),
        ]
        for mode_key, mode_label in modes:
            self.op_mode_combo.addItem(mode_label, mode_key)
        self.op_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_row.addWidget(self.op_mode_combo)
        layout.addLayout(mode_row)

        # Stack
        self.op_stack = QStackedWidget()
        self.op_mode_indexes = {
            "add": self.op_stack.addWidget(self._build_add_tab()),
            "thaw": self.op_stack.addWidget(self._build_thaw_tab()),
            "query": self.op_stack.addWidget(self._build_query_tab()),
            "rollback": self.op_stack.addWidget(self._build_rollback_tab()),
            "audit": self.op_stack.addWidget(self._build_audit_tab()),
        }
        layout.addWidget(self.op_stack, 3)

        # Result Summary Card
        self.result_card = QGroupBox("Last Result")
        result_card_layout = QVBoxLayout(self.result_card)
        result_card_layout.setContentsMargins(8, 8, 8, 8)
        self.result_summary = QLabel("No operations performed yet.")
        self.result_summary.setWordWrap(True)
        self.result_summary.setTextFormat(Qt.RichText)
        result_card_layout.addWidget(self.result_summary)
        self.result_card.setVisible(False)
        layout.addWidget(self.result_card)

        # Undo Button
        self.undo_btn = QPushButton("Undo Last Operation")
        self.undo_btn.setEnabled(False)
        self.undo_btn.setStyleSheet(
            "QPushButton { background-color: #92400e; color: white; font-weight: bold;"
            " border: 1px solid #78350f; }"
            " QPushButton:hover { background-color: #b45309; }"
            " QPushButton:disabled { background-color: #1e293b; color: #64748b; }"
        )
        self.undo_btn.clicked.connect(self.on_undo_last)
        layout.addWidget(self.undo_btn)

        # Output Panel
        output_header = QHBoxLayout()
        self.output_toggle_btn = QPushButton("Show Raw JSON")
        self.output_toggle_btn.setCheckable(True)
        self.output_toggle_btn.toggled.connect(self.on_toggle_output)
        output_header.addWidget(self.output_toggle_btn)
        output_header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self.output.clear())
        output_header.addWidget(clear_btn)
        layout.addLayout(output_header)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(180)
        self.output.setVisible(False)
        layout.addWidget(self.output, 2)

        self.set_mode("thaw")

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

    def on_toggle_output(self, checked):
        visible = bool(checked)
        self.output.setVisible(visible)
        self.output_toggle_btn.setText("Hide Raw JSON" if visible else "Show Raw JSON")

    def on_toggle_batch_section(self, checked):
        visible = bool(checked)
        if hasattr(self, "t_batch_group"):
            self.t_batch_group.setVisible(visible)
        if hasattr(self, "t_batch_toggle_btn"):
            self.t_batch_toggle_btn.setText("Hide Batch Operation" if visible else "Show Batch Operation")

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

    def set_prefill(self, source_info):
        self.t_prefill_source = source_info
        if "record_id" in source_info:
            self.t_id.setValue(int(source_info["record_id"]))
        if "position" in source_info:
            self.t_position.setValue(int(source_info["position"]))
        self.t_action.setCurrentText("Takeout")
        self._refresh_thaw_record_context()
        self.set_mode("thaw")

    def set_add_prefill(self, source_info):
        """Pre-fill the Add Entry form with box and position from overview."""
        if "box" in source_info:
            self.a_box.setValue(int(source_info["box"]))
        if "position" in source_info:
            self.a_positions.setText(str(source_info["position"]))
        self.set_mode("add")

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

    # --- ADD TAB ---
    def _build_add_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.a_parent = QLineEdit()
        self.a_short = QLineEdit()
        self.a_box = QSpinBox()
        self.a_box.setRange(1, 99)
        self.a_positions = QLineEdit()
        self.a_positions.setPlaceholderText("e.g. 30,31 or 30-32")
        self.a_date = QDateEdit()
        self.a_date.setCalendarPopup(True)
        self.a_date.setDisplayFormat("yyyy-MM-dd")
        self.a_date.setDate(QDate.currentDate())
        self.a_plasmid = QLineEdit()
        self.a_plasmid_id = QLineEdit()
        self.a_note = QLineEdit()

        form.addRow("Parent Cell Line", self.a_parent)
        form.addRow("Short Name", self.a_short)
        form.addRow("Box", self.a_box)
        form.addRow("Positions", self.a_positions)
        form.addRow("Frozen Date", self.a_date)
        form.addRow("Plasmid Name", self.a_plasmid)
        form.addRow("Plasmid ID", self.a_plasmid_id)
        form.addRow("Note", self.a_note)
        layout.addLayout(form)

        self.a_apply_btn = QPushButton("Execute Add Entry")
        self._style_execute_button(self.a_apply_btn)
        self.a_apply_btn.clicked.connect(self.on_add_entry)
        layout.addWidget(self.a_apply_btn)
        layout.addStretch(1)
        return tab

    # --- THAW TAB ---
    def _build_thaw_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        single = QGroupBox("Single Thaw / Takeout")
        single_form = QFormLayout(single)
        self.t_id = QSpinBox()
        self.t_id.setRange(1, 999999)
        self.t_id.valueChanged.connect(self._refresh_thaw_record_context)
        self.t_position = QSpinBox()
        self.t_position.setRange(1, 999)
        self.t_position.valueChanged.connect(self._refresh_thaw_record_context)
        self.t_date = QDateEdit()
        self.t_date.setCalendarPopup(True)
        self.t_date.setDisplayFormat("yyyy-MM-dd")
        self.t_date.setDate(QDate.currentDate())
        self.t_action = QComboBox()
        self.t_action.addItems(["Takeout", "Thaw", "Discard"])
        self.t_note = QLineEdit()

        single_form.addRow("Record ID", self.t_id)
        single_form.addRow("Position", self.t_position)
        single_form.addRow("Date", self.t_date)
        single_form.addRow("Action", self.t_action)
        single_form.addRow("Note", self.t_note)

        self.t_apply_btn = QPushButton("Execute Single Operation")
        self._style_execute_button(self.t_apply_btn)
        self.t_apply_btn.clicked.connect(self.on_record_thaw)
        single_form.addRow("", self.t_apply_btn)
        layout.addWidget(single)

        context_box = QGroupBox("Selected Record Context")
        context_form = QFormLayout(context_box)
        self.t_ctx_status = QLabel("No prefill yet.")
        self.t_ctx_status.setWordWrap(True)
        self.t_ctx_source = QLabel("-")
        self.t_ctx_id = QLabel("-")
        self.t_ctx_cell = QLabel("-")
        self.t_ctx_short = QLabel("-")
        self.t_ctx_box = QLabel("-")
        self.t_ctx_positions = QLabel("-")
        self.t_ctx_target = QLabel("-")
        self.t_ctx_check = QLabel("-")
        self.t_ctx_frozen = QLabel("-")
        self.t_ctx_plasmid = QLabel("-")
        self.t_ctx_events = QLabel("-")
        self.t_ctx_note = QLabel("-")

        context_form.addRow("Status", self.t_ctx_status)
        context_form.addRow("Source", self.t_ctx_source)
        context_form.addRow("ID", self.t_ctx_id)
        context_form.addRow("Cell", self.t_ctx_cell)
        context_form.addRow("Short", self.t_ctx_short)
        context_form.addRow("Box", self.t_ctx_box)
        context_form.addRow("All Pos", self.t_ctx_positions)
        context_form.addRow("Target", self.t_ctx_target)
        context_form.addRow("Check", self.t_ctx_check)
        context_form.addRow("Frozen", self.t_ctx_frozen)
        context_form.addRow("Plasmid", self.t_ctx_plasmid)
        context_form.addRow("History", self.t_ctx_events)
        context_form.addRow("Note", self.t_ctx_note)
        layout.addWidget(context_box)

        self.t_batch_toggle_btn = QPushButton("Show Batch Operation")
        self.t_batch_toggle_btn.setCheckable(True)
        self.t_batch_toggle_btn.toggled.connect(self.on_toggle_batch_section)
        layout.addWidget(self.t_batch_toggle_btn)

        self.t_batch_group = QGroupBox("Batch Thaw / Takeout")
        batch_form = QFormLayout(self.t_batch_group)
        self.b_entries = QLineEdit()
        self.b_entries.setPlaceholderText("e.g. 182:23,183:41")
        self.b_date = QDateEdit()
        self.b_date.setCalendarPopup(True)
        self.b_date.setDisplayFormat("yyyy-MM-dd")
        self.b_date.setDate(QDate.currentDate())
        self.b_action = QComboBox()
        self.b_action.addItems(["Takeout", "Thaw", "Discard"])
        self.b_note = QLineEdit()

        batch_form.addRow("Entries (text)", self.b_entries)

        # Mini-table for visual batch entry
        self.b_table = QTableWidget()
        self.b_table.setColumnCount(2)
        self.b_table.setHorizontalHeaderLabels(["Record ID", "Position"])
        self.b_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.b_table.setRowCount(1)
        self.b_table.setMaximumHeight(120)
        batch_form.addRow("Or use table", self.b_table)

        table_btn_widget = QWidget()
        table_btn_row = QHBoxLayout(table_btn_widget)
        table_btn_row.setContentsMargins(0, 0, 0, 0)
        b_add_row_btn = QPushButton("+ Row")
        b_add_row_btn.clicked.connect(self._batch_add_row)
        b_remove_row_btn = QPushButton("- Row")
        b_remove_row_btn.clicked.connect(self._batch_remove_row)
        table_btn_row.addWidget(b_add_row_btn)
        table_btn_row.addWidget(b_remove_row_btn)
        table_btn_row.addStretch()
        batch_form.addRow("", table_btn_widget)

        batch_form.addRow("Date", self.b_date)
        batch_form.addRow("Action", self.b_action)
        batch_form.addRow("Note", self.b_note)

        self.b_apply_btn = QPushButton("Execute Batch Operation")
        self._style_execute_button(self.b_apply_btn)
        self.b_apply_btn.clicked.connect(self.on_batch_thaw)
        batch_form.addRow("", self.b_apply_btn)
        layout.addWidget(self.t_batch_group)
        self.on_toggle_batch_section(False)
        layout.addStretch(1)
        return tab

    # --- QUERY TAB ---
    def _build_query_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.q_cell = QLineEdit()
        self.q_short = QLineEdit()
        self.q_plasmid = QLineEdit()
        self.q_plasmid_id = QLineEdit()
        self.q_box = QSpinBox()
        self.q_box.setRange(0, 99)
        self.q_box.setSpecialValueText("Any")
        self.q_position = QSpinBox()
        self.q_position.setRange(0, 999)
        self.q_position.setSpecialValueText("Any")

        form.addRow("Cell", self.q_cell)
        form.addRow("Short Name", self.q_short)
        form.addRow("Plasmid", self.q_plasmid)
        form.addRow("Plasmid ID", self.q_plasmid_id)
        form.addRow("Box", self.q_box)
        form.addRow("Position", self.q_position)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        query_btn = QPushButton("Query Records")
        query_btn.clicked.connect(self.on_query_records)
        btn_row.addWidget(query_btn)

        empty_btn = QPushButton("List Empty Positions")
        empty_btn.clicked.connect(self.on_list_empty)
        btn_row.addWidget(empty_btn)

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self.on_export_query_csv)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

        self.query_info = QLabel("Run a query to show records in table format.")
        layout.addWidget(self.query_info)

        self.query_table = QTableWidget()
        layout.addWidget(self.query_table, 1)
        self._setup_table(
            self.query_table,
            ["ID", "Cell", "Short", "Box", "Positions", "Frozen At", "Plasmid ID", "Note"],
            sortable=False,
        )
        return tab

    # --- ROLLBACK TAB ---
    def _build_rollback_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.rb_backup_path = QLineEdit()
        self.rb_backup_path.setPlaceholderText("Leave empty to rollback latest backup")

        form.addRow("Backup Path", self.rb_backup_path)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Backups")
        refresh_btn.clicked.connect(self.on_refresh_backups)
        btn_row.addWidget(refresh_btn)

        select_btn = QPushButton("Use Selected Backup")
        select_btn.clicked.connect(self.on_use_selected_backup)
        btn_row.addWidget(select_btn)

        rollback_latest_btn = QPushButton("Rollback Latest")
        rollback_latest_btn.clicked.connect(self.on_rollback_latest)
        btn_row.addWidget(rollback_latest_btn)

        rollback_selected_btn = QPushButton("Rollback Selected/Path")
        rollback_selected_btn.clicked.connect(self.on_rollback_selected)
        btn_row.addWidget(rollback_selected_btn)
        layout.addLayout(btn_row)

        self.backup_info = QLabel("Backups will be listed here.")
        layout.addWidget(self.backup_info)

        self.backup_table = QTableWidget()
        layout.addWidget(self.backup_table, 1)
        self._setup_table(
            self.backup_table,
            ["#", "Updated", "Size (B)", "Path"],
            sortable=True,
        )
        return tab

    # --- LOGIC ---

    def _style_execute_button(self, btn):
        btn.setStyleSheet("""
            QPushButton {
                background-color: #b91c1c;
                color: white;
                font-weight: bold;
                border: 1px solid #7f1d1d;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)

    def _ensure_today_defaults(self):
        today = QDate.currentDate()
        anchor = getattr(self, "_default_date_anchor", today)
        if today == anchor:
            return

        for attr in ("a_date", "t_date", "b_date"):
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
        target_position = self.t_position.value()
        record = self._lookup_record(record_id)

        source_text = "-"
        if self.t_prefill_source:
            source_box = self.t_prefill_source.get("box")
            source_position = self.t_prefill_source.get("position")
            if source_box is not None and source_position is not None:
                source_text = f"Box {source_box}:{source_position}"
        self.t_ctx_source.setText(source_text)

        self.t_ctx_target.setText(str(target_position) if target_position else "-")
        self.t_ctx_id.setText(str(record_id) if record_id else "-")

        if not record:
            self.t_ctx_status.setText("Record not found in cache.")
            self.t_ctx_status.setStyleSheet("color: #b45309;")
            for lbl in [self.t_ctx_cell, self.t_ctx_short, self.t_ctx_box, self.t_ctx_positions, 
                        self.t_ctx_check, self.t_ctx_frozen, self.t_ctx_plasmid, self.t_ctx_events, self.t_ctx_note]:
                lbl.setText("-")
            return

        if self.t_prefill_source:
            self.t_ctx_status.setText("Record loaded - form auto-filled.")
        else:
            self.t_ctx_status.setText("Record context loaded.")
        self.t_ctx_status.setStyleSheet("color: #15803d;")
        
        self.t_ctx_cell.setText(str(record.get("parent_cell_line") or "-"))
        self.t_ctx_short.setText(str(record.get("short_name") or "-"))
        self.t_ctx_box.setText(str(record.get("box") or "-"))

        positions = record.get("positions") or []
        self.t_ctx_positions.setText(positions_to_text(positions))
        self.t_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
        plasmid = record.get("plasmid_name") or record.get("plasmid_id") or "-"
        self.t_ctx_plasmid.setText(str(plasmid))
        self.t_ctx_note.setText(str(record.get("note") or "-"))
        
        # History
        events = record.get("thaw_events") or []
        if events:
            last = events[-1]
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_pos = positions_to_text(last.get("positions") or [])
            self.t_ctx_events.setText(f"{len(events)} events; last: {last_date} {last_action} [{last_pos}]")
        else:
            self.t_ctx_events.setText("No thaw history")

        # Check
        pos_ok = False
        try:
            pos_ok = int(target_position) in {int(p) for p in positions}
        except Exception: pass
        
        if pos_ok:
            self.t_ctx_check.setText("OK - position in record")
            self.t_ctx_check.setStyleSheet("color: #15803d;")
        else:
            self.t_ctx_check.setText("WARNING - position NOT in record")
            self.t_ctx_check.setStyleSheet("color: #b91c1c;")

    def _confirm_execute(self, title, details):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText("This operation will modify inventory YAML.")
        msg.setInformativeText(details)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        return msg.exec() == QMessageBox.Yes

    def on_add_entry(self):
        self._ensure_today_defaults()
        yaml_path = self.yaml_path_getter()
        positions_text = self.a_positions.text().strip()

        try:
            positions = parse_positions(positions_text)
        except ValueError as exc:
            self.status_message.emit(str(exc), 5000, "error")
            return

        details = "\n".join([
            f"Cell: {self.a_parent.text()}",
            f"Short: {self.a_short.text()}",
            f"Box: {self.a_box.value()}",
            f"Positions: {positions_text}",
        ])
        if not self._confirm_execute("Confirm Add", details):
            return

        response = self.bridge.add_entry(
            yaml_path=yaml_path,
            parent_cell_line=self.a_parent.text(),
            short_name=self.a_short.text(),
            box=self.a_box.value(),
            positions=positions,
            frozen_at=self.a_date.date().toString("yyyy-MM-dd"),
            plasmid_name=self.a_plasmid.text() or None,
            plasmid_id=self.a_plasmid_id.text() or None,
            note=self.a_note.text() or None,
        )
        self._handle_response(response, "Add Entry")

    def on_record_thaw(self):
        self._ensure_today_defaults()
        yaml_path = self.yaml_path_getter()

        details = (
            f"ID: {self.t_id.value()}\n"
            f"Position: {self.t_position.value()}\n"
            f"Action: {self.t_action.currentText()}"
        )
        if not self._confirm_execute("Confirm Operation", details):
            return

        response = self.bridge.record_thaw(
            yaml_path=yaml_path,
            record_id=self.t_id.value(),
            position=self.t_position.value(),
            date_str=self.t_date.date().toString("yyyy-MM-dd"),
            action=self.t_action.currentText(),
            note=self.t_note.text() or None,
        )
        self._handle_response(response, "Single Operation")

    def _batch_add_row(self):
        self.b_table.insertRow(self.b_table.rowCount())

    def _batch_remove_row(self):
        row = self.b_table.currentRow()
        if row >= 0:
            self.b_table.removeRow(row)
        elif self.b_table.rowCount() > 0:
            self.b_table.removeRow(self.b_table.rowCount() - 1)

    def _collect_batch_from_table(self):
        """Collect entries from the mini-table. Returns list of dicts or None if empty."""
        entries = []
        for row in range(self.b_table.rowCount()):
            id_item = self.b_table.item(row, 0)
            pos_item = self.b_table.item(row, 1)
            if id_item and pos_item:
                id_text = id_item.text().strip()
                pos_text = pos_item.text().strip()
                if id_text and pos_text:
                    try:
                        entries.append({
                            "record_id": int(id_text),
                            "position": int(pos_text),
                        })
                    except ValueError:
                        raise ValueError(f"Row {row + 1}: invalid Record ID or Position")
        return entries if entries else None

    def on_batch_thaw(self):
        self._ensure_today_defaults()
        yaml_path = self.yaml_path_getter()

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

        summary = ", ".join(f"{e.get('record_id')}:{e.get('position')}" for e in entries)
        if not self._confirm_execute("Confirm Batch", f"Entries: {summary}"):
            return

        response = self.bridge.batch_thaw(
            yaml_path=yaml_path,
            entries=entries,
            date_str=self.b_date.date().toString("yyyy-MM-dd"),
            action=self.b_action.currentText(),
            note=self.b_note.text() or None,
        )
        self._handle_response(response, "Batch Operation")

    def _handle_response(self, response, context):
        payload = response if isinstance(response, dict) else {}
        self.output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._display_result_summary(response, context)

        ok = payload.get("ok", False)
        msg = payload.get("message", "Unknown result")

        if ok:
            self.status_message.emit(f"{context}: Success", 3000, "success")
            self.operation_completed.emit(True)
            # Enable undo if backup_path available
            backup_path = payload.get("backup_path")
            if backup_path:
                self._last_operation_backup = backup_path
                self._enable_undo(timeout_sec=30)
        else:
            self.status_message.emit(f"{context} Failed: {msg}", 5000, "error")
            self.operation_completed.emit(False)

    def _display_result_summary(self, response, context):
        """Show a human-readable summary card for the operation result."""
        payload = response if isinstance(response, dict) else {}
        ok = payload.get("ok", False)
        preview = payload.get("preview", {}) or {}
        result = payload.get("result", {}) or {}

        if ok:
            lines = [f"<b style='color: #22c55e;'>{context}: Success</b>"]

            if context == "Add Entry":
                new_id = result.get("new_id", "?")
                cell = preview.get("parent_cell_line", "")
                short = preview.get("short_name", "")
                box = preview.get("box", "")
                positions = preview.get("positions", [])
                pos_text = ",".join(str(p) for p in positions)
                lines.append(f"Added ID {new_id}: {cell} / {short} to Box {box}, Pos [{pos_text}]")

            elif context == "Single Operation":
                rid = preview.get("record_id", "?")
                action = preview.get("action_en", preview.get("action_cn", ""))
                pos = preview.get("position", "?")
                before = preview.get("positions_before", [])
                after = preview.get("positions_after", [])
                lines.append(f"ID {rid}: {action} position {pos}")
                if before or after:
                    lines.append(
                        f"Positions: [{','.join(str(p) for p in before)}]"
                        f" -> [{','.join(str(p) for p in after)}]"
                    )

            elif context == "Batch Operation":
                count = result.get("count", preview.get("count", 0))
                ids = result.get("record_ids", [])
                lines.append(f"Processed {count} entries on IDs: {', '.join(str(i) for i in ids)}")

            elif context == "Rollback" or context == "Undo":
                restored = result.get("restored_from", "?")
                lines.append(f"Restored from: {os.path.basename(str(restored))}")

            self.result_summary.setText("<br/>".join(lines))
            self.result_card.setStyleSheet("QGroupBox { border: 1px solid #22c55e; }")
        else:
            msg = payload.get("message", "Unknown error")
            error_code = payload.get("error_code", "")
            lines = [f"<b style='color: #ef4444;'>{context}: Failed</b>"]
            lines.append(str(msg))
            if error_code:
                lines.append(f"<span style='color: #94a3b8;'>Code: {error_code}</span>")
            self.result_summary.setText("<br/>".join(lines))
            self.result_card.setStyleSheet("QGroupBox { border: 1px solid #ef4444; }")

        self.result_card.setVisible(True)

    # --- Query & Rollback Stubs (simplified) ---
    def on_query_records(self):
        box = self.q_box.value()
        box_val = box if box > 0 else None
        pos = self.q_position.value()
        pos_val = pos if pos > 0 else None
        
        response = self.bridge.query_inventory(
            self.yaml_path_getter(),
            cell=self.q_cell.text() or None,
            short=self.q_short.text() or None,
            plasmid=self.q_plasmid.text() or None,
            plasmid_id=self.q_plasmid_id.text() or None,
            box=box_val,
            position=pos_val
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
        self.output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

        if not payload.get("ok", False):
            self.status_message.emit(
                f"Query failed: {payload.get('message', 'Unknown result')}",
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
        self.output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

        if not payload.get("ok", False):
            self.status_message.emit(
                f"List empty failed: {payload.get('message', 'Unknown result')}",
                5000,
                "error",
            )

    def _render_query_results(self, records):
        self._setup_table(self.query_table, ["ID", "Cell", "Short", "Box", "Positions", "Frozen", "Plasmid", "Note"])
        rows = [rec for rec in records if isinstance(rec, dict)]
        for row, rec in enumerate(rows):
            self.query_table.insertRow(row)
            self.query_table.setItem(row, 0, QTableWidgetItem(str(rec.get("id"))))
            self.query_table.setItem(row, 1, QTableWidgetItem(str(rec.get("parent_cell_line"))))
            self.query_table.setItem(row, 2, QTableWidgetItem(str(rec.get("short_name"))))
            self.query_table.setItem(row, 3, QTableWidgetItem(str(rec.get("box"))))
            self.query_table.setItem(row, 4, QTableWidgetItem(positions_to_text(rec.get("positions"))))
            self.query_table.setItem(row, 5, QTableWidgetItem(str(rec.get("frozen_at"))))
            self.query_table.setItem(row, 6, QTableWidgetItem(str(rec.get("plasmid_id", ""))))
            self.query_table.setItem(row, 7, QTableWidgetItem(str(rec.get("note", ""))))
        self.query_info.setText(f"Found {len(rows)} records.")

    def _render_empty_results(self, boxes):
        self._setup_table(self.query_table, ["Box", "Empty/Total", "Positions"], sortable=False)
        for row, item in enumerate(boxes):
            self.query_table.insertRow(row)
            self.query_table.setItem(row, 0, QTableWidgetItem(str(item.get("box"))))
            self.query_table.setItem(row, 1, QTableWidgetItem(f"{item.get('empty_count')}/{item.get('total_slots')}"))
            
            pos_list = item.get("empty_positions", [])
            preview = ",".join(str(p) for p in pos_list[:20])
            if len(pos_list) > 20: preview += "..."
            self.query_table.setItem(row, 2, QTableWidgetItem(preview))
        self.query_info.setText(f"Found {len(boxes)} boxes with empty slots.")

    def on_export_query_csv(self):
        if self.query_table.rowCount() == 0: return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if not path: return
        
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [self.query_table.horizontalHeaderItem(i).text() for i in range(self.query_table.columnCount())]
                writer.writerow(headers)
                for r in range(self.query_table.rowCount()):
                    row = [self.query_table.item(r, c).text() for c in range(self.query_table.columnCount())]
                    writer.writerow(row)
            self.status_message.emit(f"Exported to {path}", 3000, "success")
        except Exception as e:
            self.status_message.emit(f"Export failed: {e}", 5000, "error")

    def on_refresh_backups(self):
        # Implementation for refresh backups
        resp = self.bridge.list_backups(self.yaml_path_getter())
        backups = resp.get("result", {}).get("backups", [])
        self._setup_table(self.backup_table, ["#", "Date", "Size", "Path"])
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
        self.backup_info.setText(f"Found {len(backups)} backups.")

    def on_use_selected_backup(self):
        row = self.backup_table.currentRow()
        if row >= 0:
            path = self.backup_table.item(row, 3).text()
            self.rb_backup_path.setText(path)

    def on_rollback_latest(self):
        self._do_rollback(None)

    def on_rollback_selected(self):
        path = self.rb_backup_path.text().strip()
        if not path:
            self.status_message.emit("Please select a backup path first.", 3000, "error")
            return
        self._do_rollback(path)

    def _do_rollback(self, path):
        if not self._confirm_execute("Rollback", f"Restore from {path or 'Latest'}?"):
            return

        resp = self.bridge.rollback(
            self.yaml_path_getter(),
            backup_path=path,
        )
        self._handle_response(resp, "Rollback")
        if resp.get("ok"):
            self.on_refresh_backups()

    # --- AUDIT TAB ---
    def _build_audit_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        filter_form = QFormLayout()

        self.audit_start_date = QDateEdit()
        self.audit_start_date.setCalendarPopup(True)
        self.audit_start_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_start_date.setDate(QDate.currentDate().addDays(-7))
        filter_form.addRow("From", self.audit_start_date)

        self.audit_end_date = QDateEdit()
        self.audit_end_date.setCalendarPopup(True)
        self.audit_end_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_end_date.setDate(QDate.currentDate())
        filter_form.addRow("To", self.audit_end_date)

        self.audit_action_filter = QComboBox()
        self.audit_action_filter.addItems(["All", "add_entry", "record_thaw", "batch_thaw", "rollback"])
        filter_form.addRow("Action", self.audit_action_filter)

        self.audit_status_filter = QComboBox()
        self.audit_status_filter.addItems(["All", "success", "failed"])
        filter_form.addRow("Status", self.audit_status_filter)

        layout.addLayout(filter_form)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load Audit Log")
        load_btn.clicked.connect(self.on_load_audit)
        btn_row.addWidget(load_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.audit_info = QLabel("Click 'Load Audit Log' to view events.")
        layout.addWidget(self.audit_info)

        self.audit_table = QTableWidget()
        layout.addWidget(self.audit_table, 1)
        self._setup_table(
            self.audit_table,
            ["Timestamp", "Action", "Actor", "Status", "Channel", "Details"],
            sortable=True,
        )
        self.audit_table.cellClicked.connect(self._on_audit_row_clicked)

        return tab

    def on_load_audit(self):
        """Load and display audit events from JSONL file."""
        yaml_path = self.yaml_path_getter()
        yaml_abs = os.path.abspath(yaml_path)
        from lib.config import AUDIT_LOG_FILE
        audit_path = os.path.join(os.path.dirname(yaml_abs), AUDIT_LOG_FILE)

        if not os.path.isfile(audit_path):
            self.audit_info.setText(f"Audit file not found: {audit_path}")
            return

        start = self.audit_start_date.date().toString("yyyy-MM-dd")
        end = self.audit_end_date.date().toString("yyyy-MM-dd")
        action_filter = self.audit_action_filter.currentText()
        status_filter = self.audit_status_filter.currentText()

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
            self.audit_info.setText(f"Failed to load audit: {exc}")
            return

        # Newest first
        events.reverse()
        self._audit_events = events

        self._setup_table(
            self.audit_table,
            ["Timestamp", "Action", "Actor", "Status", "Channel", "Details"],
            sortable=True,
        )
        for row, ev in enumerate(events):
            self.audit_table.insertRow(row)
            self.audit_table.setItem(row, 0, QTableWidgetItem(ev.get("timestamp", "")))
            self.audit_table.setItem(row, 1, QTableWidgetItem(ev.get("action", "")))
            self.audit_table.setItem(row, 2, QTableWidgetItem(ev.get("actor_id", "")))
            self.audit_table.setItem(row, 3, QTableWidgetItem(ev.get("status", "")))
            self.audit_table.setItem(row, 4, QTableWidgetItem(ev.get("channel", "")))

            details = ev.get("details") or {}
            error = ev.get("error") or {}
            if ev.get("status") == "failed":
                summary = str(error.get("message", ""))[:80] if error else str(details)[:80]
            else:
                summary = json.dumps(details, ensure_ascii=False)[:80] if details else ""
            self.audit_table.setItem(row, 5, QTableWidgetItem(summary))

        self.audit_info.setText(f"Showing {len(events)} audit events ({start} to {end})")

    def _on_audit_row_clicked(self, row, _col):
        """Show full JSON of selected audit event in output panel."""
        if row >= len(self._audit_events):
            return
        ev = self._audit_events[row]
        self.output.setPlainText(json.dumps(ev, ensure_ascii=False, indent=2))
        self.output.setVisible(True)
        self.output_toggle_btn.setChecked(True)

    # --- UNDO ---

    def _enable_undo(self, timeout_sec=30):
        """Enable the undo button with an auto-disable countdown."""
        self.undo_btn.setEnabled(True)
        self._undo_remaining = timeout_sec
        self.undo_btn.setText(f"Undo Last Operation ({self._undo_remaining}s)")

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
            self.undo_btn.setText(f"Undo Last Operation ({self._undo_remaining}s)")

    def _disable_undo(self):
        if self._undo_timer is not None:
            self._undo_timer.stop()
            self._undo_timer = None
        self.undo_btn.setEnabled(False)
        self.undo_btn.setText("Undo Last Operation")
        self._last_operation_backup = None

    def on_undo_last(self):
        if not self._last_operation_backup:
            self.status_message.emit("No operation to undo.", 3000, "error")
            return

        if not self._confirm_execute(
            "Undo",
            f"Restore from backup:\n{os.path.basename(self._last_operation_backup)}?",
        ):
            return

        response = self.bridge.rollback(
            self.yaml_path_getter(),
            backup_path=self._last_operation_backup,
        )
        self._disable_undo()
        self._handle_response(response, "Undo")
