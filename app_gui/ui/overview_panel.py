from datetime import date, datetime
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QScrollArea,
    QSizePolicy, QGroupBox, QMenu, QApplication
)
from app_gui.ui.utils import cell_color

class CellButton(QPushButton):
    doubleClicked = Signal(int, int) # box, position

    def __init__(self, text, box, pos, parent=None):
        super().__init__(text, parent)
        self.box = box
        self.pos = pos

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.box, self.pos)
        super().mouseDoubleClickEvent(event)

class OverviewPanel(QWidget):
    status_message = Signal(str, int)
    request_prefill = Signal(dict)
    request_quick_add = Signal()
    request_quick_thaw = Signal()
    request_add_prefill = Signal(dict)
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
        self.overview_selected_keys = set()
        self.select_mode = False

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Summary Cards
        summary_row = QHBoxLayout()
        summary_row.setSpacing(6)
        
        self.ov_total_records_value = self._build_card(summary_row, "Total Records")
        self.ov_occupied_value = self._build_card(summary_row, "Occupied")
        self.ov_empty_value = self._build_card(summary_row, "Empty")
        self.ov_rate_value = self._build_card(summary_row, "Occupancy Rate")
        
        layout.addLayout(summary_row)

        # Meta Stats
        self.ov_total_capacity_value = QLabel("-")
        self.ov_ops7_value = QLabel("-")
        self.ov_meta_stats = QLabel("Capacity: - | Ops (7d): -")
        self.ov_meta_stats.setStyleSheet("color: #64748b;")
        layout.addWidget(self.ov_meta_stats)

        # Action Row
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(refresh_btn)

        goto_add_btn = QPushButton("Quick Add")
        goto_add_btn.clicked.connect(self.request_quick_add.emit)
        action_row.addWidget(goto_add_btn)

        goto_thaw_btn = QPushButton("Quick Takeout")
        goto_thaw_btn.clicked.connect(self.request_quick_thaw.emit)
        action_row.addWidget(goto_thaw_btn)

        self.ov_select_btn = QPushButton("Select")
        self.ov_select_btn.setCheckable(True)
        self.ov_select_btn.toggled.connect(self._on_select_mode_toggled)
        action_row.addWidget(self.ov_select_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # Filter Row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel("Search"))

        self.ov_filter_keyword = QLineEdit()
        self.ov_filter_keyword.setPlaceholderText("ID / short / cell / plasmid / note")
        self.ov_filter_keyword.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.ov_filter_keyword, 2)

        self.ov_filter_toggle_btn = QPushButton("More Filters")
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

        self.ov_filter_show_empty = QCheckBox("Show Empty")
        self.ov_filter_show_empty.setChecked(True)
        self.ov_filter_show_empty.stateChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_show_empty)

        clear_filter_btn = QPushButton("Clear Filter")
        clear_filter_btn.clicked.connect(self.on_clear_filters)
        advanced_filter_row.addWidget(clear_filter_btn)
        advanced_filter_row.addStretch()

        self.ov_filter_advanced_widget = QWidget()
        self.ov_filter_advanced_widget.setLayout(advanced_filter_row)
        self.ov_filter_advanced_widget.setVisible(False)
        layout.addWidget(self.ov_filter_advanced_widget)

        self.ov_status = QLabel("Overview status")
        layout.addWidget(self.ov_status)

        self.ov_hover_hint = QLabel("Hover a slot to preview details.")
        self.ov_hover_hint.setStyleSheet("color: #94a3b8; font-weight: bold;")
        self.ov_hover_hint.setWordWrap(True)
        layout.addWidget(self.ov_hover_hint)

        # Selection Action Bar (hidden by default)
        sel_bar_layout = QHBoxLayout()
        sel_bar_layout.setSpacing(6)
        self.ov_sel_count = QLabel("0 selected")
        self.ov_sel_count.setStyleSheet("font-weight: bold;")
        sel_bar_layout.addWidget(self.ov_sel_count)
        for action_name in ("Takeout", "Thaw", "Discard"):
            btn = QPushButton(action_name)
            btn.clicked.connect(lambda _checked=False, a=action_name: self._on_quick_action(a))
            sel_bar_layout.addWidget(btn)
        sel_clear_btn = QPushButton("Clear")
        sel_clear_btn.clicked.connect(self._clear_all_selections)
        sel_bar_layout.addWidget(sel_clear_btn)
        sel_bar_layout.addStretch()
        self.ov_selection_bar = QWidget()
        self.ov_selection_bar.setLayout(sel_bar_layout)
        self.ov_selection_bar.setVisible(False)
        layout.addWidget(self.ov_selection_bar)

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
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        value_label = QLabel("-")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("font-size: 16px; font-weight: 700;")
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
            self.ov_status.setText(f"Failed to load overview: {stats_response.get('message', 'unknown error')}")
            self.overview_records_by_id = {}
            self.overview_selected_key = None
            self.overview_selected_keys.clear()
            self._update_selection_bar()
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

        if timeline_response.get("ok"):
            ops7 = timeline_response.get("result", {}).get("summary", {}).get("total_ops", 0)
            self.ov_ops7_value.setText(str(ops7))
        else:
            self.ov_ops7_value.setText("N/A")

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
            self._paint_cell(button, box_num, position, rec)

        self._refresh_filter_options(records, box_numbers)
        self._apply_filters()

        self.ov_status.setText(
            f"Loaded {len(records)} records | {datetime.now().strftime('%H:%M:%S')}"
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
        self.overview_selected_keys.clear()
        self._update_selection_bar()
        self._reset_detail()

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
                self.overview_cells[(box_num, position)] = button
                grid.addWidget(button, r, c)

            group_layout.addLayout(grid)
            self.ov_boxes_layout.addWidget(group, idx // columns, idx % columns)
            self.overview_box_groups[box_num] = group

        self.overview_shape = (rows, cols, tuple(box_numbers))

    def _paint_cell(self, button, box_num, position, record):
        is_selected = (self.overview_selected_key == (box_num, position)
                       or (box_num, position) in self.overview_selected_keys)
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
            button.setStyleSheet(
                "QPushButton {"
                f"background-color: {color};"
                "color: white;"
                f"border: {'2px' if is_selected else '1px'} solid {'#16a34a' if is_selected else '#1f2937'};"
                "border-radius: 4px;"
                "font-size: 10px;"
                "font-weight: 700;"
                "padding: 1px;"
                "}"
                f"QPushButton:hover {{ border: 2px solid {'#16a34a' if is_selected else '#f8fafc'}; }}"
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
                "color: #94a3b8;"
                f"border: {'2px' if is_selected else '1px'} solid {'#16a34a' if is_selected else '#1e293b'};"
                "border-radius: 4px;"
                "font-size: 9px;"
                "padding: 1px;"
                "}"
                f"QPushButton:hover {{ border: 2px solid {'#16a34a' if is_selected else '#38bdf8'}; background-color: #1e293b; }}"
            )
            button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
            button.setProperty("cell_line", "")
            button.setProperty("is_empty", True)

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
        if self.overview_selected_keys:
            self._clear_all_selections()

    def _refresh_filter_options(self, records, box_numbers):
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
                live.setText(f"Filtered: Occupied {stat['occ']} | Empty {stat['emp']}")

        if self.overview_selected_key:
            selected_button = self.overview_cells.get(self.overview_selected_key)
            if selected_button and not selected_button.isVisible():
                self._clear_selected_cell()
                self._reset_detail()

        # Remove hidden cells from multi-select
        hidden_keys = {k for k in self.overview_selected_keys
                       if not self.overview_cells.get(k, QPushButton()).isVisible()}
        if hidden_keys:
            self.overview_selected_keys -= hidden_keys
            self._update_selection_bar()

        self.ov_status.setText(
            f"Filter matched {visible_slots} slots across {visible_boxes} boxes | {datetime.now().strftime('%H:%M:%S')}"
        )

    def on_toggle_filters(self, checked):
        self.ov_filter_advanced_widget.setVisible(bool(checked))
        self.ov_filter_toggle_btn.setText("Hide Filters" if checked else "More Filters")

    def on_clear_filters(self):
        self.ov_filter_keyword.clear()
        self.ov_filter_box.setCurrentIndex(0)
        self.ov_filter_cell.setCurrentIndex(0)
        self.ov_filter_show_empty.setChecked(True)
        if self.ov_filter_toggle_btn.isChecked():
            self.ov_filter_toggle_btn.setChecked(False)
        self._apply_filters()

    def on_cell_clicked(self, box_num, position):
        if self.select_mode:
            self._toggle_cell_selection(box_num, position)
        else:
            self.on_cell_hovered(box_num, position, force=True)

    def on_cell_double_clicked(self, box_num, position):
        record = self.overview_pos_map.get((box_num, position))
        if record:
            self._set_selected_cell(box_num, position)
            self.on_cell_hovered(box_num, position, force=True)
            # Prefill thaw
            rec_id = int(record.get("id"))
            self.request_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })
            self.status_message.emit(f"Double-click: Prefill Thaw for ID {rec_id}", 2000)
        else:
            self._set_selected_cell(box_num, position)
            self.on_cell_hovered(box_num, position, force=True)
            self.request_add_prefill.emit({
                "box": int(box_num),
                "position": int(position),
            })
            self.status_message.emit(f"Double-click: Prefill Add Entry (Box {box_num} Pos {position})", 2000)

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
        self.ov_hover_hint.setText("Hover a slot to preview details.")

    def _show_detail(self, box_num, position, record):
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

    def on_cell_context_menu(self, box_num, position, global_pos):
        record = self.overview_pos_map.get((box_num, position))
        self.on_cell_hovered(box_num, position, force=True)

        menu = QMenu(self)
        act_copy_loc = menu.addAction(f"Copy Location {box_num}:{position}")
        act_copy_id = None
        act_prefill = None
        if record:
            act_copy_id = menu.addAction(f"Copy ID {record.get('id')}")
            act_prefill = menu.addAction("Prefill to Thaw")
        else:
            # If empty, maybe add quick add shortcut?
            pass

        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected == act_copy_loc:
            QApplication.clipboard().setText(f"{box_num}:{position}")
            self.status_message.emit(f"Copied location {box_num}:{position}", 2000)
            return
        if act_copy_id is not None and selected == act_copy_id:
            rid = str(record.get("id", "")).strip()
            QApplication.clipboard().setText(rid)
            self.status_message.emit(f"Copied ID {rid}", 2000)
            return
        if act_prefill is not None and selected == act_prefill:
            self._set_selected_cell(box_num, position)
            rec_id = int(record.get("id"))
            self.request_prefill.emit({
                "box": int(box_num),
                "position": int(position),
                "record_id": rec_id,
            })

    # --- Multi-select ---

    def _on_select_mode_toggled(self, checked):
        self.select_mode = checked
        self.ov_select_btn.setText("Exit Select" if checked else "Select")
        if checked:
            self._clear_selected_cell()
        else:
            self._clear_all_selections()

    def _toggle_cell_selection(self, box_num, position):
        key = (box_num, position)
        record = self.overview_pos_map.get(key)
        if not record:
            return
        if key in self.overview_selected_keys:
            self.overview_selected_keys.discard(key)
        else:
            self.overview_selected_keys.add(key)
        button = self.overview_cells.get(key)
        if button is not None:
            self._paint_cell(button, box_num, position, record)
        self._update_selection_bar()

    def _clear_all_selections(self):
        old_keys = list(self.overview_selected_keys)
        self.overview_selected_keys.clear()
        for key in old_keys:
            button = self.overview_cells.get(key)
            if button is not None:
                rec = self.overview_pos_map.get(key)
                self._paint_cell(button, key[0], key[1], rec)
        self._update_selection_bar()

    def _update_selection_bar(self):
        n = len(self.overview_selected_keys)
        self.ov_sel_count.setText(f"{n} selected")
        self.ov_selection_bar.setVisible(n > 0)

    def _on_quick_action(self, action_name):
        items = []
        for key in sorted(self.overview_selected_keys):
            box_num, position = key
            record = self.overview_pos_map.get(key)
            if not record:
                continue
            rec_id = int(record.get("id"))
            label = record.get("short_name") or record.get("parent_cell_line") or "-"
            items.append({
                "action": action_name.lower(),
                "box": box_num,
                "position": position,
                "record_id": rec_id,
                "label": label,
                "source": "human",
                "payload": {
                    "record_id": rec_id,
                    "position": position,
                    "date_str": date.today().isoformat(),
                    "action": action_name,
                    "note": f"Quick {action_name.lower()} from Overview",
                },
            })

        if not items:
            self.status_message.emit("No valid records selected.", 2000)
            return

        self._clear_all_selections()
        self.plan_items_requested.emit(items)
        self.status_message.emit(f"Added {len(items)} item(s) to Plan.", 2000)
