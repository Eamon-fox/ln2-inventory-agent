from datetime import date, datetime
from PySide6.QtCore import Qt, Signal, QEvent, QMimeData, QPoint
from PySide6.QtGui import QDrag, QDropEvent, QDragEnterEvent, QDragMoveEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QScrollArea,
    QSizePolicy, QGroupBox, QMenu
)
from app_gui.ui.utils import build_panel_header, cell_color
from app_gui.ui.theme import (
    cell_occupied_style, 
    cell_empty_style,
    cell_preview_add_style,
    cell_preview_takeout_style,
    cell_preview_move_source_style,
    cell_preview_move_target_style,
)
from app_gui.i18n import tr, t

MIME_TYPE_MOVE = "application/x-ln2-move"

def get_overview_help_text():
    # i18n-backed so it tracks language selection.
    return tr("overview.helpText")

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

        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
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

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addLayout(build_panel_header(self, tr("overview.title"), tr("overview.helpTitle"), get_overview_help_text()))

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
        self.ov_meta_stats.setStyleSheet("color: #64748b;")
        layout.addWidget(self.ov_meta_stats)

        # Action Row
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        refresh_btn = QPushButton(tr("overview.refresh"))
        refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(refresh_btn)

        goto_add_btn = QPushButton(tr("overview.quickAdd"))
        goto_add_btn.clicked.connect(self.request_quick_add.emit)
        action_row.addWidget(goto_add_btn)

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
        self.ov_filter_box.addItem("All boxes", None)
        self.ov_filter_box.currentIndexChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_box)

        self.ov_filter_cell = QComboBox()
        self.ov_filter_cell.addItem("All cells", None)
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

        # Grid Area
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

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
            box_num = obj.property("overview_box")
            position = obj.property("overview_position")
            if box_num is not None and position is not None:
                self.on_cell_hovered(int(box_num), int(position))
        return super().eventFilter(obj, event)

    def refresh(self):
        yaml_path = self.yaml_path_getter()
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
        box_numbers = sorted([int(k) for k in box_stats.keys()], key=int)
        if not box_numbers:
            box_numbers = [1, 2, 3, 4, 5]

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
            self.ov_hover_hint.setText(
                "[EMPTY] No samples yet. Double-click a slot to add your first entry, "
                "or use Quick Start to load demo data."
            )
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

        total_slots = rows * cols
        columns = 3
        for idx, box_num in enumerate(box_numbers):
            group = QGroupBox(t("overview.boxLabel", box=box_num))
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
                button = CellButton(str(position), box_num, position)
                button.setFixedSize(32, 32)
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
                button.setText("ADD")
                button.setStyleSheet(cell_preview_add_style())
            elif key in preview_positions["takeout"]:
                button.setText("OUT")
                button.setStyleSheet(cell_preview_takeout_style())
            elif key in preview_positions["move_source"]:
                orig_record = self.overview_pos_map.get(key)
                label = ""
                if orig_record:
                    label = str(orig_record.get("short_name") or "")[:4]
                button.setText(f"{label}→" if label else "→")
                button.setStyleSheet(cell_preview_move_source_style())
            elif key in preview_positions["move_target"]:
                button.setText("←")
                button.setStyleSheet(cell_preview_move_target_style())
            else:
                self._paint_cell(button, box_num, position, record)

    def _paint_cell(self, button, box_num, position, record):
        is_selected = self.overview_selected_key == (box_num, position)
        if record:
            short = str(record.get("short_name") or "")
            label = short[:6] if short else str(position)
            parent = record.get("parent_cell_line")
            color = cell_color(parent)
            button.setText(label)
            
            # Richer tooltip
            tt = [
                f"ID: {record.get('id', '-')}",
                f"Cell: {record.get('parent_cell_line', '-')}",
                f"Short: {record.get('short_name', '-')}",
                f"Pos: {box_num}:{position}",
                f"Date: {record.get('frozen_at', '-')}",
            ]
            if record.get('plasmid_name'): tt.append(f"Plasmid: {record.get('plasmid_name')}")
            if record.get('note'): tt.append(f"Note: {record.get('note')}")
            
            button.setToolTip("\n".join(tt))
            button.setStyleSheet(cell_occupied_style(color, is_selected))
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
            button.set_record_id(int(record.get("id", 0)))
        else:
            button.setText(str(position))
            button.setToolTip(f"Box {box_num} Position {position}: empty")
            button.setStyleSheet(cell_empty_style(is_selected))
            button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
            button.setProperty("cell_line", "")
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

        cell_lines = sorted({str(rec.get("parent_cell_line")) for rec in records if rec.get("parent_cell_line")})
        self.ov_filter_cell.blockSignals(True)
        self.ov_filter_cell.clear()
        self.ov_filter_cell.addItem(tr("overview.allCells"), None)
        for cell in cell_lines:
            self.ov_filter_cell.addItem(cell, cell)
        index = self.ov_filter_cell.findData(prev_cell)
        self.ov_filter_cell.setCurrentIndex(index if index >= 0 else 0)
        self.ov_filter_cell.blockSignals(False)

    def _apply_filters(self):
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
                live.setText(t("overview.filteredCount", occupied=stat['occ'], empty=stat['emp']))

        if self.overview_selected_key:
            selected_button = self.overview_cells.get(self.overview_selected_key)
            if selected_button and not selected_button.isVisible():
                self._clear_selected_cell()
                self._reset_detail()

        self.ov_status.setText(
            f"Filter matched {visible_slots} slots across {visible_boxes} boxes | {datetime.now().strftime('%H:%M:%S')}"
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
            self.status_message.emit(f"Auto-prefilled Takeout for ID {rec_id}.", 2000)
        else:
            self.request_add_prefill_background.emit({
                "box": int(box_num),
                "position": int(position),
            })
            self.status_message.emit(f"Auto-prefilled Add Entry (Box {box_num} Pos {position}).", 2000)
            self.status_message.emit(f"Auto-prefilled Add Entry (Box {box_num} Pos {position}).", 2000)

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

        rec_id = str(record.get("id", "-"))
        cell = str(record.get("parent_cell_line", "-"))
        short = str(record.get("short_name", "-"))
        frozen = str(record.get("frozen_at", "-"))
        plasmid = record.get("plasmid_name") or record.get("plasmid_id") or "-"
        self.ov_hover_hint.setText(
            t("overview.previewRecord", box=box_num, pos=position, id=rec_id, cell=cell, short=short)
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
            act_thaw = menu.addAction("Thaw / Takeout")
            act_move = menu.addAction("Move")
            act_query = menu.addAction("Query")
        else:
            act_add = menu.addAction("Add Entry")

        selected = menu.exec(global_pos)
        if selected is None:
            return

        if selected == act_add:
            self.request_add_prefill.emit({
                "box": int(box_num),
                "position": int(position),
            })
            self.status_message.emit(f"Prefill Add Entry (Box {box_num} Pos {position})", 2000)
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
            self.status_message.emit(f"Prefill Thaw for ID {rec_id}", 2000)
            return
        if selected == act_move:
            self.request_move_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(f"Prefill Move for ID {rec_id}", 2000)
            return
        if selected == act_query:
            self.request_query_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(f"Query ID {rec_id}", 2000)

    def _on_cell_drop(self, from_box, from_pos, to_box, to_pos, record_id):
        if from_box == to_box and from_pos == to_pos:
            return

        record = self.overview_records_by_id.get(record_id)
        label = "-"
        if record:
            label = record.get("short_name") or record.get("parent_cell_line") or "-"

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
