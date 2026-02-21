"""Grid and cell rendering helpers for OverviewPanel."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QSizePolicy, QVBoxLayout

from app_gui.i18n import t, tr
from app_gui.ui.overview_panel_cell_button import CellButton
from app_gui.ui.theme import cell_empty_style, cell_occupied_style
from app_gui.ui.utils import cell_color
from lib.position_fmt import box_to_display, pos_to_display


def _repaint_all_cells(self):
    """Repaint all cell buttons using cached data."""
    records = getattr(self, "_current_records", [])
    record_map = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        box = rec.get("box")
        pos = rec.get("position")
        if box is not None and pos is not None:
            record_map[(box, pos)] = rec
    for (box_num, position), button in self.overview_cells.items():
        record = record_map.get((box_num, position))
        self._paint_cell(button, box_num, position, record)


def _warm_hover_animation(self):
    """Pre-create hover proxy and animation to eliminate first-hover delay."""
    if self._hover_warmed or not self.overview_cells:
        return
    self._hover_warmed = True

    for button in self.overview_cells.values():
        if isinstance(button, CellButton) and button.isVisible():
            button._ensure_hover_proxy()
            if button._hover_anim is not None:
                button._hover_anim.setDuration(1)
                button._hover_anim.setStartValue(QRect(0, 0, 1, 1))
                button._hover_anim.setEndValue(QRect(0, 0, 1, 1))
                button._hover_anim.start()
                button._hover_anim.stop()
            break


def _rebuild_boxes(self, rows, cols, box_numbers):
    while self.ov_boxes_layout.count():
        item = self.ov_boxes_layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()

    self.overview_cells = {}
    self.overview_box_live_labels = {}
    self.overview_box_groups = {}
    self.overview_selected_key = None
    self._reset_detail()

    layout = getattr(self, "_current_layout", {})
    total_slots = rows * cols
    self._base_cell_size = max(30, min(45, 375 // max(rows, cols)))
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
            button.setProperty("overview_box", box_num)
            button.setProperty("overview_position", position)
            button.installEventFilter(self)

            button.clicked.connect(
                lambda _checked=False, b=box_num, p=position: self.on_cell_clicked(b, p)
            )
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


def _paint_cell(self, button, box_num, position, record):
    from lib.custom_fields import (
        STRUCTURAL_FIELD_KEYS,
        get_color_key,
        get_display_key,
        get_effective_fields,
    )

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
        max_chars = max(4, int(8 * self._zoom_level))
        label = dk_val[:max_chars] if dk_val else display_pos
        color = cell_color(ck_val or None)
        button.setText(label)

        cl = record.get("cell_line")
        tt = [
            f"{tr('overview.tooltipId')}: {record.get('id', '-')}",
            f"{tr('overview.tooltipPos')}: {box_num}:{position}",
        ]
        if cl:
            tt.append(f"{tr('overview.tooltipCellLine')}: {cl}")
        note_value = record.get("note")
        if note_value is not None and str(note_value).strip():
            tt.append(f"{tr('operations.note')}: {note_value}")
        for fdef in get_effective_fields(meta):
            fk = fdef["key"]
            fv = record.get(fk)
            if fv is not None and str(fv):
                tt.append(f"{fdef.get('label', fk)}: {fv}")
        tt.append(f"{tr('overview.tooltipDate')}: {record.get('frozen_at', '-')}")

        button.setToolTip("\n".join(tt))
        button.setStyleSheet(cell_occupied_style(color, is_selected, font_size=fs_occ))
        parts = [
            str(record.get("id", "")),
            str(box_num),
            str(position),
            str(record.get("cell_line") or ""),
            str(record.get("note") or ""),
            str(record.get("frozen_at") or ""),
        ]
        for key, value in record.items():
            if key not in STRUCTURAL_FIELD_KEYS and key != "id":
                parts.append(str(value or ""))
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
