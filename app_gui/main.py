"""Desktop GUI for LN2 inventory operations (M2 starter)."""

import csv
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_gui.tool_bridge import GuiToolBridge
from lib.config import YAML_PATH
from lib.validators import parse_positions
from lib.yaml_ops import load_yaml, write_html_snapshot


def _positions_to_text(positions):
    if not positions:
        return ""
    return ",".join(str(p) for p in positions)


def _cell_color(parent_cell_line):
    palette = {
        "NCCIT": "#4a90d9",
        "K562": "#e67e22",
        "HeLa": "#27ae60",
        "HEK293T": "#8e44ad",
        "NCCIT Des-MCP-APEX2": "#2c3e50",
    }
    return palette.get(parent_cell_line, "#7f8c8d")


def main():
    try:
        from PySide6.QtCore import QDate, QSettings, Qt
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDateEdit,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QGroupBox,
            QGridLayout,
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMenu,
            QMessageBox,
            QPushButton,
            QScrollArea,
            QSizePolicy,
            QSpinBox,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("PySide6 is not installed. Install it with: pip install PySide6")
        return 1

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("LN2 Inventory Agent")
            self.resize(1300, 900)

            self.settings = QSettings("EamonFox", "LN2InventoryAgent")
            self.bridge = GuiToolBridge(actor_id="gui-user")
            self.current_yaml_path = self.settings.value("ui/current_yaml_path", YAML_PATH, type=str) or YAML_PATH
            self.current_actor_id = self.settings.value("ui/current_actor_id", "gui-user", type=str) or "gui-user"
            self.bridge.set_actor(actor_id=self.current_actor_id)

            self.overview_shape = None
            self.overview_cells = {}
            self.overview_pos_map = {}
            self.overview_box_live_labels = {}
            self.overview_box_groups = {}
            self.overview_selected = None
            self.query_last_mode = "records"

            container = QWidget()
            root = QVBoxLayout(container)

            top = QHBoxLayout()
            self.dataset_label = QLabel()
            self._update_dataset_label()
            top.addWidget(self.dataset_label, 1)

            quick_start_btn = QPushButton("Quick Start")
            quick_start_btn.clicked.connect(self.on_quick_start)
            top.addWidget(quick_start_btn)

            settings_btn = QPushButton("Settings")
            settings_btn.clicked.connect(self.on_open_settings)
            top.addWidget(settings_btn)
            root.addLayout(top)

            self.tabs = QTabWidget()
            self.tab_overview = self.tabs.addTab(self._build_overview_tab(), "Overview")
            self.tab_query = self.tabs.addTab(self._build_query_tab(), "Query")
            self.tab_add = self.tabs.addTab(self._build_add_tab(), "Add Entry")
            self.tab_thaw = self.tabs.addTab(self._build_thaw_tab(), "Thaw / Batch")
            self.tab_rollback = self.tabs.addTab(self._build_rollback_tab(), "Rollback")
            root.addWidget(self.tabs, 3)

            output_header = QHBoxLayout()
            output_header.addWidget(QLabel("Response JSON"))
            clear_btn = QPushButton("Clear")
            clear_btn.clicked.connect(lambda: self.output.clear())
            output_header.addWidget(clear_btn)
            output_header.addStretch()
            root.addLayout(output_header)

            self.output = QTextEdit()
            self.output.setReadOnly(True)
            root.addWidget(self.output, 2)

            self.setCentralWidget(container)
            self.statusBar().showMessage("Ready", 2000)
            self._restore_ui_settings()
            self.on_quick_start(auto=True)

        def _read_saved_widths(self, key):
            raw = self.settings.value(key, "", type=str)
            if not raw:
                return None
            try:
                values = json.loads(raw)
                if isinstance(values, list):
                    return [int(v) for v in values]
            except Exception:
                return None
            return None

        def _apply_saved_table_widths(self, table, key):
            widths = self._read_saved_widths(key)
            if not widths or len(widths) != table.columnCount():
                return
            for idx, width in enumerate(widths):
                table.setColumnWidth(idx, width)

        def _save_table_widths(self, table, key):
            widths = [table.columnWidth(i) for i in range(table.columnCount())]
            self.settings.setValue(key, json.dumps(widths, ensure_ascii=False))

        def _restore_ui_settings(self):
            geometry = self.settings.value("ui/geometry")
            if geometry:
                self.restoreGeometry(geometry)

            tab_idx = self.settings.value("ui/current_tab", 0, type=int)
            if 0 <= tab_idx < self.tabs.count():
                self.tabs.setCurrentIndex(tab_idx)

        def _save_ui_settings(self):
            self.settings.setValue("ui/current_yaml_path", self.current_yaml_path)
            self.settings.setValue("ui/current_actor_id", self.current_actor_id)
            self.settings.setValue("ui/current_tab", self.tabs.currentIndex())
            self.settings.setValue("ui/geometry", self.saveGeometry())
            self._save_table_widths(self.query_table, "tables/query_widths")
            self._save_table_widths(self.backup_table, "tables/backup_widths")

        def closeEvent(self, event):
            self._save_ui_settings()
            super().closeEvent(event)

        def _setup_table(self, table, headers, width_key=None, sortable=True):
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
            if width_key:
                self._apply_saved_table_widths(table, width_key)

        def _clear_layout(self, layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    widget.deleteLater()
                elif child_layout is not None:
                    self._clear_layout(child_layout)

        def _wrap_layout_widget(self, layout):
            wrapper = QWidget()
            wrapper.setLayout(layout)
            return wrapper

        def _build_summary_card(self, title, initial="-"):
            card = QGroupBox(title)
            card_layout = QVBoxLayout(card)
            value_label = QLabel(initial)
            value_label.setStyleSheet("font-size: 20px; font-weight: 700;")
            card_layout.addWidget(value_label)
            return card, value_label

        def _build_overview_tab(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)

            summary_row = QHBoxLayout()
            summary_row.setSpacing(6)
            card, self.ov_total_records_value = self._build_summary_card("Total Records")
            summary_row.addWidget(card)
            card, self.ov_total_capacity_value = self._build_summary_card("Total Capacity")
            summary_row.addWidget(card)
            card, self.ov_occupied_value = self._build_summary_card("Occupied")
            summary_row.addWidget(card)
            card, self.ov_empty_value = self._build_summary_card("Empty")
            summary_row.addWidget(card)
            card, self.ov_rate_value = self._build_summary_card("Occupancy Rate")
            summary_row.addWidget(card)
            card, self.ov_ops7_value = self._build_summary_card("Ops (7d)")
            summary_row.addWidget(card)
            layout.addLayout(summary_row)

            action_row = QHBoxLayout()
            action_row.setSpacing(6)
            refresh_btn = QPushButton("Refresh Overview")
            refresh_btn.clicked.connect(self.on_refresh_overview)
            action_row.addWidget(refresh_btn)

            html_btn = QPushButton("Open HTML Preview")
            html_btn.clicked.connect(self.on_open_html_preview)
            action_row.addWidget(html_btn)

            goto_query_btn = QPushButton("Go Query")
            goto_query_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tab_query))
            action_row.addWidget(goto_query_btn)

            goto_add_btn = QPushButton("Go Add")
            goto_add_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tab_add))
            action_row.addWidget(goto_add_btn)

            goto_thaw_btn = QPushButton("Go Thaw")
            goto_thaw_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tab_thaw))
            action_row.addWidget(goto_thaw_btn)

            goto_rollback_btn = QPushButton("Go Rollback")
            goto_rollback_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tab_rollback))
            action_row.addWidget(goto_rollback_btn)
            action_row.addStretch()
            layout.addLayout(action_row)

            filter_row = QHBoxLayout()
            filter_row.setSpacing(6)
            filter_row.addWidget(QLabel("Filter"))

            self.ov_filter_keyword = QLineEdit()
            self.ov_filter_keyword.setPlaceholderText("keyword: ID / short / cell / plasmid / note")
            self.ov_filter_keyword.textChanged.connect(self._apply_overview_filters)
            filter_row.addWidget(self.ov_filter_keyword, 2)

            self.ov_filter_box = QComboBox()
            self.ov_filter_box.addItem("All boxes", None)
            self.ov_filter_box.currentIndexChanged.connect(self._apply_overview_filters)
            filter_row.addWidget(self.ov_filter_box)

            self.ov_filter_cell = QComboBox()
            self.ov_filter_cell.addItem("All cells", None)
            self.ov_filter_cell.currentIndexChanged.connect(self._apply_overview_filters)
            filter_row.addWidget(self.ov_filter_cell, 1)

            self.ov_filter_show_empty = QCheckBox("Show Empty")
            self.ov_filter_show_empty.setChecked(True)
            self.ov_filter_show_empty.stateChanged.connect(self._apply_overview_filters)
            filter_row.addWidget(self.ov_filter_show_empty)

            clear_filter_btn = QPushButton("Clear Filter")
            clear_filter_btn.clicked.connect(self.on_overview_clear_filters)
            filter_row.addWidget(clear_filter_btn)
            layout.addLayout(filter_row)

            self.ov_status = QLabel("Overview status")
            layout.addWidget(self.ov_status)

            body = QHBoxLayout()

            self.ov_scroll = QScrollArea()
            self.ov_scroll.setWidgetResizable(True)
            self.ov_boxes_widget = QWidget()
            self.ov_boxes_layout = QGridLayout(self.ov_boxes_widget)
            self.ov_boxes_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.ov_boxes_layout.setContentsMargins(0, 0, 0, 0)
            self.ov_boxes_layout.setHorizontalSpacing(4)
            self.ov_boxes_layout.setVerticalSpacing(6)
            self.ov_scroll.setWidget(self.ov_boxes_widget)
            body.addWidget(self.ov_scroll, 3)

            detail = QGroupBox("Cell Detail")
            detail_form = QFormLayout(detail)
            self.ov_detail_id = QLabel("-")
            self.ov_detail_location = QLabel("-")
            self.ov_detail_parent = QLabel("-")
            self.ov_detail_short = QLabel("-")
            self.ov_detail_frozen = QLabel("-")
            self.ov_detail_plasmid = QLabel("-")
            self.ov_detail_note = QLabel("-")
            detail_form.addRow("ID", self.ov_detail_id)
            detail_form.addRow("Location", self.ov_detail_location)
            detail_form.addRow("Cell", self.ov_detail_parent)
            detail_form.addRow("Short", self.ov_detail_short)
            detail_form.addRow("Frozen", self.ov_detail_frozen)
            detail_form.addRow("Plasmid", self.ov_detail_plasmid)
            detail_form.addRow("Note", self.ov_detail_note)

            detail_actions = QHBoxLayout()
            self.ov_copy_id_btn = QPushButton("Copy ID")
            self.ov_copy_id_btn.clicked.connect(self.on_overview_copy_id)
            self.ov_copy_id_btn.setEnabled(False)
            detail_actions.addWidget(self.ov_copy_id_btn)

            self.ov_prefill_btn = QPushButton("Prefill to Thaw")
            self.ov_prefill_btn.clicked.connect(self.on_overview_prefill_to_thaw)
            self.ov_prefill_btn.setEnabled(False)
            detail_actions.addWidget(self.ov_prefill_btn)
            detail_form.addRow("", self._wrap_layout_widget(detail_actions))

            body.addWidget(detail, 1)

            layout.addLayout(body, 1)
            return tab

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
                width_key="tables/query_widths",
                sortable=False,
            )
            return tab

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
            self.a_dry_run = QCheckBox("Dry Run")
            self.a_dry_run.setChecked(True)
            self.a_dry_run.stateChanged.connect(self._update_action_button_labels)

            form.addRow("Parent Cell Line", self.a_parent)
            form.addRow("Short Name", self.a_short)
            form.addRow("Box", self.a_box)
            form.addRow("Positions", self.a_positions)
            form.addRow("Frozen Date", self.a_date)
            form.addRow("Plasmid Name", self.a_plasmid)
            form.addRow("Plasmid ID", self.a_plasmid_id)
            form.addRow("Note", self.a_note)
            form.addRow("", self.a_dry_run)
            layout.addLayout(form)

            self.a_apply_btn = QPushButton("Preview Add Entry")
            self.a_apply_btn.clicked.connect(self.on_add_entry)
            layout.addWidget(self.a_apply_btn)
            layout.addStretch(1)
            return tab

        def _build_thaw_tab(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)

            single = QGroupBox("Single Thaw / Takeout")
            single_form = QFormLayout(single)
            self.t_id = QSpinBox()
            self.t_id.setRange(1, 999999)
            self.t_position = QSpinBox()
            self.t_position.setRange(1, 999)
            self.t_date = QDateEdit()
            self.t_date.setCalendarPopup(True)
            self.t_date.setDisplayFormat("yyyy-MM-dd")
            self.t_date.setDate(QDate.currentDate())
            self.t_action = QComboBox()
            self.t_action.addItems(["取出", "复苏", "扔掉"])
            self.t_note = QLineEdit()
            self.t_dry_run = QCheckBox("Dry Run")
            self.t_dry_run.setChecked(True)
            self.t_dry_run.stateChanged.connect(self._update_action_button_labels)

            single_form.addRow("Record ID", self.t_id)
            single_form.addRow("Position", self.t_position)
            single_form.addRow("Date", self.t_date)
            single_form.addRow("Action", self.t_action)
            single_form.addRow("Note", self.t_note)
            single_form.addRow("", self.t_dry_run)

            self.t_apply_btn = QPushButton("Preview Single Operation")
            self.t_apply_btn.clicked.connect(self.on_record_thaw)
            single_form.addRow("", self.t_apply_btn)
            layout.addWidget(single)

            batch = QGroupBox("Batch Thaw / Takeout")
            batch_form = QFormLayout(batch)
            self.b_entries = QLineEdit()
            self.b_entries.setPlaceholderText("e.g. 182:23,183:41")
            self.b_date = QDateEdit()
            self.b_date.setCalendarPopup(True)
            self.b_date.setDisplayFormat("yyyy-MM-dd")
            self.b_date.setDate(QDate.currentDate())
            self.b_action = QComboBox()
            self.b_action.addItems(["取出", "复苏", "扔掉"])
            self.b_note = QLineEdit()
            self.b_dry_run = QCheckBox("Dry Run")
            self.b_dry_run.setChecked(True)
            self.b_dry_run.stateChanged.connect(self._update_action_button_labels)

            batch_form.addRow("Entries", self.b_entries)
            batch_form.addRow("Date", self.b_date)
            batch_form.addRow("Action", self.b_action)
            batch_form.addRow("Note", self.b_note)
            batch_form.addRow("", self.b_dry_run)

            self.b_apply_btn = QPushButton("Preview Batch Operation")
            self.b_apply_btn.clicked.connect(self.on_batch_thaw)
            batch_form.addRow("", self.b_apply_btn)
            layout.addWidget(batch)
            layout.addStretch(1)
            self._update_action_button_labels()
            return tab

        def _build_rollback_tab(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)

            form = QFormLayout()
            self.rb_backup_path = QLineEdit()
            self.rb_backup_path.setPlaceholderText("Leave empty to rollback latest backup")
            self.rb_no_html = QCheckBox("No HTML Refresh")
            self.rb_no_html.setChecked(True)
            self.rb_no_server = QCheckBox("No Preview Server")
            self.rb_no_server.setChecked(True)

            form.addRow("Backup Path", self.rb_backup_path)
            form.addRow("", self.rb_no_html)
            form.addRow("", self.rb_no_server)
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
                width_key="tables/backup_widths",
                sortable=True,
            )
            return tab

        def _yaml_path(self):
            return self.current_yaml_path

        def _update_dataset_label(self):
            path = self.current_yaml_path
            self.dataset_label.setText(f"Dataset: {path} | Actor: {self.current_actor_id}")

        def _notify(self, message, level="info", timeout=4000):
            if level == "error":
                self.statusBar().showMessage(f"ERROR: {message}", timeout)
            elif level == "success":
                self.statusBar().showMessage(f"OK: {message}", timeout)
            else:
                self.statusBar().showMessage(message, timeout)

        def _collect_tool_error_lines(self, response):
            if not isinstance(response, dict):
                return []

            lines = []

            errors = response.get("errors")
            if isinstance(errors, list):
                lines.extend(str(item) for item in errors if item)

            conflicts = response.get("conflicts")
            if isinstance(conflicts, list):
                for item in conflicts:
                    if isinstance(item, dict):
                        rec_id = item.get("id")
                        short_name = item.get("short_name")
                        positions = item.get("positions")
                        lines.append(f"ID {rec_id} ({short_name}): 位置 {positions}")
                    elif item:
                        lines.append(str(item))

            return lines

        def _show_tool_error_dialog(self, title, message, lines):
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle(title)
            dialog.setText(message)

            if lines:
                preview = lines[:6]
                extra = len(lines) - len(preview)
                preview_text = "\n".join(f"- {line}" for line in preview)
                if extra > 0:
                    preview_text += f"\n- ... 另外 {extra} 条"
                dialog.setInformativeText(preview_text)
                dialog.setDetailedText("\n".join(lines))

            dialog.exec()

        def _handle_tool_failure(self, response, fallback_message, dialog_title="Operation Failed"):
            payload = response if isinstance(response, dict) else {}
            message = payload.get("message", fallback_message)
            error_code = payload.get("error_code")
            status_message = f"{message} [{error_code}]" if error_code else message
            self._notify(status_message, level="error")

            lines = self._collect_tool_error_lines(payload)
            if error_code in {
                "integrity_validation_failed",
                "rollback_backup_invalid",
                "validation_failed",
                "position_conflict",
            }:
                self._show_tool_error_dialog(dialog_title, status_message, lines)

        def _update_action_button_labels(self):
            self.a_apply_btn.setText("Preview Add Entry" if self.a_dry_run.isChecked() else "Execute Add Entry")
            self.t_apply_btn.setText(
                "Preview Single Operation" if self.t_dry_run.isChecked() else "Execute Single Operation"
            )
            self.b_apply_btn.setText(
                "Preview Batch Operation" if self.b_dry_run.isChecked() else "Execute Batch Operation"
            )

        def _reload_all_views(self, emit_payload=False):
            self._refresh_overview(update_output=emit_payload)
            self._refresh_backups_table(update_output=False)

        def on_quick_start(self, auto=False):
            if auto and Path(self.current_yaml_path).exists():
                self._reload_all_views(emit_payload=False)
                self._emit({"ok": True, "message": "GUI ready. Overview loaded."})
                return

            msg = QMessageBox(self)
            msg.setWindowTitle("Quick Start")
            msg.setText("Choose a data source to start:")
            btn_current = msg.addButton("Use Current", QMessageBox.AcceptRole)
            btn_demo = msg.addButton("Use Demo", QMessageBox.AcceptRole)
            btn_custom = msg.addButton("Select File...", QMessageBox.ActionRole)
            msg.addButton("Cancel", QMessageBox.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()

            if clicked is btn_current:
                chosen = self.current_yaml_path
            elif clicked is btn_demo:
                chosen = os.path.join(ROOT, "demo", "ln2_inventory.demo.yaml")
            elif clicked is btn_custom:
                chosen, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select YAML",
                    os.path.dirname(self.current_yaml_path) or ROOT,
                    "YAML Files (*.yaml *.yml)",
                )
                if not chosen:
                    return
            else:
                return

            if not os.path.exists(chosen):
                self._warn(f"YAML file does not exist: {chosen}")
                return

            self.current_yaml_path = os.path.abspath(chosen)
            self._update_dataset_label()
            self._reload_all_views(emit_payload=True)
            self._notify("Loaded dataset", level="success")

        def on_open_settings(self):
            dialog = QDialog(self)
            dialog.setWindowTitle("Settings")
            layout = QVBoxLayout(dialog)
            form = QFormLayout()

            yaml_edit = QLineEdit(self.current_yaml_path)
            browse_btn = QPushButton("Browse")

            row = QHBoxLayout()
            row.addWidget(yaml_edit, 1)
            row.addWidget(browse_btn)
            row_widget = QWidget()
            row_widget.setLayout(row)
            form.addRow("YAML Path", row_widget)

            actor_edit = QLineEdit(self.current_actor_id)
            form.addRow("Actor ID", actor_edit)

            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            layout.addWidget(buttons)

            def _browse():
                picked, _ = QFileDialog.getOpenFileName(
                    dialog,
                    "Select YAML",
                    os.path.dirname(yaml_edit.text()) or ROOT,
                    "YAML Files (*.yaml *.yml)",
                )
                if picked:
                    yaml_edit.setText(picked)

            browse_btn.clicked.connect(_browse)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)

            if dialog.exec() != QDialog.Accepted:
                return

            new_yaml = yaml_edit.text().strip()
            new_actor = actor_edit.text().strip() or "gui-user"
            if not new_yaml or not os.path.exists(new_yaml):
                self._warn(f"Invalid YAML path: {new_yaml}")
                return

            self.current_yaml_path = os.path.abspath(new_yaml)
            self.current_actor_id = new_actor
            self.bridge.set_actor(actor_id=new_actor)
            self._update_dataset_label()
            self._reload_all_views(emit_payload=True)
            self._notify("Settings applied", level="success")

        def _emit(self, response):
            self.output.setPlainText(json.dumps(response, ensure_ascii=False, indent=2))

        def _warn(self, message):
            QMessageBox.warning(self, "Input Error", message)

        def _selected_backup_path(self):
            row = self.backup_table.currentRow()
            if row < 0:
                return None
            item = self.backup_table.item(row, 3)
            return item.text() if item else None

        def _confirm_rollback(self, backup_path):
            path = backup_path
            if not path:
                backups = self.bridge.list_backups(self._yaml_path()).get("result", {}).get("backups", [])
                path = backups[0] if backups else None
            if not path:
                self._warn("No backup available for rollback.")
                return False

            try:
                stat = os.stat(path)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = stat.st_size
            except OSError:
                mtime = "unknown"
                size = "unknown"

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Confirm Rollback")
            msg.setText("Rollback will overwrite current inventory YAML.")
            msg.setInformativeText(f"Backup: {path}\nUpdated: {mtime}\nSize: {size} bytes")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            return msg.exec() == QMessageBox.Yes

        def _reset_overview_detail(self):
            self.overview_selected = None
            self.ov_detail_id.setText("-")
            self.ov_detail_location.setText("-")
            self.ov_detail_parent.setText("-")
            self.ov_detail_short.setText("-")
            self.ov_detail_frozen.setText("-")
            self.ov_detail_plasmid.setText("-")
            self.ov_detail_note.setText("-")
            self.ov_copy_id_btn.setEnabled(False)
            self.ov_prefill_btn.setEnabled(False)

        def _show_overview_detail(self, box_num, position, record):
            self.overview_selected = (box_num, position, record)
            self.ov_detail_location.setText(f"Box {box_num} Position {position}")
            if not record:
                self.ov_detail_id.setText("(empty)")
                self.ov_detail_parent.setText("-")
                self.ov_detail_short.setText("-")
                self.ov_detail_frozen.setText("-")
                self.ov_detail_plasmid.setText("-")
                self.ov_detail_note.setText("Available slot")
                self.ov_copy_id_btn.setEnabled(False)
                self.ov_prefill_btn.setEnabled(False)
                return

            self.ov_detail_id.setText(str(record.get("id", "-")))
            self.ov_detail_parent.setText(str(record.get("parent_cell_line", "-")))
            self.ov_detail_short.setText(str(record.get("short_name", "-")))
            self.ov_detail_frozen.setText(str(record.get("frozen_at", "-")))
            plasmid = record.get("plasmid_name") or record.get("plasmid_id") or "-"
            self.ov_detail_plasmid.setText(str(plasmid))
            self.ov_detail_note.setText(str(record.get("note") or "-"))
            self.ov_copy_id_btn.setEnabled(True)
            self.ov_prefill_btn.setEnabled(True)

        def _paint_overview_cell(self, button, box_num, position, record):
            if record:
                short = str(record.get("short_name") or "")
                label = short[:6] if short else str(position)
                parent = record.get("parent_cell_line")
                color = _cell_color(parent)
                button.setText(label)
                button.setToolTip(
                    "\n".join(
                        [
                            f"ID: {record.get('id', '-')}",
                            f"Cell: {record.get('parent_cell_line', '-')}",
                            f"Short: {record.get('short_name', '-')}",
                            f"Box/Pos: {box_num}/{position}",
                            f"Frozen: {record.get('frozen_at', '-')}",
                            f"Plasmid: {record.get('plasmid_name') or record.get('plasmid_id') or '-'}",
                            f"Note: {record.get('note') or '-'}",
                        ]
                    )
                )
                button.setStyleSheet(
                    "QPushButton {"
                    f"background-color: {color};"
                    "color: white;"
                    "border: 1px solid #1f2937;"
                    "border-radius: 4px;"
                    "font-size: 10px;"
                    "font-weight: 700;"
                    "padding: 1px;"
                    "}"
                    "QPushButton:hover { border: 2px solid #f8fafc; }"
                )
                searchable = " ".join(
                    [
                        str(record.get("id", "")),
                        str(record.get("parent_cell_line", "")),
                        str(record.get("short_name", "")),
                        str(record.get("plasmid_name") or ""),
                        str(record.get("plasmid_id") or ""),
                        str(record.get("note") or ""),
                        str(record.get("frozen_at") or ""),
                        str(box_num),
                        str(position),
                    ]
                ).lower()
                button.setProperty("search_text", searchable)
                button.setProperty("cell_line", str(record.get("parent_cell_line") or ""))
                button.setProperty("is_empty", False)
            else:
                button.setText(str(position))
                button.setToolTip(f"Box {box_num} Position {position}: empty")
                button.setStyleSheet(
                    "QPushButton {"
                    "background-color: #0f3460;"
                    "color: #b7c9e9;"
                    "border: 1px solid #1e4b78;"
                    "border-radius: 4px;"
                    "font-size: 9px;"
                    "padding: 1px;"
                    "}"
                    "QPushButton:hover { border: 2px solid #7dd3fc; }"
                )
                button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
                button.setProperty("cell_line", "")
                button.setProperty("is_empty", True)

        def _rebuild_overview_boxes(self, rows, cols, box_numbers):
            self._clear_layout(self.ov_boxes_layout)
            self.overview_cells = {}
            self.overview_box_live_labels = {}
            self.overview_box_groups = {}
            self._reset_overview_detail()

            total_slots = rows * cols
            columns = 3
            for idx, box_num in enumerate(box_numbers):
                group = QGroupBox(f"Box {box_num}")
                group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                group_layout = QVBoxLayout(group)
                group_layout.setContentsMargins(6, 6, 6, 6)
                group_layout.setSpacing(4)

                live_label = QLabel(f"Occupied 0 / {total_slots} | Empty {total_slots}")
                group_layout.addWidget(live_label)
                self.overview_box_live_labels[box_num] = live_label

                grid = QGridLayout()
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setHorizontalSpacing(1)
                grid.setVerticalSpacing(1)
                for position in range(1, total_slots + 1):
                    r = (position - 1) // cols
                    c = (position - 1) % cols
                    button = QPushButton(str(position))
                    button.setFixedSize(32, 32)
                    button.clicked.connect(
                        lambda _checked=False, b=box_num, p=position: self.on_overview_cell_clicked(b, p)
                    )
                    button.setContextMenuPolicy(Qt.CustomContextMenu)
                    button.customContextMenuRequested.connect(
                        lambda point, b=box_num, p=position, btn=button: self.on_overview_cell_context_menu(
                            b, p, btn.mapToGlobal(point)
                        )
                    )
                    self.overview_cells[(box_num, position)] = button
                    grid.addWidget(button, r, c)

                group_layout.addLayout(grid)
                self.ov_boxes_layout.addWidget(group, idx // columns, idx % columns)
                self.overview_box_groups[box_num] = group

            self.overview_shape = (rows, cols, tuple(box_numbers))

        def _refresh_overview(self, update_output=False):
            yaml_path = self._yaml_path()
            stats_response = self.bridge.generate_stats(yaml_path)
            timeline_response = self.bridge.collect_timeline(yaml_path, days=7, all_history=False)

            if update_output:
                self._emit(
                    {
                        "ok": bool(stats_response.get("ok")),
                        "stats": stats_response,
                        "timeline": timeline_response,
                    }
                )

            if not stats_response.get("ok"):
                self.ov_status.setText(f"Failed to load overview: {stats_response.get('message', 'unknown error')}")
                self._reset_overview_detail()
                return

            payload = stats_response.get("result", {})
            data = payload.get("data", {})
            records = data.get("inventory", [])
            layout = payload.get("layout", {})
            stats = payload.get("stats", {})
            overall = stats.get("overall", {})
            box_stats = stats.get("boxes", {})

            rows = int(layout.get("rows", 9))
            cols = int(layout.get("cols", 9))
            box_numbers = sorted([int(k) for k in box_stats.keys()], key=int)
            if not box_numbers:
                box_numbers = [1, 2, 3, 4, 5]

            shape = (rows, cols, tuple(box_numbers))
            if self.overview_shape != shape:
                self._rebuild_overview_boxes(rows, cols, box_numbers)

            pos_map = {}
            for rec in records:
                box = rec.get("box")
                if box is None:
                    continue
                for pos in rec.get("positions") or []:
                    pos_map[(int(box), int(pos))] = rec

            self.overview_pos_map = pos_map

            self.ov_total_records_value.setText(str(len(records)))
            self.ov_total_capacity_value.setText(str(overall.get("total_capacity", "-")))
            self.ov_occupied_value.setText(str(overall.get("total_occupied", "-")))
            self.ov_empty_value.setText(str(overall.get("total_empty", "-")))
            self.ov_rate_value.setText(f"{overall.get('occupancy_rate', 0):.1f}%")

            if timeline_response.get("ok"):
                ops7 = timeline_response.get("result", {}).get("summary", {}).get("total_ops", 0)
                self.ov_ops7_value.setText(str(ops7))
            else:
                self.ov_ops7_value.setText("N/A")

            for box_num in box_numbers:
                stats_item = box_stats.get(str(box_num), {})
                occupied = stats_item.get("occupied", 0)
                empty = stats_item.get("empty", rows * cols)
                total = stats_item.get("total", rows * cols)
                live = self.overview_box_live_labels.get(box_num)
                if live is not None:
                    live.setText(f"Occupied {occupied}/{total} | Empty {empty}")

            for key, button in self.overview_cells.items():
                box_num, position = key
                rec = pos_map.get(key)
                self._paint_overview_cell(button, box_num, position, rec)

            self._refresh_overview_filter_options(records, box_numbers)
            self._apply_overview_filters()

            self.ov_status.setText(
                f"Loaded {len(records)} records from {yaml_path} | refreshed at {datetime.now().strftime('%H:%M:%S')}"
            )

        def _refresh_overview_filter_options(self, records, box_numbers):
            prev_box = self.ov_filter_box.currentData()
            prev_cell = self.ov_filter_cell.currentData()

            self.ov_filter_box.blockSignals(True)
            self.ov_filter_box.clear()
            self.ov_filter_box.addItem("All boxes", None)
            for box_num in box_numbers:
                self.ov_filter_box.addItem(f"Box {box_num}", box_num)
            index = self.ov_filter_box.findData(prev_box)
            self.ov_filter_box.setCurrentIndex(index if index >= 0 else 0)
            self.ov_filter_box.blockSignals(False)

            cell_lines = sorted({str(rec.get("parent_cell_line")) for rec in records if rec.get("parent_cell_line")})
            self.ov_filter_cell.blockSignals(True)
            self.ov_filter_cell.clear()
            self.ov_filter_cell.addItem("All cells", None)
            for cell in cell_lines:
                self.ov_filter_cell.addItem(cell, cell)
            index = self.ov_filter_cell.findData(prev_cell)
            self.ov_filter_cell.setCurrentIndex(index if index >= 0 else 0)
            self.ov_filter_cell.blockSignals(False)

        def _apply_overview_filters(self):
            keyword = self.ov_filter_keyword.text().strip().lower()
            selected_box = self.ov_filter_box.currentData()
            selected_cell = self.ov_filter_cell.currentData()
            show_empty = self.ov_filter_show_empty.isChecked()

            visible_boxes = 0
            visible_slots = 0
            per_box = {box: {"occ": 0, "emp": 0} for box in self.overview_box_groups.keys()}

            for (box_num, position), button in self.overview_cells.items():
                record = self.overview_pos_map.get((box_num, position))
                is_empty = record is None
                match_box = selected_box is None or box_num == selected_box
                match_cell = selected_cell is None or (record and str(record.get("parent_cell_line")) == selected_cell)
                match_empty = show_empty or not is_empty

                if keyword:
                    search_text = str(button.property("search_text") or "")
                    match_keyword = keyword in search_text
                else:
                    match_keyword = True

                visible = bool(match_box and match_cell and match_empty and match_keyword)
                button.setVisible(visible)

                if visible:
                    visible_slots += 1
                    if is_empty:
                        per_box.setdefault(box_num, {"occ": 0, "emp": 0})["emp"] += 1
                    else:
                        per_box.setdefault(box_num, {"occ": 0, "emp": 0})["occ"] += 1

            for box_num, group in self.overview_box_groups.items():
                stat = per_box.get(box_num, {"occ": 0, "emp": 0})
                total_visible = stat["occ"] + stat["emp"]
                group.setVisible(total_visible > 0)
                if total_visible > 0:
                    visible_boxes += 1

                live = self.overview_box_live_labels.get(box_num)
                if live:
                    live.setText(f"Filtered: Occupied {stat['occ']} | Empty {stat['emp']}")

            if self.overview_selected:
                box_num, position, _record = self.overview_selected
                selected_button = self.overview_cells.get((box_num, position))
                if selected_button and not selected_button.isVisible():
                    self._reset_overview_detail()

            self.ov_status.setText(
                f"Filter matched {visible_slots} slots across {visible_boxes} boxes | {datetime.now().strftime('%H:%M:%S')}"
            )

        def _render_query_records(self, records):
            sorting_enabled = self.query_table.isSortingEnabled()
            self.query_table.setSortingEnabled(False)
            self._setup_table(
                self.query_table,
                ["ID", "Cell", "Short", "Box", "Positions", "Frozen At", "Plasmid ID", "Note"],
                width_key="tables/query_widths",
                sortable=True,
            )
            for row, rec in enumerate(records):
                self.query_table.insertRow(row)
                self.query_table.setItem(row, 0, QTableWidgetItem(str(rec.get("id", ""))))
                self.query_table.setItem(row, 1, QTableWidgetItem(str(rec.get("parent_cell_line", ""))))
                self.query_table.setItem(row, 2, QTableWidgetItem(str(rec.get("short_name", ""))))
                self.query_table.setItem(row, 3, QTableWidgetItem(str(rec.get("box", ""))))
                self.query_table.setItem(row, 4, QTableWidgetItem(_positions_to_text(rec.get("positions"))))
                self.query_table.setItem(row, 5, QTableWidgetItem(str(rec.get("frozen_at", ""))))
                self.query_table.setItem(row, 6, QTableWidgetItem(str(rec.get("plasmid_id", ""))))
                self.query_table.setItem(row, 7, QTableWidgetItem(str(rec.get("note", ""))))
            self.query_info.setText(f"Query returned {len(records)} record(s).")
            self.query_table.setSortingEnabled(sorting_enabled)

        def _render_empty_positions(self, boxes):
            sorting_enabled = self.query_table.isSortingEnabled()
            self.query_table.setSortingEnabled(False)
            self._setup_table(
                self.query_table,
                ["Box", "Empty/Total", "Empty Positions"],
                width_key="tables/query_widths",
                sortable=False,
            )
            for row, item in enumerate(boxes):
                self.query_table.insertRow(row)
                empty_positions = item.get("empty_positions", [])
                preview = ",".join(str(p) for p in empty_positions[:30])
                if len(empty_positions) > 30:
                    preview += " ..."
                self.query_table.setItem(row, 0, QTableWidgetItem(str(item.get("box", ""))))
                self.query_table.setItem(
                    row,
                    1,
                    QTableWidgetItem(f"{item.get('empty_count', 0)}/{item.get('total_slots', 0)}"),
                )
                self.query_table.setItem(row, 2, QTableWidgetItem(preview))
            self.query_info.setText(f"Empty-position query returned {len(boxes)} box row(s).")
            self.query_table.setSortingEnabled(sorting_enabled)

        def _render_backups(self, backups):
            sorting_enabled = self.backup_table.isSortingEnabled()
            self.backup_table.setSortingEnabled(False)
            self._setup_table(
                self.backup_table,
                ["#", "Updated", "Size (B)", "Path"],
                width_key="tables/backup_widths",
                sortable=False,
            )
            for row, path in enumerate(backups):
                self.backup_table.insertRow(row)
                try:
                    stat = os.stat(path)
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size = str(stat.st_size)
                except OSError:
                    mtime = "-"
                    size = "-"
                self.backup_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
                self.backup_table.setItem(row, 1, QTableWidgetItem(mtime))
                self.backup_table.setItem(row, 2, QTableWidgetItem(size))
                self.backup_table.setItem(row, 3, QTableWidgetItem(path))
            self.backup_info.setText(f"Found {len(backups)} backup file(s).")
            self.backup_table.setSortingEnabled(sorting_enabled)

        def on_apply_actor(self):
            self.bridge.set_actor(actor_id=self.current_actor_id)
            self._emit({"ok": True, "message": f"actor updated: {self.current_actor_id}"})

        def on_overview_clear_filters(self):
            self.ov_filter_keyword.clear()
            self.ov_filter_box.setCurrentIndex(0)
            self.ov_filter_cell.setCurrentIndex(0)
            self.ov_filter_show_empty.setChecked(True)
            self._apply_overview_filters()

        def on_overview_cell_clicked(self, box_num, position):
            record = self.overview_pos_map.get((box_num, position))
            self._show_overview_detail(box_num, position, record)

        def on_overview_cell_context_menu(self, box_num, position, global_pos):
            record = self.overview_pos_map.get((box_num, position))
            self._show_overview_detail(box_num, position, record)

            menu = QMenu(self)
            act_copy_loc = menu.addAction(f"Copy Location {box_num}:{position}")
            act_copy_id = None
            act_prefill = None
            if record:
                act_copy_id = menu.addAction(f"Copy ID {record.get('id')}")
                act_prefill = menu.addAction("Prefill to Thaw")

            selected = menu.exec(global_pos)
            if selected is None:
                return
            if selected == act_copy_loc:
                QApplication.clipboard().setText(f"{box_num}:{position}")
                self._notify(f"Copied location {box_num}:{position}", level="success")
                return
            if act_copy_id is not None and selected == act_copy_id:
                self.on_overview_copy_id()
                return
            if act_prefill is not None and selected == act_prefill:
                self.on_overview_prefill_to_thaw()
                return

        def on_overview_copy_id(self):
            if not self.overview_selected:
                return
            _box_num, _position, record = self.overview_selected
            if not record:
                return
            rec_id = str(record.get("id", "")).strip()
            if not rec_id:
                return
            QApplication.clipboard().setText(rec_id)
            self._notify(f"Copied ID {rec_id}", level="success")

        def on_overview_prefill_to_thaw(self):
            if not self.overview_selected:
                return
            box_num, position, record = self.overview_selected
            if not record:
                self._notify("Selected slot is empty", level="error")
                return

            rec_id = int(record.get("id"))
            self.t_id.setValue(rec_id)
            self.t_position.setValue(position)
            self.t_action.setCurrentText("取出")
            self.tabs.setCurrentIndex(self.tab_thaw)
            self._notify(f"Prefilled thaw form: ID {rec_id}, position {position} (box {box_num})", level="success")

        def on_refresh_overview(self):
            self._refresh_overview(update_output=True)

        def on_open_html_preview(self):
            try:
                yaml_path = self._yaml_path()
                data = load_yaml(yaml_path)
                html_path = write_html_snapshot(data, yaml_path=yaml_path)
                webbrowser.open(f"file://{os.path.abspath(html_path)}")
                self._emit({"ok": True, "html_path": os.path.abspath(html_path)})
            except Exception as exc:
                self._emit({"ok": False, "message": f"Failed to open HTML preview: {exc}"})

        def on_export_query_csv(self):
            if self.query_table.rowCount() == 0 or self.query_table.columnCount() == 0:
                self._warn("No query result to export.")
                return

            default_name = f"ln2_query_{self.query_last_mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            default_dir = os.path.dirname(self._yaml_path()) or ROOT
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Query CSV",
                os.path.join(default_dir, default_name),
                "CSV Files (*.csv)",
            )
            if not target_path:
                return

            headers = []
            for col in range(self.query_table.columnCount()):
                header = self.query_table.horizontalHeaderItem(col)
                headers.append(header.text() if header else f"col_{col}")

            try:
                with open(target_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for row in range(self.query_table.rowCount()):
                        row_values = []
                        for col in range(self.query_table.columnCount()):
                            item = self.query_table.item(row, col)
                            row_values.append(item.text() if item else "")
                        writer.writerow(row_values)
            except Exception as exc:
                self._warn(f"Failed to export CSV: {exc}")
                return

            self._notify(f"Exported CSV: {target_path}", level="success")
            self._emit({"ok": True, "csv_path": target_path, "rows": self.query_table.rowCount()})

        def on_query_records(self):
            box_value = self.q_box.value() or None
            position_value = self.q_position.value() or None
            response = self.bridge.query_inventory(
                yaml_path=self._yaml_path(),
                cell=self.q_cell.text().strip() or None,
                short=self.q_short.text().strip() or None,
                plasmid=self.q_plasmid.text().strip() or None,
                plasmid_id=self.q_plasmid_id.text().strip() or None,
                box=box_value,
                position=position_value,
            )
            self._emit(response)
            if response.get("ok"):
                records = response.get("result", {}).get("records", [])
                self._render_query_records(records)
                self.query_last_mode = "records"
                self._notify(f"Query returned {len(records)} records", level="success")
            else:
                self._notify(response.get("message", "Query failed"), level="error")

        def on_list_empty(self):
            response = self.bridge.list_empty_positions(
                yaml_path=self._yaml_path(),
                box=self.q_box.value() or None,
            )
            self._emit(response)
            if response.get("ok"):
                boxes = response.get("result", {}).get("boxes", [])
                self._render_empty_positions(boxes)
                self.query_last_mode = "empty"
                self._notify(f"Loaded empty positions for {len(boxes)} boxes", level="success")
            else:
                self._notify(response.get("message", "Empty position query failed"), level="error")

        def on_add_entry(self):
            try:
                positions = parse_positions(self.a_positions.text().strip())
            except ValueError as exc:
                self._warn(str(exc))
                return

            box_value = self.a_box.value()

            response = self.bridge.add_entry(
                yaml_path=self._yaml_path(),
                parent_cell_line=self.a_parent.text().strip(),
                short_name=self.a_short.text().strip(),
                box=box_value,
                positions=positions,
                frozen_at=self.a_date.date().toString("yyyy-MM-dd"),
                plasmid_name=self.a_plasmid.text().strip() or None,
                plasmid_id=self.a_plasmid_id.text().strip() or None,
                note=self.a_note.text().strip() or None,
                dry_run=self.a_dry_run.isChecked(),
            )
            payload = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}
            self._emit(payload)
            self._refresh_overview(update_output=False)
            self._refresh_backups_table(update_output=False)
            if payload.get("ok"):
                self._notify("Add entry succeeded", level="success")
            else:
                self._handle_tool_failure(payload, "Add entry failed", dialog_title="Add Entry Failed")

        def on_record_thaw(self):
            record_id = self.t_id.value()
            position = self.t_position.value()

            response = self.bridge.record_thaw(
                yaml_path=self._yaml_path(),
                record_id=record_id,
                position=position,
                date_str=self.t_date.date().toString("yyyy-MM-dd"),
                action=self.t_action.currentText(),
                note=self.t_note.text().strip() or None,
                dry_run=self.t_dry_run.isChecked(),
            )
            payload = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}
            self._emit(payload)
            self._refresh_overview(update_output=False)
            self._refresh_backups_table(update_output=False)
            if payload.get("ok"):
                self._notify("Single operation succeeded", level="success")
            else:
                self._handle_tool_failure(payload, "Single operation failed", dialog_title="Single Operation Failed")

        def on_batch_thaw(self):
            try:
                response = self.bridge.batch_thaw_from_text(
                    yaml_path=self._yaml_path(),
                    entries_text=self.b_entries.text().strip(),
                    date_str=self.b_date.date().toString("yyyy-MM-dd"),
                    action=self.b_action.currentText(),
                    note=self.b_note.text().strip() or None,
                    dry_run=self.b_dry_run.isChecked(),
                )
            except ValueError as exc:
                self._warn(str(exc))
                return
            payload = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}
            self._emit(payload)
            self._refresh_overview(update_output=False)
            self._refresh_backups_table(update_output=False)
            if payload.get("ok"):
                self._notify("Batch operation succeeded", level="success")
            else:
                self._handle_tool_failure(payload, "Batch operation failed", dialog_title="Batch Operation Failed")

        def on_refresh_backups(self):
            self._refresh_backups_table(update_output=True)

        def _refresh_backups_table(self, update_output=False):
            response = self.bridge.list_backups(self._yaml_path())
            if update_output:
                self._emit(response)
            if response.get("ok"):
                backups = response.get("result", {}).get("backups", [])
                self._render_backups(backups)
            return response

        def on_use_selected_backup(self):
            selected = self._selected_backup_path()
            if not selected:
                self._warn("Select a backup row first.")
                return
            self.rb_backup_path.setText(selected)

        def on_rollback_latest(self):
            if not self._confirm_rollback(None):
                self._notify("Rollback cancelled")
                return
            response = self.bridge.rollback(
                yaml_path=self._yaml_path(),
                backup_path=None,
                no_html=self.rb_no_html.isChecked(),
                no_server=self.rb_no_server.isChecked(),
            )
            payload = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}
            self._emit(payload)
            self._refresh_backups_table(update_output=False)
            self._refresh_overview(update_output=False)
            if payload.get("ok"):
                self._notify("Rollback latest succeeded", level="success")
            else:
                self._handle_tool_failure(payload, "Rollback failed", dialog_title="Rollback Failed")

        def on_rollback_selected(self):
            path = self.rb_backup_path.text().strip() or self._selected_backup_path()
            if not path:
                self._warn("Provide backup path or select one from table.")
                return
            if not self._confirm_rollback(path):
                self._notify("Rollback cancelled")
                return
            response = self.bridge.rollback(
                yaml_path=self._yaml_path(),
                backup_path=path,
                no_html=self.rb_no_html.isChecked(),
                no_server=self.rb_no_server.isChecked(),
            )
            payload = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}
            self._emit(payload)
            self._refresh_backups_table(update_output=False)
            self._refresh_overview(update_output=False)
            if payload.get("ok"):
                self._notify("Rollback selected backup succeeded", level="success")
            else:
                self._handle_tool_failure(payload, "Rollback failed", dialog_title="Rollback Failed")

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
