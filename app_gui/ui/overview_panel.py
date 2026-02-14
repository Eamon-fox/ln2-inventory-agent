from datetime import date, datetime
import os
from PySide6.QtCore import Qt, Signal, QEvent, QMimeData, QPoint
from PySide6.QtGui import QDrag, QDropEvent, QDragEnterEvent, QDragMoveEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QScrollArea,
    QSizePolicy, QGroupBox, QMenu, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from app_gui.ui.utils import cell_color, build_color_palette
from lib.position_fmt import pos_to_display, box_to_display, get_box_count
from lib.csv_export import build_export_rows
from app_gui.ui.theme import (
    cell_occupied_style, 
    cell_empty_style,
    cell_preview_add_style,
    cell_preview_takeout_style,
    cell_preview_move_source_style,
    cell_preview_move_target_style,
)
from app_gui.i18n import tr, t
from app_gui.plan_preview import simulate_plan_pos_map

MIME_TYPE_MOVE = "application/x-ln2-move"

class CellButton(QPushButton):
    doubleClicked = Signal(int, int)
    dropReceived = Signal(int, int, int, int, int)

    def __init__(self, text, box, pos, parent=None):
        super().__init__(text, parent)
        self.box = box
        self.pos = pos
        self.record_id = None
        self.setAcceptDrops(True)
        self._drag_start_pos = None

    def set_record_id(self, record_id):
        self.record_id = record_id

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.box, self.pos)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None or self.record_id is None:
            super().mouseMoveEvent(event)
            return

        if (event.pos() - self._drag_start_pos).manhattanLength() < 20:
            super().mouseMoveEvent(event)
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE_MOVE, f"{self.box}:{self.pos}:{self.record_id}".encode())
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)
        self._drag_start_pos = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            data = bytes(event.mimeData().data(MIME_TYPE_MOVE)).decode()
            parts = data.split(":")
            if len(parts) == 3:
                from_box = int(parts[0])
                from_pos = int(parts[1])
                record_id = int(parts[2])
                self.dropReceived.emit(from_box, from_pos, self.box, self.pos, record_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

class OverviewPanel(QWidget):
    status_message = Signal(str, int)
    request_prefill = Signal(dict)
    request_prefill_background = Signal(dict)
    request_quick_add = Signal()
    request_add_prefill = Signal(dict)
    request_add_prefill_background = Signal(dict)
    request_move_prefill = Signal(dict)
    request_query_prefill = Signal(dict)
    # Use object to preserve non-string dict keys (Qt map coercion can drop int keys).
    data_loaded = Signal(object)
    plan_items_requested = Signal(list)

    def __init__(self, bridge, yaml_path_getter):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        
        # State
        self.overview_shape = None
        self.overview_cells = {}
        self.overview_pos_map = {}
        self.overview_box_live_labels = {}
        self.overview_box_groups = {}
        self.overview_selected_key = None
        self.overview_hover_key = None
        self.overview_records_by_id = {}
        self._plan_items = []
        self._current_records = []
        self._current_font_sizes = (9, 8)
        self._plan_simulation = None
        self._hover_exec_preview_active = False
        self._status_before_hover = None
        self._overview_view_mode = "grid"
        self._table_rows = []
        self._table_columns = []
        self._table_row_records = []

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        # Summary Cards
        summary_row = QHBoxLayout()
        summary_row.setSpacing(6)
        
        self.ov_total_records_value = self._build_card(summary_row, tr("overview.totalRecords"))
        self.ov_occupied_value = self._build_card(summary_row, tr("overview.occupied"))
        self.ov_empty_value = self._build_card(summary_row, tr("overview.empty"))
        self.ov_rate_value = self._build_card(summary_row, tr("overview.occupancyRate"))
        
        layout.addLayout(summary_row)

        # Meta Stats
        self.ov_total_capacity_value = QLabel("-")
        self.ov_ops7_value = QLabel("-")
        self.ov_meta_stats = QLabel(f"{tr('overview.capacity')}: - | {tr('overview.ops7d')}: -")
        self.ov_meta_stats.setStyleSheet("color: var(--status-muted);")
        layout.addWidget(self.ov_meta_stats)

        # Action Row
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        refresh_btn = QPushButton(tr("overview.refresh"))
        refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(refresh_btn)

        action_row.addWidget(QLabel(tr("overview.view")))
        self.ov_view_mode = QComboBox()
        self.ov_view_mode.addItem(tr("overview.viewGrid"), "grid")
        self.ov_view_mode.addItem(tr("overview.viewTable"), "table")
        self.ov_view_mode.currentIndexChanged.connect(self._on_view_mode_changed)
        action_row.addWidget(self.ov_view_mode)

        action_row.addStretch()
        layout.addLayout(action_row)

        # Filter Row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel(tr("overview.search")))

        self.ov_filter_keyword = QLineEdit()
        self.ov_filter_keyword.setPlaceholderText(tr("overview.searchPlaceholder"))
        self.ov_filter_keyword.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.ov_filter_keyword, 2)

        self.ov_filter_toggle_btn = QPushButton(tr("overview.moreFilters"))
        self.ov_filter_toggle_btn.setCheckable(True)
        self.ov_filter_toggle_btn.toggled.connect(self.on_toggle_filters)
        filter_row.addWidget(self.ov_filter_toggle_btn)
        layout.addLayout(filter_row)

        # Advanced Filters
        advanced_filter_row = QHBoxLayout()
        advanced_filter_row.setSpacing(6)

        self.ov_filter_box = QComboBox()
        self.ov_filter_box.addItem(tr("overview.allBoxes"), None)
        self.ov_filter_box.currentIndexChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_box)

        self.ov_filter_cell = QComboBox()
        self.ov_filter_cell.addItem(tr("overview.allCells"), None)
        self.ov_filter_cell.currentIndexChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_cell, 1)

        self.ov_filter_show_empty = QCheckBox(tr("overview.showEmpty"))
        self.ov_filter_show_empty.setChecked(True)
        self.ov_filter_show_empty.stateChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_show_empty)

        clear_filter_btn = QPushButton(tr("overview.clearFilter"))
        clear_filter_btn.clicked.connect(self.on_clear_filters)
        advanced_filter_row.addWidget(clear_filter_btn)
        advanced_filter_row.addStretch()

        self.ov_filter_advanced_widget = QWidget()
        self.ov_filter_advanced_widget.setLayout(advanced_filter_row)
        self.ov_filter_advanced_widget.setVisible(False)
        layout.addWidget(self.ov_filter_advanced_widget)

        self.ov_status = QLabel(tr("overview.statusReady"))
        layout.addWidget(self.ov_status)

        self.ov_hover_hint = QLabel(tr("overview.hoverHint"))
        self.ov_hover_hint.setStyleSheet("color: var(--text-weak); font-weight: 500;")
        self.ov_hover_hint.setWordWrap(True)
        layout.addWidget(self.ov_hover_hint)

        # Zoom controls
        self._zoom_level = 1.0
        self._base_cell_size = 36  # recalculated on refresh
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(4)
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedSize(24, 24)
        zoom_out_btn.setToolTip(tr("overview.zoomOut"))
        zoom_out_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level - 0.1))
        zoom_row.addWidget(zoom_out_btn)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(42)
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setStyleSheet("font-size: 11px;")
        zoom_row.addWidget(self._zoom_label)
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(24, 24)
        zoom_in_btn.setToolTip(tr("overview.zoomIn"))
        zoom_in_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level + 0.1))
        zoom_row.addWidget(zoom_in_btn)
        zoom_reset_btn = QPushButton(tr("overview.zoomReset"))
        zoom_reset_btn.setToolTip(tr("overview.zoomReset"))
        zoom_reset_btn.clicked.connect(lambda: self._set_zoom(1.0))
        zoom_row.addWidget(zoom_reset_btn)
        zoom_row.addStretch()
        layout.addLayout(zoom_row)

        # Grid Area
        self.ov_scroll = QScrollArea()
        self.ov_scroll.setWidgetResizable(True)
        self.ov_scroll.installEventFilter(self)
        self.ov_boxes_widget = QWidget()
        self.ov_boxes_layout = QGridLayout(self.ov_boxes_widget)
        self.ov_boxes_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.ov_boxes_layout.setContentsMargins(0, 0, 0, 0)
        self.ov_boxes_layout.setHorizontalSpacing(4)
        self.ov_boxes_layout.setVerticalSpacing(6)
        self.ov_scroll.setWidget(self.ov_boxes_widget)

        # Table Area
        self.ov_table = QTableWidget()
        self.ov_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ov_table.verticalHeader().setVisible(False)
        self.ov_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ov_table.setSelectionMode(QTableWidget.SingleSelection)
        self.ov_table.cellDoubleClicked.connect(self.on_table_row_double_clicked)

        self.ov_view_stack = QStackedWidget()
        self.ov_view_stack.addWidget(self.ov_scroll)  # grid
        self.ov_view_stack.addWidget(self.ov_table)   # table
        layout.addWidget(self.ov_view_stack, 1)

    def _build_card(self, layout, title):
        card = QGroupBox(title)
        card.setStyleSheet("""
            QGroupBox {
                background-color: var(--background-inset);
                border: 1px solid var(--border-weak);
                border-radius: var(--radius-md);
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                color: var(--text-weak);
                font-size: 11px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        value_label = QLabel("-")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("font-size: 16px; font-weight: 500; color: var(--text-strong);")
        card_layout.addWidget(value_label)
        layout.addWidget(card)
        return value_label

    def _on_view_mode_changed(self):
        mode = self.ov_view_mode.currentData()
        if mode not in {"grid", "table"}:
            mode = "grid"

        self._overview_view_mode = mode
        self.ov_view_stack.setCurrentIndex(0 if mode == "grid" else 1)

        is_table_mode = mode == "table"
        self.ov_filter_show_empty.setEnabled(not is_table_mode)
        self.ov_filter_show_empty.setToolTip(
            tr("overview.showEmptyGridOnly") if is_table_mode else ""
        )
        self._apply_filters()

    def _set_table_columns(self, headers):
        self.ov_table.setRowCount(0)
        self.ov_table.setColumnCount(len(headers))
        self.ov_table.setHorizontalHeaderLabels(headers)
        header = self.ov_table.horizontalHeader()
        for idx in range(len(headers)):
            mode = QHeaderView.Stretch if idx == len(headers) - 1 else QHeaderView.ResizeToContents
            header.setSectionResizeMode(idx, mode)
        self.ov_table.setSortingEnabled(False)

    def _rebuild_table_rows(self, records):
        meta = getattr(self, "_current_meta", {})
        from lib.custom_fields import get_color_key

        payload = build_export_rows(records or [], meta=meta)
        self._table_columns = list(payload.get("columns") or [])

        color_key = get_color_key(meta)
        rows = []
        for values in payload.get("rows") or []:
            rid_raw = values.get("id")
            record = None
            if rid_raw not in (None, ""):
                try:
                    record = self.overview_records_by_id.get(int(rid_raw))
                except (TypeError, ValueError):
                    record = None

            box_value = values.get("box")
            try:
                box_number = int(box_value)
            except (TypeError, ValueError):
                box_number = None

            color_value = ""
            if isinstance(record, dict):
                color_value = str(record.get(color_key) or "")
            elif color_key in values:
                color_value = str(values.get(color_key) or "")

            search_text = " ".join(str(values.get(col, "")) for col in self._table_columns).lower()
            rows.append(
                {
                    "values": values,
                    "record": record,
                    "box": box_number,
                    "color_value": color_value,
                    "search_text": search_text,
                }
            )

        self._table_rows = rows
        self._set_table_columns(self._table_columns)
        self._table_row_records = []

    def _render_table_rows(self, rows):
        self.ov_table.setRowCount(0)
        self._table_row_records = []

        for row_index, row_data in enumerate(rows):
            self.ov_table.insertRow(row_index)
            values = row_data.get("values") or {}
            for col_index, column in enumerate(self._table_columns):
                value = values.get(column, "")
                self.ov_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
            self._table_row_records.append(row_data.get("record"))

    def on_table_row_double_clicked(self, row, _col):
        if row < 0 or row >= len(self._table_row_records):
            return

        record = self._table_row_records[row]
        if not isinstance(record, dict):
            return

        positions = record.get("positions") or []
        if not positions:
            return

        try:
            record_id = int(record.get("id"))
            box_num = int(record.get("box"))
            position = int(positions[0])
        except (TypeError, ValueError):
            return

        self._set_selected_cell(box_num, position)
        self.request_prefill_background.emit(
            {
                "box": box_num,
                "position": position,
                "record_id": record_id,
            }
        )
        self.status_message.emit(t("overview.prefillTakeoutAuto", id=record_id), 2000)

    def eventFilter(self, obj, event):
        # Ctrl+Wheel zoom on scroll area
        if obj is self.ov_scroll and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self._set_zoom(self._zoom_level + 0.1)
                elif delta < 0:
                    self._set_zoom(self._zoom_level - 0.1)
                return True  # consume event
        if event.type() in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
            box_num = obj.property("overview_box")
            position = obj.property("overview_position")
            if box_num is not None and position is not None:
                self.on_cell_hovered(int(box_num), int(position))
        return super().eventFilter(obj, event)

    def _set_zoom(self, level):
        self._zoom_level = max(0.5, min(3.0, round(level, 1)))
        self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")
        self._apply_zoom()

    def _apply_zoom(self):
        """Resize all existing cell buttons and repaint with scaled font."""
        cell_size = max(12, int(self._base_cell_size * self._zoom_level))
        font_size_occupied = max(7, int(9 * self._zoom_level))
        font_size_empty = max(6, int(8 * self._zoom_level))
        self._current_font_sizes = (font_size_occupied, font_size_empty)
        for button in self.overview_cells.values():
            button.setFixedSize(cell_size, cell_size)
        # Repaint all cells with current data
        self._repaint_all_cells()

    def _repaint_all_cells(self):
        """Repaint all cell buttons using cached data."""
        records = getattr(self, "_current_records", [])
        record_map = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            box = rec.get("box")
            for pos in (rec.get("positions") or []):
                record_map[(box, pos)] = rec
        for (box_num, position), button in self.overview_cells.items():
            record = record_map.get((box_num, position))
            self._paint_cell(button, box_num, position, record)

    def refresh(self):
        yaml_path = self.yaml_path_getter()
        if not yaml_path or not os.path.isfile(yaml_path):
            self.ov_status.setText(t("main.fileNotFound", path=yaml_path or ""))
            self.overview_records_by_id = {}
            self.overview_selected_key = None
            self._reset_detail()
            return

        stats_response = self.bridge.generate_stats(yaml_path)
        timeline_response = self.bridge.collect_timeline(yaml_path, days=7, all_history=False)

        if not stats_response.get("ok"):
            self.ov_status.setText(t("overview.loadFailed", error=stats_response.get('message', 'unknown error')))
            self.overview_records_by_id = {}
            self.overview_selected_key = None
            self._reset_detail()
            return

        payload = stats_response.get("result", {})
        data = payload.get("data", {})
        records = data.get("inventory", [])
        self._current_meta = data.get("meta", {})
        self._current_records = records

        # Build color palette from meta
        from lib.custom_fields import get_cell_line_options
        build_color_palette(get_cell_line_options(self._current_meta))
        
        self.overview_records_by_id = {}
        for rec in records:
            if not isinstance(rec, dict): continue
            try:
                self.overview_records_by_id[int(rec.get("id"))] = rec
            except (ValueError, TypeError): pass
        
        self.data_loaded.emit(self.overview_records_by_id)

        layout = payload.get("layout", {})
        stats = payload.get("stats", {})
        overall = stats.get("overall", {})
        box_stats = stats.get("boxes", {})

        rows = int(layout.get("rows", 9))
        cols = int(layout.get("cols", 9))
        self._current_layout = layout
        box_numbers = sorted([int(k) for k in box_stats.keys()], key=int)
        if not box_numbers:
            box_count = get_box_count(layout)
            box_numbers = list(range(1, box_count + 1))

        shape = (rows, cols, tuple(box_numbers))
        if self.overview_shape != shape:
            self._rebuild_boxes(rows, cols, box_numbers)

        pos_map = {}
        for rec in records:
            box = rec.get("box")
            if box is None: continue
            for pos in rec.get("positions") or []:
                pos_map[(int(box), int(pos))] = rec

        self.overview_pos_map = pos_map

        self.ov_total_records_value.setText(str(len(records)))
        self.ov_total_capacity_value.setText(str(overall.get("total_capacity", "-")))
        self.ov_occupied_value.setText(str(overall.get("total_occupied", "-")))
        self.ov_empty_value.setText(str(overall.get("total_empty", "-")))
        self.ov_rate_value.setText(f"{overall.get('occupancy_rate', 0):.1f}%")

        if len(records) == 0:
            self.ov_hover_hint.setText(tr("overview.emptyHint"))
            self.ov_hover_hint.setStyleSheet("color: var(--warning); font-weight: 500; padding: 8px; background-color: rgba(245,158,11,0.1); border-radius: 4px;")
        else:
            self.ov_hover_hint.setText(tr("overview.hoverHint"))
            self.ov_hover_hint.setStyleSheet("color: var(--text-weak); font-weight: 500;")

        if timeline_response.get("ok"):
            ops7 = timeline_response.get("result", {}).get("summary", {}).get("total_ops", 0)
            self.ov_ops7_value.setText(str(ops7))
        else:
            self.ov_ops7_value.setText(tr("common.na"))

        self.ov_meta_stats.setText(
            tr("overview.capacity") + f": {self.ov_total_capacity_value.text()} | " + tr("overview.ops7d") + f": {self.ov_ops7_value.text()}"
        )

        for box_num in box_numbers:
            stats_item = box_stats.get(str(box_num), {})
            occupied = stats_item.get("occupied", 0)
            empty = stats_item.get("empty", rows * cols)
            total = stats_item.get("total", rows * cols)
            live = self.overview_box_live_labels.get(box_num)
            if live is not None:
                live.setText(t("overview.occupiedCount", occupied=occupied, total=total, empty=empty))

        for key, button in self.overview_cells.items():
            box_num, position = key
            rec = pos_map.get(key)
            self._paint_cell(button, box_num, position, rec)

        self._rebuild_table_rows(records)
        self._refresh_filter_options(records, box_numbers)
        self._apply_filters()

        self.ov_status.setText(
            t("overview.loadedStatus", count=len(records), time=datetime.now().strftime("%H:%M:%S"))
        )

    def _rebuild_boxes(self, rows, cols, box_numbers):
        # clear layout
        while self.ov_boxes_layout.count():
            item = self.ov_boxes_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()

        self.overview_cells = {}
        self.overview_box_live_labels = {}
        self.overview_box_groups = {}
        self.overview_selected_key = None
        self._reset_detail()

        layout = getattr(self, "_current_layout", {})
        total_slots = rows * cols
        self._base_cell_size = max(24, min(36, 320 // max(rows, cols)))
        cell_size = max(12, int(self._base_cell_size * self._zoom_level))
        columns = 3
        for idx, box_num in enumerate(box_numbers):
            box_label = box_to_display(box_num, layout)
            group = QGroupBox(t("overview.boxLabel", box=box_label))
            group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            group_layout.setSpacing(4)

            live_label = QLabel(t("overview.occupiedCount", occupied=0, total=total_slots, empty=total_slots))
            group_layout.addWidget(live_label)
            self.overview_box_live_labels[box_num] = live_label

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(1)
            grid.setVerticalSpacing(1)
            for position in range(1, total_slots + 1):
                r = (position - 1) // cols
                c = (position - 1) % cols
                display_text = pos_to_display(position, layout)
                button = CellButton(display_text, box_num, position)
                button.setFixedSize(cell_size, cell_size)
                button.setMouseTracking(True)
                button.setAttribute(Qt.WA_Hover, True)
                button.setProperty("overview_box", box_num)
                button.setProperty("overview_position", position)
                button.installEventFilter(self)
                
                # Single click
                button.clicked.connect(
                    lambda _checked=False, b=box_num, p=position: self.on_cell_clicked(b, p)
                )
                
                # Double click
                button.doubleClicked.connect(self.on_cell_double_clicked)
                
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda point, b=box_num, p=position, btn=button: self.on_cell_context_menu(
                        b, p, btn.mapToGlobal(point)
                    )
                )
                button.dropReceived.connect(self._on_cell_drop)
                self.overview_cells[(box_num, position)] = button
                grid.addWidget(button, r, c)

            group_layout.addLayout(grid)
            self.ov_boxes_layout.addWidget(group, idx // columns, idx % columns)
            self.overview_box_groups[box_num] = group

        self.overview_shape = (rows, cols, tuple(box_numbers))

    def update_plan_preview(self, plan_items):
        """Update overview cells to show plan preview effects."""
        self._plan_items = list(plan_items or [])
        self._plan_simulation = None
        if self._plan_items:
            try:
                self._plan_simulation = simulate_plan_pos_map(
                    base_records_by_id=self.overview_records_by_id,
                    plan_items=self._plan_items,
                )
            except Exception:
                self._plan_simulation = None
        # Plan changed while hover preview is active: cancel preview and repaint
        # the normal overlay to avoid showing stale simulated state.
        if self._hover_exec_preview_active:
            self._hover_exec_preview_active = False
            if self._status_before_hover is not None:
                self.ov_status.setText(self._status_before_hover)
                self._status_before_hover = None

        if not plan_items:
            for (box_num, position), button in self.overview_cells.items():
                key = (box_num, position)
                record = self.overview_pos_map.get(key)
                self._paint_cell(button, box_num, position, record)
            return
            
        preview_positions = {
            "add": set(),
            "takeout": set(),
            "move_source": set(),
            "move_target": set(),
        }
        
        for item in plan_items:
            action = item.get("action", "").lower()
            box = item.get("box")
            position = item.get("position")
            to_box = item.get("to_box")
            to_position = item.get("to_position")
            
            if action == "add" and box and position:
                preview_positions["add"].add((int(box), int(position)))
            
            elif action in ("takeout", "thaw", "discard") and box and position:
                preview_positions["takeout"].add((int(box), int(position)))
            
            elif action == "move" and box and position:
                preview_positions["move_source"].add((int(box), int(position)))
                if to_position:
                    target_box = int(to_box) if to_box else int(box)
                    preview_positions["move_target"].add((target_box, int(to_position)))
        
        for (box_num, position), button in self.overview_cells.items():
            key = (box_num, position)
            record = self.overview_pos_map.get(key)
            is_selected = self.overview_selected_key == key
            
            if key in preview_positions["add"]:
                button.setText(tr("overview.previewAdd"))
                button.setStyleSheet(cell_preview_add_style())
            elif key in preview_positions["takeout"]:
                button.setText(tr("overview.previewOut"))
                button.setStyleSheet(cell_preview_takeout_style())
            elif key in preview_positions["move_source"]:
                orig_record = self.overview_pos_map.get(key)
                label = ""
                if orig_record:
                    from lib.custom_fields import get_display_key
                    _dk = get_display_key(getattr(self, "_current_meta", {}))
                    label = str(orig_record.get(_dk) or "")[:4]
                button.setText(f"{label}→" if label else "→")
                button.setStyleSheet(cell_preview_move_source_style())
            elif key in preview_positions["move_target"]:
                button.setText("←")
                button.setStyleSheet(cell_preview_move_target_style())
            else:
                self._paint_cell(button, box_num, position, record)

    def _focus_style(self, base_style: str) -> str:
        """Overlay a stronger border to highlight a cell in preview mode."""
        return (
            (base_style or "")
            + """
            QPushButton { border: 3px solid var(--warning); }
            QPushButton:hover { border: 3px solid var(--warning); }
            """
        )

    def on_plan_item_hovered(self, item):
        """Show a simulated post-execution overview when hovering a plan item."""
        if not item:
            self._hover_exec_preview_active = False
            if self._status_before_hover is not None:
                self.ov_status.setText(self._status_before_hover)
                self._status_before_hover = None
            self.update_plan_preview(self._plan_items)
            return

        if not self._plan_items:
            return

        sim = self._plan_simulation
        if not isinstance(sim, dict):
            try:
                sim = simulate_plan_pos_map(
                    base_records_by_id=self.overview_records_by_id,
                    plan_items=self._plan_items,
                )
            except Exception:
                sim = None
        if not isinstance(sim, dict):
            return

        pos_map = sim.get("pos_map") if isinstance(sim.get("pos_map"), dict) else {}
        preview_errors = sim.get("errors") if isinstance(sim.get("errors"), list) else []

        if self._status_before_hover is None:
            self._status_before_hover = self.ov_status.text()

        action = str(item.get("action") or "").lower()
        label = str(item.get("label") or "")
        suffix = f" | issues: {len(preview_errors)}" if preview_errors else ""
        self.ov_status.setText(f"[PREVIEW] After executing plan: focus {action} {label}{suffix}".strip())

        self._hover_exec_preview_active = True

        # Render the simulated final occupancy map.
        for (box_num, position), button in self.overview_cells.items():
            key = (box_num, position)
            record = pos_map.get(key)
            self._paint_cell(button, box_num, position, record)

        # Highlight the focused operation's affected cells (best-effort).
        focus_keys = set()
        payload = item.get("payload") or {}

        if action == "add":
            box = payload.get("box", item.get("box"))
            box = int(box) if box not in (None, "") else None
            positions = payload.get("positions") or []
            if box is not None:
                for p in positions:
                    try:
                        focus_keys.add((box, int(p)))
                    except Exception:
                        pass
        elif action in ("takeout", "thaw", "discard"):
            box = item.get("box")
            pos = item.get("position")
            try:
                focus_keys.add((int(box), int(pos)))
            except Exception:
                pass
        elif action == "move":
            box = item.get("box")
            pos = item.get("position")
            to_pos = item.get("to_position")
            to_box = item.get("to_box")
            try:
                focus_keys.add((int(box), int(pos)))
            except Exception:
                pass
            if to_pos not in (None, ""):
                try:
                    target_box = int(to_box) if to_box else int(box)
                    focus_keys.add((target_box, int(to_pos)))
                except Exception:
                    pass

        for key in focus_keys:
            btn = self.overview_cells.get(key)
            if btn is not None:
                btn.setStyleSheet(self._focus_style(btn.styleSheet()))

    def _paint_cell(self, button, box_num, position, record):
        from lib.custom_fields import get_display_key, get_color_key, get_effective_fields, STRUCTURAL_FIELD_KEYS
        is_selected = self.overview_selected_key == (box_num, position)
        layout = getattr(self, "_current_layout", {})
        meta = getattr(self, "_current_meta", {})
        display_pos = pos_to_display(position, layout)
        fs_occ, fs_empty = getattr(self, "_current_font_sizes", (9, 8))
        if record:
            dk = get_display_key(meta)
            ck = get_color_key(meta)
            dk_val = str(record.get(dk) or "")
            ck_val = str(record.get(ck) or "")
            # Scale label truncation with zoom
            max_chars = max(3, int(6 * self._zoom_level))
            label = dk_val[:max_chars] if dk_val else display_pos
            # Color based on color_key field
            color = cell_color(ck_val or None)
            button.setText(label)

            # Dynamic tooltip from effective fields
            cl = record.get("cell_line")
            tt = [
                f"ID: {record.get('id', '-')}",
                f"Pos: {box_num}:{position}",
            ]
            if cl:
                tt.append(f"Cell Line: {cl}")
            for fdef in get_effective_fields(meta):
                fk = fdef["key"]
                fv = record.get(fk)
                if fv is not None and str(fv):
                    tt.append(f"{fdef.get('label', fk)}: {fv}")
            tt.append(f"Date: {record.get('frozen_at', '-')}")

            button.setToolTip("\n".join(tt))
            button.setStyleSheet(cell_occupied_style(color, is_selected, font_size=fs_occ))
            # Dynamic search text — include cell_line + all user fields
            parts = [str(record.get("id", "")), str(box_num), str(position),
                     str(record.get("cell_line") or ""),
                     str(record.get("frozen_at") or "")]
            for k, v in record.items():
                if k not in STRUCTURAL_FIELD_KEYS and k != "id":
                    parts.append(str(v or ""))
            button.setProperty("search_text", " ".join(parts).lower())
            button.setProperty("display_key_value", dk_val)
            button.setProperty("color_key_value", ck_val)
            button.setProperty("is_empty", False)
            button.set_record_id(int(record.get("id", 0)))
        else:
            button.setText(display_pos)
            button.setToolTip(t("overview.emptyCellTooltip", box=box_num, position=position))
            button.setStyleSheet(cell_empty_style(is_selected, font_size=fs_empty))
            button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
            button.setProperty("color_key_value", "")
            button.setProperty("is_empty", True)
            button.set_record_id(None)

    def _set_selected_cell(self, box_num, position):
        new_key = (box_num, position)
        old_key = self.overview_selected_key
        if old_key == new_key:
            return

        self.overview_selected_key = new_key
        for key in (old_key, new_key):
            if key is None:
                continue
            button = self.overview_cells.get(key)
            if button is None:
                continue
            rec = self.overview_pos_map.get(key)
            self._paint_cell(button, key[0], key[1], rec)

    def _clear_selected_cell(self):
        key = self.overview_selected_key
        self.overview_selected_key = None
        if key is not None:
            button = self.overview_cells.get(key)
            if button is not None:
                rec = self.overview_pos_map.get(key)
                self._paint_cell(button, key[0], key[1], rec)

    def _refresh_filter_options(self, records, box_numbers):
        from lib.custom_fields import get_color_key
        prev_box = self.ov_filter_box.currentData()
        prev_cell = self.ov_filter_cell.currentData()

        self.ov_filter_box.blockSignals(True)
        self.ov_filter_box.clear()
        self.ov_filter_box.addItem(tr("overview.allBoxes"), None)
        for box_num in box_numbers:
            self.ov_filter_box.addItem(t("overview.boxLabel", box=box_num), box_num)
        index = self.ov_filter_box.findData(prev_box)
        self.ov_filter_box.setCurrentIndex(index if index >= 0 else 0)
        self.ov_filter_box.blockSignals(False)

        meta = getattr(self, "_current_meta", {})
        ck = get_color_key(meta)
        values = sorted({str(rec.get(ck)) for rec in records if rec.get(ck)})
        self.ov_filter_cell.blockSignals(True)
        self.ov_filter_cell.clear()
        self.ov_filter_cell.addItem(tr("overview.allCells"), None)
        for val in values:
            self.ov_filter_cell.addItem(val, val)
        index = self.ov_filter_cell.findData(prev_cell)
        self.ov_filter_cell.setCurrentIndex(index if index >= 0 else 0)
        self.ov_filter_cell.blockSignals(False)

    def _apply_filters(self):
        keyword = self.ov_filter_keyword.text().strip().lower()
        selected_box = self.ov_filter_box.currentData()
        selected_cell = self.ov_filter_cell.currentData()
        show_empty = self.ov_filter_show_empty.isChecked()

        if self._overview_view_mode == "table":
            self._apply_filters_table(
                keyword=keyword,
                selected_box=selected_box,
                selected_cell=selected_cell,
            )
            return

        self._apply_filters_grid(
            keyword=keyword,
            selected_box=selected_box,
            selected_cell=selected_cell,
            show_empty=show_empty,
        )

    def _apply_filters_grid(self, keyword, selected_box, selected_cell, show_empty):
        visible_boxes = 0
        visible_slots = 0
        per_box = {box: {"occ": 0, "emp": 0} for box in self.overview_box_groups.keys()}

        for (box_num, position), button in self.overview_cells.items():
            record = self.overview_pos_map.get((box_num, position))
            is_empty = record is None
            match_box = selected_box is None or box_num == selected_box
            match_cell = selected_cell is None or (record and str(button.property("color_key_value") or "") == selected_cell)
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
                live.setText(t("overview.filteredCount", occupied=stat['occ'], empty=stat['emp']))

        if self.overview_selected_key:
            selected_button = self.overview_cells.get(self.overview_selected_key)
            if selected_button and not selected_button.isVisible():
                self._clear_selected_cell()
                self._reset_detail()

        self.ov_status.setText(
            t(
                "overview.filterStatus",
                slots=visible_slots,
                boxes=visible_boxes,
                time=datetime.now().strftime("%H:%M:%S"),
            )
        )

    def _apply_filters_table(self, keyword, selected_box, selected_cell):
        matched_rows = []
        matched_boxes = set()

        for row_data in self._table_rows:
            box_num = row_data.get("box")
            color_value = str(row_data.get("color_value") or "")

            match_box = selected_box is None or box_num == selected_box
            match_cell = selected_cell is None or color_value == selected_cell

            if keyword:
                match_keyword = keyword in str(row_data.get("search_text") or "")
            else:
                match_keyword = True

            if not (match_box and match_cell and match_keyword):
                continue

            matched_rows.append(row_data)
            if box_num is not None:
                matched_boxes.add(box_num)

        self._render_table_rows(matched_rows)
        self.ov_status.setText(
            t(
                "overview.filterStatusTable",
                records=len(matched_rows),
                boxes=len(matched_boxes),
                time=datetime.now().strftime("%H:%M:%S"),
            )
        )

    def on_toggle_filters(self, checked):
        self.ov_filter_advanced_widget.setVisible(bool(checked))
        self.ov_filter_toggle_btn.setText(tr("overview.hideFilters") if checked else tr("overview.moreFilters"))

    def on_clear_filters(self):
        self.ov_filter_keyword.clear()
        self.ov_filter_box.setCurrentIndex(0)
        self.ov_filter_cell.setCurrentIndex(0)
        self.ov_filter_show_empty.setChecked(True)
        if self.ov_filter_toggle_btn.isChecked():
            self.ov_filter_toggle_btn.setChecked(False)
        self._apply_filters()

    def on_cell_clicked(self, box_num, position):
        self.on_cell_hovered(box_num, position, force=True)

    def on_cell_double_clicked(self, box_num, position):
        record = self.overview_pos_map.get((box_num, position))
        self._set_selected_cell(box_num, position)
        self.on_cell_hovered(box_num, position, force=True)

        # Double click should be low-friction: just prefill common forms, no popup menu.
        if record:
            rec_id = int(record.get("id"))
            self.request_prefill_background.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(t("overview.prefillTakeoutAuto", id=rec_id), 2000)
        else:
            self.request_add_prefill_background.emit({
                "box": int(box_num),
                "position": int(position),
            })
            self.status_message.emit(
                t("overview.prefillAddAuto", box=box_num, position=position),
                2000,
            )

    def on_cell_hovered(self, box_num, position, force=False):
        hover_key = (box_num, position)
        if not force and self.overview_hover_key == hover_key:
            return
        button = self.overview_cells.get((box_num, position))
        if button is not None and not button.isVisible():
            return
        record = self.overview_pos_map.get((box_num, position))
        self.overview_hover_key = hover_key
        self._show_detail(box_num, position, record)

    def _reset_detail(self):
        self.overview_hover_key = None
        self.ov_hover_hint.setText(tr("overview.hoverHint"))

    def _show_detail(self, box_num, position, record):
        if not record:
            self.ov_hover_hint.setText(t("overview.previewEmpty", box=box_num, pos=position))
            return

        from lib.custom_fields import get_display_key
        meta = getattr(self, "_current_meta", {})
        dk = get_display_key(meta)
        rec_id = str(record.get("id", "-"))
        dk_val = str(record.get(dk, "-"))
        self.ov_hover_hint.setText(
            t("overview.previewRecord", box=box_num, pos=position, id=rec_id, cell=dk_val, short=dk_val)
        )

    def on_cell_context_menu(self, box_num, position, global_pos):
        record = self.overview_pos_map.get((box_num, position))
        self._set_selected_cell(box_num, position)
        self.on_cell_hovered(box_num, position, force=True)

        menu = QMenu(self)
        act_add = None
        act_thaw = None
        act_move = None
        act_query = None

        if record:
            act_thaw = menu.addAction(tr("operations.thaw"))
            act_move = menu.addAction(tr("operations.move"))
            act_query = menu.addAction(tr("operations.query"))
        else:
            act_add = menu.addAction(tr("operations.add"))

        selected = menu.exec(global_pos)
        if selected is None:
            return

        if selected == act_add:
            self.request_add_prefill.emit({
                "box": int(box_num),
                "position": int(position),
            })
            self.status_message.emit(
                t("overview.prefillAdd", box=box_num, position=position),
                2000,
            )
            return

        if not record:
            return

        rec_id = int(record.get("id"))
        if selected == act_thaw:
            self.request_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(t("overview.prefillThaw", id=rec_id), 2000)
            return
        if selected == act_move:
            self.request_move_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(t("overview.prefillMove", id=rec_id), 2000)
            return
        if selected == act_query:
            self.request_query_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(t("overview.prefillQuery", id=rec_id), 2000)

    def _on_cell_drop(self, from_box, from_pos, to_box, to_pos, record_id):
        if from_box == to_box and from_pos == to_pos:
            return

        record = self.overview_records_by_id.get(record_id)
        label = "-"
        if record:
            from lib.custom_fields import get_display_key
            meta = getattr(self, "_current_meta", {})
            dk = get_display_key(meta)
            label = str(record.get(dk) or "") or "-"

        item = {
            "action": "move",
            "box": from_box,
            "position": from_pos,
            "to_position": to_pos,
            "to_box": to_box if to_box != from_box else None,
            "record_id": record_id,
            "label": label,
            "source": "human",
            "payload": {
                "record_id": record_id,
                "position": from_pos,
                "to_position": to_pos,
                "to_box": to_box if to_box != from_box else None,
                "date_str": date.today().isoformat(),
                "action": "Move",
                "note": "Drag from Overview",
            },
        }

        self.plan_items_requested.emit([item])
        target_desc = f"Box {to_box}:{to_pos}" if to_box != from_box else f"Pos {to_pos}"
        self.status_message.emit(f"Move ID {record_id} to {target_desc} added to Plan.", 2000)
