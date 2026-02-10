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
from lib.config import AUDIT_LOG_FILE, YAML_PATH
from lib.tool_api import parse_batch_entries
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
        from PySide6.QtCore import QDate, QEvent, QObject, QSettings, QThread, Qt, Signal
        from PySide6.QtGui import QFont, QFontDatabase
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
            QSplitter,
            QSpinBox,
            QStackedWidget,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("PySide6 is not installed. Install it with: pip install PySide6")
        return 1

    def _pick_cjk_font():
        # Prefer widely available CJK-capable fonts to avoid tofu squares.
        candidates = [
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "WenQuanYi Zen Hei",
            "Microsoft YaHei",
            "PingFang SC",
            "SimHei",
            "Droid Sans Fallback",
            "Droid Sans",
        ]
        available = set(QFontDatabase().families())
        for family in candidates:
            if family in available:
                return QFont(family, 10)
        return None

    class _AgentRunWorker(QObject):
        finished = Signal(dict)
        progress = Signal(dict)

        def __init__(self, bridge, yaml_path, query, model, max_steps, mock, history):
            super().__init__()
            self._bridge = bridge
            self._yaml_path = yaml_path
            self._query = query
            self._model = model
            self._max_steps = max_steps
            self._mock = mock
            self._history = history

        def run(self):
            try:
                payload = self._bridge.run_agent_query(
                    yaml_path=self._yaml_path,
                    query=self._query,
                    model=self._model,
                    max_steps=self._max_steps,
                    mock=self._mock,
                    history=self._history,
                    on_event=self._emit_progress,
                )
                if not isinstance(payload, dict):
                    payload = {"ok": False, "message": "Unexpected response"}
            except Exception as exc:
                payload = {
                    "ok": False,
                    "error_code": "agent_runtime_failed",
                    "message": str(exc),
                    "result": None,
                }
            self.finished.emit(payload)

        def _emit_progress(self, event):
            if not isinstance(event, dict):
                return
            self.progress.emit(event)

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
            self.overview_hover_key = None
            self.overview_records_by_id = {}
            self.t_prefill_source = None
            self.query_last_mode = "records"
            self.ai_history = []
            self.ai_run_inflight = False
            self.ai_run_thread = None
            self.ai_run_worker = None

            container = QWidget()
            root = QVBoxLayout(container)
            root.setContentsMargins(8, 8, 8, 8)
            root.setSpacing(8)

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

            preview_btn = QPushButton("Preview HTML")
            preview_btn.clicked.connect(self.on_open_html_preview)
            top.addWidget(preview_btn)
            root.addLayout(top)

            splitter = QSplitter(Qt.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.addWidget(self._build_overview_tab())
            splitter.addWidget(self._build_operations_panel())
            splitter.addWidget(self._build_ai_tab())
            splitter.setStretchFactor(0, 6)
            splitter.setStretchFactor(1, 4)
            splitter.setStretchFactor(2, 4)
            root.addWidget(splitter, 1)

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

            op_mode = self.settings.value("ui/current_operation_mode", "thaw", type=str)
            self._set_operation_mode(op_mode or "thaw")

            self.ai_model.setText(self.settings.value("ai/model", "", type=str) or "")
            self.ai_mock.setChecked(self.settings.value("ai/mock", True, type=bool))
            self.ai_steps.setValue(self.settings.value("ai/max_steps", 8, type=int))
            self.on_ai_mode_changed()

        def _save_ui_settings(self):
            self.settings.setValue("ui/current_yaml_path", self.current_yaml_path)
            self.settings.setValue("ui/current_actor_id", self.current_actor_id)
            self.settings.setValue("ui/current_operation_mode", getattr(self, "current_operation_mode", "thaw"))
            self.settings.setValue("ui/geometry", self.saveGeometry())
            self.settings.setValue("ai/model", self.ai_model.text().strip())
            self.settings.setValue("ai/mock", self.ai_mock.isChecked())
            self.settings.setValue("ai/max_steps", self.ai_steps.value())
            self._save_table_widths(self.query_table, "tables/query_widths")
            self._save_table_widths(self.backup_table, "tables/backup_widths")

        def closeEvent(self, event):
            if self.ai_run_inflight:
                self._warn("AI run is still in progress. Please wait for it to finish.")
                event.ignore()
                return
            self._save_ui_settings()
            super().closeEvent(event)

        def eventFilter(self, obj, event):
            if (
                event.type() == QEvent.KeyPress
                and obj is getattr(self, "ai_prompt", None)
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            ):
                mods = event.modifiers()
                if mods & Qt.ShiftModifier:
                    return False
                if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                    return False
                self.on_run_ai_agent()
                return True

            if event.type() in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
                box_num = obj.property("overview_box")
                position = obj.property("overview_position")
                if box_num is not None and position is not None:
                    self.on_overview_cell_hovered(int(box_num), int(position))
            return super().eventFilter(obj, event)

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
            card_layout.setContentsMargins(8, 6, 8, 6)
            value_label = QLabel(initial)
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet("font-size: 16px; font-weight: 700;")
            card_layout.addWidget(value_label)
            return card, value_label

        def _build_operations_panel(self):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            mode_row = QHBoxLayout()
            mode_row.addWidget(QLabel("Manual Action"))
            mode_row.addStretch()

            self.op_mode_combo = QComboBox()
            modes = [
                ("thaw", "Takeout / Batch"),
                ("add", "Add Entry"),
                ("query", "Query"),
                ("rollback", "Rollback"),
            ]
            for mode_key, mode_label in modes:
                self.op_mode_combo.addItem(mode_label, mode_key)
            self.op_mode_combo.currentIndexChanged.connect(self.on_operation_mode_changed)
            mode_row.addWidget(self.op_mode_combo)
            layout.addLayout(mode_row)

            self.op_stack = QStackedWidget()
            self.op_mode_indexes = {
                "add": self.op_stack.addWidget(self._build_add_tab()),
                "thaw": self.op_stack.addWidget(self._build_thaw_tab()),
                "query": self.op_stack.addWidget(self._build_query_tab()),
                "rollback": self.op_stack.addWidget(self._build_rollback_tab()),
            }
            layout.addWidget(self.op_stack, 3)

            output_header = QHBoxLayout()
            self.output_toggle_btn = QPushButton("Show Raw JSON")
            self.output_toggle_btn.setCheckable(True)
            self.output_toggle_btn.toggled.connect(self.on_toggle_output_panel)
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

            self._set_operation_mode("thaw")
            return panel

        def _set_operation_mode(self, mode):
            target = mode if mode in getattr(self, "op_mode_indexes", {}) else "thaw"
            if target not in self.op_mode_indexes:
                return

            self.op_stack.setCurrentIndex(self.op_mode_indexes[target])
            self.current_operation_mode = target

            if hasattr(self, "op_mode_combo"):
                idx = self.op_mode_combo.findData(target)
                if idx >= 0 and idx != self.op_mode_combo.currentIndex():
                    self.op_mode_combo.blockSignals(True)
                    self.op_mode_combo.setCurrentIndex(idx)
                    self.op_mode_combo.blockSignals(False)

        def on_operation_mode_changed(self, _index=None):
            self._set_operation_mode(self.op_mode_combo.currentData())

        def on_toggle_output_panel(self, checked):
            visible = bool(checked)
            self.output.setVisible(visible)
            self.output_toggle_btn.setText("Hide Raw JSON" if visible else "Show Raw JSON")

        def on_toggle_ai_controls(self, checked):
            visible = bool(checked)
            self.ai_controls_box.setVisible(visible)
            self.ai_toggle_controls_btn.setText("Hide Advanced" if visible else "Show Advanced")

        def on_toggle_ai_report(self, checked):
            visible = bool(checked)
            self.ai_report_box.setVisible(visible)
            self.ai_toggle_report_btn.setText("Hide Plan Details" if visible else "Show Plan Details")

        def _build_overview_tab(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            summary_row = QHBoxLayout()
            summary_row.setSpacing(6)
            card, self.ov_total_records_value = self._build_summary_card("Total Records")
            summary_row.addWidget(card)
            card, self.ov_occupied_value = self._build_summary_card("Occupied")
            summary_row.addWidget(card)
            card, self.ov_empty_value = self._build_summary_card("Empty")
            summary_row.addWidget(card)
            card, self.ov_rate_value = self._build_summary_card("Occupancy Rate")
            summary_row.addWidget(card)
            layout.addLayout(summary_row)

            # Keep secondary metrics available without dedicating extra cards.
            self.ov_total_capacity_value = QLabel("-")
            self.ov_ops7_value = QLabel("-")
            self.ov_meta_stats = QLabel("Capacity: - | Ops (7d): -")
            self.ov_meta_stats.setStyleSheet("color: #64748b;")
            layout.addWidget(self.ov_meta_stats)

            action_row = QHBoxLayout()
            action_row.setSpacing(6)
            refresh_btn = QPushButton("Refresh")
            refresh_btn.clicked.connect(self.on_refresh_overview)
            action_row.addWidget(refresh_btn)

            goto_add_btn = QPushButton("Quick Add")
            goto_add_btn.clicked.connect(lambda: self._set_operation_mode("add"))
            action_row.addWidget(goto_add_btn)

            goto_thaw_btn = QPushButton("Quick Takeout")
            goto_thaw_btn.clicked.connect(lambda: self._set_operation_mode("thaw"))
            action_row.addWidget(goto_thaw_btn)
            action_row.addStretch()
            layout.addLayout(action_row)

            filter_row = QHBoxLayout()
            filter_row.setSpacing(6)
            filter_row.addWidget(QLabel("Search"))

            self.ov_filter_keyword = QLineEdit()
            self.ov_filter_keyword.setPlaceholderText("ID / short / cell / plasmid / note")
            self.ov_filter_keyword.textChanged.connect(self._apply_overview_filters)
            filter_row.addWidget(self.ov_filter_keyword, 2)

            self.ov_filter_toggle_btn = QPushButton("More Filters")
            self.ov_filter_toggle_btn.setCheckable(True)
            self.ov_filter_toggle_btn.toggled.connect(self.on_overview_toggle_filters)
            filter_row.addWidget(self.ov_filter_toggle_btn)
            layout.addLayout(filter_row)

            advanced_filter_row = QHBoxLayout()
            advanced_filter_row.setSpacing(6)

            self.ov_filter_box = QComboBox()
            self.ov_filter_box.addItem("All boxes", None)
            self.ov_filter_box.currentIndexChanged.connect(self._apply_overview_filters)
            advanced_filter_row.addWidget(self.ov_filter_box)

            self.ov_filter_cell = QComboBox()
            self.ov_filter_cell.addItem("All cells", None)
            self.ov_filter_cell.currentIndexChanged.connect(self._apply_overview_filters)
            advanced_filter_row.addWidget(self.ov_filter_cell, 1)

            self.ov_filter_show_empty = QCheckBox("Show Empty")
            self.ov_filter_show_empty.setChecked(True)
            self.ov_filter_show_empty.stateChanged.connect(self._apply_overview_filters)
            advanced_filter_row.addWidget(self.ov_filter_show_empty)

            clear_filter_btn = QPushButton("Clear Filter")
            clear_filter_btn.clicked.connect(self.on_overview_clear_filters)
            advanced_filter_row.addWidget(clear_filter_btn)
            advanced_filter_row.addStretch()

            self.ov_filter_advanced_widget = self._wrap_layout_widget(advanced_filter_row)
            self.ov_filter_advanced_widget.setVisible(False)
            layout.addWidget(self.ov_filter_advanced_widget)

            self.ov_status = QLabel("Overview status")
            layout.addWidget(self.ov_status)

            self.ov_hover_hint = QLabel("Hover a slot to preview details.")
            self.ov_hover_hint.setStyleSheet("color: #64748b;")
            layout.addWidget(self.ov_hover_hint)

            self.ov_scroll = QScrollArea()
            self.ov_scroll.setWidgetResizable(True)
            self.ov_boxes_widget = QWidget()
            self.ov_boxes_layout = QGridLayout(self.ov_boxes_widget)
            self.ov_boxes_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.ov_boxes_layout.setContentsMargins(0, 0, 0, 0)
            self.ov_boxes_layout.setHorizontalSpacing(4)
            self.ov_boxes_layout.setVerticalSpacing(6)
            self.ov_scroll.setWidget(self.ov_boxes_widget)
            layout.addWidget(self.ov_scroll, 1)
            return tab

        def _build_ai_tab(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            toggle_row = QHBoxLayout()
            self.ai_toggle_controls_btn = QPushButton("Show Advanced")
            self.ai_toggle_controls_btn.setCheckable(True)
            self.ai_toggle_controls_btn.toggled.connect(self.on_toggle_ai_controls)
            toggle_row.addWidget(self.ai_toggle_controls_btn)

            self.ai_toggle_report_btn = QPushButton("Show Plan Details")
            self.ai_toggle_report_btn.setCheckable(True)
            self.ai_toggle_report_btn.toggled.connect(self.on_toggle_ai_report)
            toggle_row.addWidget(self.ai_toggle_report_btn)
            toggle_row.addStretch()
            layout.addLayout(toggle_row)

            self.ai_controls_box = QGroupBox("Agent Controls")
            controls_form = QFormLayout(self.ai_controls_box)
            self.ai_model = QLineEdit()
            self.ai_model.setPlaceholderText("e.g. anthropic/claude-3-5-sonnet")

            self.ai_steps = QSpinBox()
            self.ai_steps.setRange(1, 20)
            self.ai_steps.setValue(8)

            self.ai_mock = QCheckBox("Mock LLM (no external API)")
            self.ai_mock.setChecked(True)
            self.ai_mock.stateChanged.connect(self.on_ai_mode_changed)

            controls_form.addRow("Model", self.ai_model)
            controls_form.addRow("Max Steps", self.ai_steps)
            controls_form.addRow("", self.ai_mock)
            layout.addWidget(self.ai_controls_box)

            prompt_box = QGroupBox("Prompt")
            prompt_layout = QVBoxLayout(prompt_box)

            examples = QHBoxLayout()
            examples.addWidget(QLabel("Quick prompts"))

            quick_prompts = [
                (
                    "Find K562",
                    "Find K562-related records and summarize count with a few representative rows.",
                ),
                (
                    "Takeout Today",
                    "List today's takeout/thaw/discard events and summarize by action.",
                ),
                (
                    "Suggest Slots",
                    "Recommend 2 consecutive empty slots, prefer boxes with more free space, and explain why.",
                ),
            ]
            for label, text in quick_prompts:
                btn = QPushButton(label)
                btn.clicked.connect(lambda _checked=False, value=text: self.on_ai_use_prompt(value))
                examples.addWidget(btn)
            examples.addStretch()
            prompt_layout.addLayout(examples)

            self.ai_prompt = QTextEdit()
            self.ai_prompt.setPlaceholderText(
                "Type a natural-language request... (Enter to send, Shift+Enter for newline)"
            )
            self.ai_prompt.setFixedHeight(90)
            self.ai_prompt.installEventFilter(self)
            prompt_layout.addWidget(self.ai_prompt)

            run_row = QHBoxLayout()
            self.ai_run_btn = QPushButton("Run Agent")
            self.ai_run_btn.clicked.connect(self.on_run_ai_agent)
            run_row.addWidget(self.ai_run_btn)

            ai_clear_btn = QPushButton("Clear AI Panel")
            ai_clear_btn.clicked.connect(self.on_ai_clear)
            run_row.addWidget(ai_clear_btn)
            run_row.addStretch()
            prompt_layout.addLayout(run_row)

            chat_box = QGroupBox("AI Chat")
            chat_layout = QVBoxLayout(chat_box)
            self.ai_chat = QTextEdit()
            self.ai_chat.setReadOnly(True)
            self.ai_chat.setPlaceholderText("Conversation timeline will appear here.")
            chat_layout.addWidget(self.ai_chat)
            layout.addWidget(chat_box, 3)

            self.ai_report_box = QGroupBox("Plan / Preview / Result / Audit")
            report_layout = QVBoxLayout(self.ai_report_box)
            self.ai_report = QTextEdit()
            self.ai_report.setReadOnly(True)
            self.ai_report.setPlaceholderText("Structured agent output will appear here.")
            report_layout.addWidget(self.ai_report)
            layout.addWidget(self.ai_report_box, 1)

            # Keep the input composer at the bottom for chat-style interaction.
            layout.addWidget(prompt_box)
            self.ai_controls_box.setVisible(False)
            self.ai_report_box.setVisible(False)
            self.on_ai_mode_changed()
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
            self.t_id.valueChanged.connect(self.on_thaw_fields_changed)
            self.t_position = QSpinBox()
            self.t_position.setRange(1, 999)
            self.t_position.valueChanged.connect(self.on_thaw_fields_changed)
            self.t_date = QDateEdit()
            self.t_date.setCalendarPopup(True)
            self.t_date.setDisplayFormat("yyyy-MM-dd")
            self.t_date.setDate(QDate.currentDate())
            self.t_action = QComboBox()
            self.t_action.addItems(["Takeout", "Thaw", "Discard"])
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

            context_box = QGroupBox("Selected Record Context")
            context_form = QFormLayout(context_box)
            self.t_ctx_status = QLabel("No prefill yet. Right-click slot -> Prefill to Thaw.")
            self.t_ctx_status.setStyleSheet("color: #64748b;")
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

            for label in [
                self.t_ctx_status,
                self.t_ctx_positions,
                self.t_ctx_target,
                self.t_ctx_check,
                self.t_ctx_plasmid,
                self.t_ctx_events,
                self.t_ctx_note,
            ]:
                label.setWordWrap(True)

            context_form.addRow("Status", self.t_ctx_status)
            context_form.addRow("Source Slot", self.t_ctx_source)
            context_form.addRow("Record ID", self.t_ctx_id)
            context_form.addRow("Cell", self.t_ctx_cell)
            context_form.addRow("Short", self.t_ctx_short)
            context_form.addRow("Box", self.t_ctx_box)
            context_form.addRow("All Positions", self.t_ctx_positions)
            context_form.addRow("Target Position", self.t_ctx_target)
            context_form.addRow("Position Check", self.t_ctx_check)
            context_form.addRow("Frozen At", self.t_ctx_frozen)
            context_form.addRow("Plasmid", self.t_ctx_plasmid)
            context_form.addRow("Thaw History", self.t_ctx_events)
            context_form.addRow("Note", self.t_ctx_note)
            layout.addWidget(context_box)

            batch = QGroupBox("Batch Thaw / Takeout")
            batch_form = QFormLayout(batch)
            self.b_entries = QLineEdit()
            self.b_entries.setPlaceholderText("e.g. 182:23,183:41")
            self.b_date = QDateEdit()
            self.b_date.setCalendarPopup(True)
            self.b_date.setDisplayFormat("yyyy-MM-dd")
            self.b_date.setDate(QDate.currentDate())
            self.b_action = QComboBox()
            self.b_action.addItems(["Takeout", "Thaw", "Discard"])
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
                        lines.append(f"ID {rec_id} ({short_name}): positions {positions}")
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
                    preview_text += f"\n- ... and {extra} more"
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
            if hasattr(self, "a_apply_btn") and hasattr(self, "a_dry_run"):
                self.a_apply_btn.setText("Preview Add Entry" if self.a_dry_run.isChecked() else "Execute Add Entry")
            if hasattr(self, "t_apply_btn") and hasattr(self, "t_dry_run"):
                self.t_apply_btn.setText(
                    "Preview Single Operation" if self.t_dry_run.isChecked() else "Execute Single Operation"
                )
            if hasattr(self, "b_apply_btn") and hasattr(self, "b_dry_run"):
                self.b_apply_btn.setText(
                    "Preview Batch Operation" if self.b_dry_run.isChecked() else "Execute Batch Operation"
                )

        def _lookup_record_by_id(self, record_id):
            try:
                key = int(record_id)
            except Exception:
                return None
            record = self.overview_records_by_id.get(key)
            return record if isinstance(record, dict) else None

        def _positions_text(self, positions):
            if not positions:
                return "-"
            try:
                normalized = sorted({int(p) for p in positions})
            except Exception:
                normalized = [str(p) for p in positions]
                return ",".join(normalized)
            return ",".join(str(p) for p in normalized)

        def _thaw_history_text(self, record):
            events = record.get("thaw_events")
            if not isinstance(events, list) or not events:
                return "No thaw history"
            last = events[-1] if isinstance(events[-1], dict) else {}
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_positions = self._positions_text(last.get("positions") or [])
            return f"{len(events)} event(s); last: {last_date} {last_action} [{last_positions}]"

        def on_thaw_fields_changed(self, _value=None):
            self._refresh_thaw_record_context()

        def _refresh_thaw_record_context(self):
            if not hasattr(self, "t_ctx_status"):
                return

            record_id = self.t_id.value() if hasattr(self, "t_id") else None
            target_position = self.t_position.value() if hasattr(self, "t_position") else None
            record = self._lookup_record_by_id(record_id)

            source_text = "-"
            source = self.t_prefill_source if isinstance(self.t_prefill_source, dict) else None
            if source:
                source_text = f"Box {source.get('box')} Pos {source.get('position')}"
            self.t_ctx_source.setText(source_text)

            self.t_ctx_target.setText(str(target_position) if target_position else "-")
            self.t_ctx_id.setText(str(record_id) if record_id else "-")

            if not record:
                if source:
                    self.t_ctx_status.setText("Record not found in current dataset. Please verify ID/position.")
                    self.t_ctx_status.setStyleSheet("color: #b45309;")
                else:
                    self.t_ctx_status.setText("No prefill yet. Right-click slot -> Prefill to Thaw.")
                    self.t_ctx_status.setStyleSheet("color: #64748b;")
                self.t_ctx_cell.setText("-")
                self.t_ctx_short.setText("-")
                self.t_ctx_box.setText("-")
                self.t_ctx_positions.setText("-")
                self.t_ctx_check.setText("-")
                self.t_ctx_check.setStyleSheet("color: #64748b;")
                self.t_ctx_frozen.setText("-")
                self.t_ctx_plasmid.setText("-")
                self.t_ctx_events.setText("-")
                self.t_ctx_note.setText("-")
                return

            self.t_ctx_cell.setText(str(record.get("parent_cell_line") or "-"))
            self.t_ctx_short.setText(str(record.get("short_name") or "-"))
            self.t_ctx_box.setText(str(record.get("box") or "-"))

            positions = record.get("positions") or []
            self.t_ctx_positions.setText(self._positions_text(positions))
            self.t_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
            plasmid = record.get("plasmid_name") or record.get("plasmid_id") or "-"
            self.t_ctx_plasmid.setText(str(plasmid))
            self.t_ctx_events.setText(self._thaw_history_text(record))
            self.t_ctx_note.setText(str(record.get("note") or "-"))

            target_pos_value = None
            try:
                if isinstance(target_position, int):
                    target_pos_value = target_position
                elif isinstance(target_position, str) and target_position.strip():
                    target_pos_value = int(target_position.strip())
                pos_ok = target_pos_value in {int(p) for p in positions}
            except Exception:
                pos_ok = False
            if pos_ok:
                self.t_ctx_check.setText("OK - target position belongs to this record")
                self.t_ctx_check.setStyleSheet("color: #15803d;")
            else:
                self.t_ctx_check.setText("WARNING - target position is NOT in this record")
                self.t_ctx_check.setStyleSheet("color: #b91c1c;")

            source_record_id = None
            if source:
                raw_source_id = source.get("record_id")
                if isinstance(raw_source_id, int):
                    source_record_id = raw_source_id
                elif isinstance(raw_source_id, str) and raw_source_id.strip():
                    try:
                        source_record_id = int(raw_source_id.strip())
                    except Exception:
                        source_record_id = None

            record_id_value = record_id if isinstance(record_id, int) else None
            if source and source_record_id is not None and record_id_value is not None and source_record_id == record_id_value:
                self.t_ctx_status.setText("Prefill context loaded from overview slot.")
                self.t_ctx_status.setStyleSheet("color: #15803d;")
            else:
                self.t_ctx_status.setText("Record context loaded from current ID field.")
                self.t_ctx_status.setStyleSheet("color: #64748b;")

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

        def on_ai_mode_changed(self):
            use_mock = self.ai_mock.isChecked()
            self.ai_model.setEnabled(not use_mock)
            if use_mock:
                self.ai_model.setPlaceholderText("Mock mode enabled: no external LLM call")
            else:
                self.ai_model.setPlaceholderText("e.g. anthropic/claude-3-5-sonnet")

        def on_ai_use_prompt(self, prompt):
            self.ai_prompt.setPlainText(str(prompt or "").strip())
            self.ai_prompt.setFocus()

        def on_ai_clear(self):
            self.ai_chat.clear()
            self.ai_report.clear()
            self.ai_history = []
            self._notify("AI conversation memory cleared", level="success")

        def _append_ai_chat(self, role, text):
            stamp = datetime.now().strftime("%H:%M:%S")
            block = f"[{stamp}] {role}\n{text}"
            if self.ai_chat.toPlainText().strip():
                self.ai_chat.append("")
            self.ai_chat.append(block)

        def _append_ai_history(self, role, content, max_turns=20):
            role_text = str(role or "").strip().lower()
            if role_text not in {"user", "assistant"}:
                return
            content_text = str(content or "").strip()
            if not content_text:
                return
            self.ai_history.append({"role": role_text, "content": content_text})
            if max_turns and len(self.ai_history) > max_turns:
                self.ai_history = self.ai_history[-max_turns:]

        def _compact_json(self, value, max_chars=200):
            try:
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                text = str(value)
            text = text.replace("\n", " ")
            if len(text) <= max_chars:
                return text
            return text[: max_chars - 3] + "..."

        def _load_audit_events_for_trace(self, trace_id, limit=30):
            if not trace_id:
                return []

            audit_path = os.path.join(os.path.dirname(os.path.abspath(self._yaml_path())), AUDIT_LOG_FILE)
            if not os.path.exists(audit_path):
                return []

            rows = []
            try:
                with open(audit_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except Exception:
                            continue
                        if event.get("trace_id") == trace_id:
                            rows.append(event)
            except Exception:
                return []

            return rows[-max(1, int(limit)) :]

        def _build_ai_report_text(self, run_result, audit_rows):
            scratchpad = run_result.get("scratchpad", []) if isinstance(run_result, dict) else []
            lines = []

            lines.append("Plan")
            if scratchpad:
                for item in scratchpad:
                    lines.append(
                        f"- Step {item.get('step')}: {item.get('action')} | thought: {item.get('thought') or '-'}"
                    )
            else:
                lines.append("- No tool steps (model may finish directly)")

            lines.append("")
            lines.append("Preview")
            preview_rows = []
            for item in scratchpad:
                obs = item.get("observation")
                if not isinstance(obs, dict):
                    continue
                if obs.get("dry_run") or ("preview" in obs):
                    preview_payload = obs.get("preview")
                    if preview_payload is None:
                        preview_payload = obs.get("result")
                    preview_rows.append(
                        f"- Step {item.get('step')} {item.get('action')}: {self._compact_json(preview_payload)}"
                    )
            if preview_rows:
                lines.extend(preview_rows)
            else:
                lines.append("- No dry-run preview output in this run")

            lines.append("")
            lines.append("Execution Result")
            if scratchpad:
                for item in scratchpad:
                    obs = item.get("observation")
                    if not isinstance(obs, dict):
                        lines.append(f"- Step {item.get('step')} {item.get('action')}: invalid observation")
                        continue
                    status = "OK" if obs.get("ok") else f"FAIL/{obs.get('error_code', 'unknown')}"
                    summary = obs.get("message")
                    if not summary and obs.get("result") is not None:
                        summary = self._compact_json(obs.get("result"))
                    if not summary and obs.get("preview") is not None:
                        summary = self._compact_json(obs.get("preview"))
                    if not summary:
                        summary = "(no message)"
                    lines.append(f"- Step {item.get('step')} {item.get('action')}: {status} | {summary}")
            else:
                lines.append("- No execution steps")

            lines.append("")
            lines.append("Audit")
            if audit_rows:
                for event in audit_rows:
                    if not isinstance(event, dict):
                        continue
                    err = (event.get("error") or {}).get("error_code")
                    lines.append(
                        "- "
                        + " | ".join(
                            [
                                str(event.get("timestamp", "-")),
                                str(event.get("action", "-")),
                                str(event.get("status", "-")),
                                f"error={err or '-'}",
                            ]
                        )
                    )
            else:
                lines.append("- No audit events found for this trace_id")

            lines.append("")
            lines.append("Final")
            lines.append(str(run_result.get("final") or "(empty final answer)"))
            return "\n".join(lines)

        def _set_ai_run_busy(self, busy):
            self.ai_run_inflight = bool(busy)
            if self.ai_run_inflight:
                self.ai_run_btn.setEnabled(False)
                self.ai_run_btn.setText("Running...")
            else:
                self.ai_run_btn.setEnabled(True)
                self.ai_run_btn.setText("Run Agent")

        def _start_ai_run(self, prompt):
            model = self.ai_model.text().strip() or None
            history = [dict(item) for item in self.ai_history if isinstance(item, dict)]
            worker = _AgentRunWorker(
                bridge=self.bridge,
                yaml_path=self._yaml_path(),
                query=prompt,
                model=model,
                max_steps=self.ai_steps.value(),
                mock=self.ai_mock.isChecked(),
                history=history,
            )
            thread = QThread(self)
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.progress.connect(self._on_ai_run_progress)
            worker.finished.connect(self._on_ai_run_finished)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(self._on_ai_run_thread_finished)

            self.ai_run_thread = thread
            self.ai_run_worker = worker
            self._set_ai_run_busy(True)
            thread.start()

        def _on_ai_run_progress(self, event):
            if not isinstance(event, dict):
                return

            event_type = str(event.get("type") or "").strip()
            if event_type == "run_start":
                trace_id = str(event.get("trace_id") or "")
                if trace_id:
                    self.statusBar().showMessage(f"Agent running ({trace_id[:12]}...)", 2500)
                return

            if event_type == "step_start":
                step = event.get("step")
                if step is not None:
                    self.statusBar().showMessage(f"Agent step {step}...", 2000)
                return

            if event_type != "step_end":
                return

            step = event.get("step")
            action = str(event.get("action") or "tool")
            raw_obs = event.get("observation")
            obs = raw_obs if isinstance(raw_obs, dict) else {}
            status = "OK" if obs.get("ok") else f"FAIL/{obs.get('error_code', 'unknown')}"
            summary = obs.get("message")
            preview_val = obs.get("preview")
            result_val = obs.get("result")
            if not summary and preview_val is not None:
                summary = self._compact_json(preview_val, max_chars=120)
            if not summary and result_val is not None:
                summary = self._compact_json(result_val, max_chars=120)

            line = f"Step {step}: {action} -> {status}" if step is not None else f"{action} -> {status}"
            if summary:
                line = f"{line} | {summary}"
            self._append_ai_chat("Agent", line)

        def _on_ai_run_thread_finished(self):
            self.ai_run_thread = None
            self.ai_run_worker = None

        def _on_ai_run_finished(self, response):
            self._set_ai_run_busy(False)
            response = response if isinstance(response, dict) else {"ok": False, "message": "Unexpected response"}

            self._emit(response)

            raw_result = response.get("result")
            run_result = raw_result if isinstance(raw_result, dict) else {}
            trace_id = run_result.get("trace_id")
            audit_rows = self._load_audit_events_for_trace(trace_id)
            self.ai_report.setPlainText(self._build_ai_report_text(run_result, audit_rows))

            final_text = str(run_result.get("final") or response.get("message") or "")
            self._append_ai_chat("Agent", final_text)
            self._append_ai_history("assistant", final_text)

            self._refresh_overview(update_output=False)
            self._refresh_backups_table(update_output=False)

            if response.get("ok"):
                scratchpad = run_result.get("scratchpad")
                if not isinstance(scratchpad, list):
                    scratchpad = []
                step_count = run_result.get("steps", len(scratchpad))
                self._notify(f"AI run completed in {step_count} step(s)", level="success")
            else:
                self._handle_tool_failure(response, "AI run failed", dialog_title="AI Agent Failed")

        def on_run_ai_agent(self):
            if self.ai_run_inflight:
                self.statusBar().showMessage("AI is running... Enter is disabled until this run finishes.", 2500)
                return

            prompt = self.ai_prompt.toPlainText().strip()
            if not prompt:
                self._warn("Please input a natural-language request first.")
                return

            self._append_ai_chat("You", prompt)
            self._append_ai_history("user", prompt)
            self.ai_prompt.clear()
            self.statusBar().showMessage("Agent is thinking...", 2000)
            self._start_ai_run(prompt)

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

        def _confirm_execute(self, title, details):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle(title)
            msg.setText("This operation will modify inventory YAML.")
            msg.setInformativeText(details)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            return msg.exec() == QMessageBox.Yes

        def _reset_overview_detail(self):
            self.overview_selected = None
            self.overview_hover_key = None
            if hasattr(self, "ov_hover_hint"):
                self.ov_hover_hint.setText("Hover a slot to preview details.")

        def _show_overview_detail(self, box_num, position, record):
            self.overview_selected = (box_num, position, record)
            if not hasattr(self, "ov_hover_hint"):
                return

            if not record:
                self.ov_hover_hint.setText(f"Box {box_num} Pos {position} | Empty slot")
                return

            rec_id = str(record.get("id", "-"))
            cell = str(record.get("parent_cell_line", "-"))
            short = str(record.get("short_name", "-"))
            frozen = str(record.get("frozen_at", "-"))
            plasmid = record.get("plasmid_name") or record.get("plasmid_id") or "-"
            self.ov_hover_hint.setText(
                f"Box {box_num} Pos {position} | ID {rec_id} | {cell} / {short} | Frozen {frozen} | Plasmid {plasmid}"
            )

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
                    button.setMouseTracking(True)
                    button.setAttribute(Qt.WA_Hover, True)
                    button.setProperty("overview_box", box_num)
                    button.setProperty("overview_position", position)
                    button.installEventFilter(self)
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
                self.overview_records_by_id = {}
                self._reset_overview_detail()
                self._refresh_thaw_record_context()
                return

            payload = stats_response.get("result", {})
            data = payload.get("data", {})
            records = data.get("inventory", [])
            self.overview_records_by_id = {}
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                rec_id = rec.get("id")
                key = None
                if isinstance(rec_id, int):
                    key = rec_id
                elif isinstance(rec_id, str) and rec_id.strip():
                    try:
                        key = int(rec_id.strip())
                    except Exception:
                        key = None
                if key is None:
                    continue
                self.overview_records_by_id[key] = rec
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

            if hasattr(self, "ov_meta_stats"):
                self.ov_meta_stats.setText(
                    f"Capacity: {self.ov_total_capacity_value.text()} | Ops (7d): {self.ov_ops7_value.text()}"
                )

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
            self._refresh_thaw_record_context()

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

        def on_overview_toggle_filters(self, checked):
            visible = bool(checked)
            self.ov_filter_advanced_widget.setVisible(visible)
            self.ov_filter_toggle_btn.setText("Hide Filters" if visible else "More Filters")

        def on_overview_clear_filters(self):
            self.ov_filter_keyword.clear()
            self.ov_filter_box.setCurrentIndex(0)
            self.ov_filter_cell.setCurrentIndex(0)
            self.ov_filter_show_empty.setChecked(True)
            if self.ov_filter_toggle_btn.isChecked():
                self.ov_filter_toggle_btn.setChecked(False)
            self._apply_overview_filters()

        def on_overview_cell_clicked(self, box_num, position):
            self.on_overview_cell_hovered(box_num, position, force=True)

        def on_overview_cell_hovered(self, box_num, position, force=False):
            hover_key = (box_num, position)
            if not force and self.overview_hover_key == hover_key:
                return
            button = self.overview_cells.get((box_num, position))
            if button is not None and not button.isVisible():
                return
            record = self.overview_pos_map.get((box_num, position))
            self.overview_hover_key = hover_key
            self._show_overview_detail(box_num, position, record)

        def on_overview_cell_context_menu(self, box_num, position, global_pos):
            record = self.overview_pos_map.get((box_num, position))
            self.on_overview_cell_hovered(box_num, position, force=True)

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
            self.t_prefill_source = {
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            }
            self.t_id.setValue(rec_id)
            self.t_position.setValue(position)
            self.t_action.setCurrentText("Takeout")
            self._refresh_thaw_record_context()
            self._set_operation_mode("thaw")
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
            dry_run = self.a_dry_run.isChecked()
            if not dry_run:
                details = (
                    f"Cell: {self.a_parent.text().strip() or '-'}\n"
                    f"Short: {self.a_short.text().strip() or '-'}\n"
                    f"Box: {box_value}\n"
                    f"Positions: {','.join(str(p) for p in positions)}\n"
                    f"Frozen at: {self.a_date.date().toString('yyyy-MM-dd')}"
                )
                if not self._confirm_execute("Confirm Add Entry", details):
                    self._notify("Add entry cancelled")
                    return

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
                dry_run=dry_run,
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
            date_value = self.t_date.date().toString("yyyy-MM-dd")
            dry_run = self.t_dry_run.isChecked()
            if not dry_run:
                record = self._lookup_record_by_id(record_id)
                if record:
                    positions = record.get("positions") or []
                    pos_ok = False
                    try:
                        pos_ok = int(position) in {int(p) for p in positions}
                    except Exception:
                        pos_ok = False
                    position_check = "OK" if pos_ok else "WARNING: not in record positions"
                    details = (
                        f"Record ID: {record_id}\n"
                        f"Cell/Short: {record.get('parent_cell_line') or '-'} / {record.get('short_name') or '-'}\n"
                        f"Box: {record.get('box') or '-'}\n"
                        f"All Positions: {self._positions_text(positions)}\n"
                        f"Target Position: {position} ({position_check})\n"
                        f"Frozen At: {record.get('frozen_at') or '-'}\n"
                        f"Plasmid: {record.get('plasmid_name') or record.get('plasmid_id') or '-'}\n"
                        f"Action: {self.t_action.currentText()}\n"
                        f"Date: {date_value}"
                    )
                else:
                    details = (
                        f"Record ID: {record_id}\n"
                        f"Target Position: {position}\n"
                        "WARNING: Record not found in current dataset\n"
                        f"Action: {self.t_action.currentText()}\n"
                        f"Date: {date_value}"
                    )
                if not self._confirm_execute("Confirm Single Operation", details):
                    self._notify("Single operation cancelled")
                    return

            response = self.bridge.record_thaw(
                yaml_path=self._yaml_path(),
                record_id=record_id,
                position=position,
                date_str=date_value,
                action=self.t_action.currentText(),
                note=self.t_note.text().strip() or None,
                dry_run=dry_run,
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
            entries_text = self.b_entries.text().strip()
            try:
                entries = parse_batch_entries(entries_text)
            except ValueError as exc:
                self._warn(str(exc))
                return

            date_value = self.b_date.date().toString("yyyy-MM-dd")
            dry_run = self.b_dry_run.isChecked()
            if not dry_run:
                preview_pairs = ", ".join(f"{rid}:{pos}" for rid, pos in entries[:6])
                if len(entries) > 6:
                    preview_pairs = f"{preview_pairs}, ..."
                details = (
                    f"Count: {len(entries)}\n"
                    f"Action: {self.b_action.currentText()}\n"
                    f"Date: {date_value}\n"
                    f"Entries: {preview_pairs}"
                )
                if not self._confirm_execute("Confirm Batch Operation", details):
                    self._notify("Batch operation cancelled")
                    return

            response = self.bridge.batch_thaw(
                yaml_path=self._yaml_path(),
                entries=entries,
                date_str=date_value,
                action=self.b_action.currentText(),
                note=self.b_note.text().strip() or None,
                dry_run=dry_run,
            )
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
    cjk_font = _pick_cjk_font()
    if cjk_font is not None:
        app.setFont(cjk_font)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
