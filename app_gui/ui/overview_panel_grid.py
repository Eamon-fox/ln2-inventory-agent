"""Grid and cell rendering helpers for OverviewPanel."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QSizePolicy, QVBoxLayout

from app_gui.i18n import t, tr
from app_gui.ui.overview_panel_cell_button import CellButton
from app_gui.ui.theme import cell_empty_style, cell_occupied_style
from app_gui.ui.utils import cell_color
from lib.position_fmt import box_to_display, pos_to_display

_BOX_TAG_TITLE_MAX_CHARS = 18
_OCCUPIED_TEXT_SHOW_MIN_CELL_PX = 52


def _set_button_font_size(button, pixel_size):
    """Set font pixel size on a button without touching the stylesheet."""
    font = button.font()
    if font.pixelSize() != pixel_size:
        font.setPixelSize(pixel_size)
        button.setFont(font)


def _should_show_occupied_label(button, label_text):
    text = str(label_text or "").strip()
    if not text:
        return False

    side = min(int(button.width() or 0), int(button.height() or 0))
    return side >= _OCCUPIED_TEXT_SHOW_MIN_CELL_PX


def _update_cell_label_visibility(self, button):
    if button is None:
        return

    label_text = str(button.property("display_label_full") or "")
    is_empty = bool(button.property("is_empty"))

    if is_empty:
        target_text = label_text
    else:
        target_text = label_text if _should_show_occupied_label(button, label_text) else ""

    if button.text() != target_text:
        button.setText(target_text)


def _normalize_positive_int(raw):
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


def _freeze_signature_value(value):
    if isinstance(value, dict):
        return tuple(
            (str(key), _freeze_signature_value(val))
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_signature_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_signature_value(item) for item in value))
    return value


def _build_cell_render_signature(self, box_num, position, record):
    from lib.custom_fields import get_color_key, get_display_key

    layout = getattr(self, "_current_layout", {}) or {}
    meta = getattr(self, "_current_meta", {}) or {}
    marker_map = getattr(self, "_operation_markers", {}) or {}
    marker = marker_map.get((box_num, position)) if isinstance(marker_map, dict) else None
    marker_type = str((marker or {}).get("type") or "").strip().lower()
    move_id = (marker or {}).get("move_id")
    selected = bool(getattr(self, "overview_selected_key", None) == (box_num, position))
    # NOTE: zoom / fonts are intentionally excluded from the signature.
    # Font size is set via QFont.setPixelSize() in _apply_zoom(), not in
    # the stylesheet, so zoom changes should NOT invalidate cell styles.
    display_key = str(get_display_key(meta) or "")
    color_key = str(get_color_key(meta) or "")
    layout_signature = (
        int(layout.get("rows", 9) or 9),
        int(layout.get("cols", 9) or 9),
        str(layout.get("indexing", "") or ""),
    )
    record_signature = _freeze_signature_value(record) if isinstance(record, dict) else None
    return (
        box_num,
        position,
        layout_signature,
        display_key,
        color_key,
        selected,
        marker_type,
        move_id,
        record_signature,
    )


def _marker_border_color(marker_type):
    marker = str(marker_type or "").strip().lower()
    if marker == "add":
        return "#22c55e"
    if marker == "takeout":
        return "#ef4444"
    if marker == "edit":
        return "#06b6d4"
    if marker in {"move-source", "move-target"}:
        return "#63b3ff"
    return ""


def _marker_css_overlay(marker_type, *, is_selected=False):
    if bool(is_selected):
        # Keep selected state visually dominant when plan markers coexist.
        return ""
    color = _marker_border_color(marker_type)
    if not color:
        return ""
    return (
        "\n"
        "QPushButton {\n"
        f"    border: 2px solid {color};\n"
        "}\n"
        "QPushButton:hover {\n"
        f"    border: 2px solid {color};\n"
        "}\n"
    )


def _get_box_tag(layout, box_num):
    box_tags = (layout or {}).get("box_tags")
    if not isinstance(box_tags, dict):
        return ""
    raw_value = box_tags.get(str(box_num))
    if raw_value is None:
        return ""
    text = str(raw_value)
    if "\n" in text or "\r" in text:
        text = text.replace("\r", " ").replace("\n", " ")
    return text.strip()


def _truncate_box_tag_for_title(tag_text, max_chars=_BOX_TAG_TITLE_MAX_CHARS):
    text = str(tag_text or "").strip()
    limit = max(1, int(max_chars or 1))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _format_box_group_title(box_num, layout):
    box_label = box_to_display(box_num, layout)
    title = t("overview.boxLabel", box=box_label)
    box_tag = _get_box_tag(layout, box_num)
    if not box_tag:
        return title
    return f"{title} | {_truncate_box_tag_for_title(box_tag)}"


def _format_box_group_tooltip(box_num, layout):
    box_label = box_to_display(box_num, layout)
    title = t("overview.boxLabel", box=box_label)
    box_tag = _get_box_tag(layout, box_num)
    if not box_tag:
        return title
    return f"{title} | {box_tag}"


def _build_operation_marker_map(plan_items):
    marker_map = {}
    move_counter = 1
    for item in list(plan_items or []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip().lower()
        box = _normalize_positive_int(item.get("box"))
        pos = _normalize_positive_int(item.get("position"))
        if box is None or pos is None:
            continue

        if action == "add":
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
            add_positions = []
            for raw_pos in positions:
                normalized_pos = _normalize_positive_int(raw_pos)
                if normalized_pos is not None:
                    add_positions.append(normalized_pos)
            if not add_positions:
                add_positions = [pos]
            for add_pos in add_positions:
                marker_map[(box, add_pos)] = {"type": "add"}
            continue

        if action == "takeout":
            marker_map[(box, pos)] = {"type": "takeout"}
            continue

        if action == "edit":
            marker_map[(box, pos)] = {"type": "edit"}
            continue

        if action != "move":
            continue

        move_id = move_counter
        move_counter += 1
        marker_map[(box, pos)] = {"type": "move-source", "move_id": move_id}

        to_box = _normalize_positive_int(item.get("to_box")) or box
        to_pos = _normalize_positive_int(item.get("to_position"))
        if to_pos is not None:
            marker_map[(to_box, to_pos)] = {"type": "move-target", "move_id": move_id}

    return marker_map


def _set_plan_store_ref(self, plan_store):
    self._plan_store_ref = plan_store
    self._on_plan_store_changed()


def _set_plan_markers_from_items(self, plan_items):
    self._operation_markers = _build_operation_marker_map(plan_items)
    if self.overview_cells:
        self._repaint_all_cells()


def _on_plan_store_changed(self):
    plan_items = []
    store = getattr(self, "_plan_store_ref", None)
    if store is not None and hasattr(store, "list_items"):
        try:
            plan_items = store.list_items()
        except Exception:
            plan_items = []
    self._set_plan_markers_from_items(plan_items)


def _repaint_all_cells(self):
    """Repaint all cell buttons using cached data.

    Uses render-signature caching (same as refresh()) to skip cells
    whose visual state has not changed, avoiding expensive setStyleSheet
    calls on every plan-store mutation.
    """
    record_map = {}
    cached_map = getattr(self, "overview_pos_map", None)
    if isinstance(cached_map, dict) and cached_map:
        record_map = cached_map
    else:
        records = getattr(self, "_current_records", [])
        for rec in records:
            if not isinstance(rec, dict):
                continue
            box = _normalize_positive_int(rec.get("box"))
            pos = _normalize_positive_int(rec.get("position"))
            if box is not None and pos is not None:
                record_map[(box, pos)] = rec

    signatures = getattr(self, "_cell_render_signatures", None)
    if not isinstance(signatures, dict):
        signatures = {}
        self._cell_render_signatures = signatures

    for (box_num, position), button in self.overview_cells.items():
        record = record_map.get((box_num, position))
        sig = _build_cell_render_signature(self, box_num, position, record)
        if signatures.get((box_num, position)) == sig:
            continue
        self._paint_cell(button, box_num, position, record)


def _update_box_titles(self, box_numbers):
    layout = getattr(self, "_current_layout", {}) or {}
    for box_num in list(box_numbers or []):
        group = self.overview_box_groups.get(box_num)
        if group is None:
            continue
        group.setTitle(_format_box_group_title(box_num, layout))
        group.setToolTip(_format_box_group_tooltip(box_num, layout))


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
    self._cell_render_signatures = {}
    self._reset_detail()

    layout = getattr(self, "_current_layout", {})
    total_slots = rows * cols
    self._base_cell_size = max(30, min(45, 375 // max(rows, cols)))
    cell_size = max(12, int(self._base_cell_size * self._zoom_level))
    columns = 3
    for idx, box_num in enumerate(box_numbers):
        group = QGroupBox(_format_box_group_title(box_num, layout))
        group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        group.setToolTip(_format_box_group_tooltip(box_num, layout))
        group.setContextMenuPolicy(Qt.CustomContextMenu)
        group.customContextMenuRequested.connect(
            lambda point, b=box_num, grp=group: self.on_box_context_menu(
                b,
                grp.mapToGlobal(point),
            )
        )
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
            button.setProperty("position_display_text", display_text)
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
        display_label = dk_val if dk_val else display_pos
        color = cell_color(ck_val or None)
        _set_button_font_size(button, fs_occ)
        button.setProperty("display_label_full", display_label)
        button.setProperty("is_empty", False)
        _update_cell_label_visibility(self, button)

        tt = [
            f"{tr('overview.tooltipId')}: {record.get('id', '-')}",
            f"{tr('overview.tooltipPos')}: {box_num}:{position}",
        ]
        field_defs = get_effective_fields(meta)
        field_label_map = {
            str(fdef.get("key") or ""): str(fdef.get("label") or fdef.get("key") or "")
            for fdef in field_defs
            if isinstance(fdef, dict)
        }
        if dk_val:
            tt.append(f"{field_label_map.get(dk, dk)}: {dk_val}")
        if ck_val and ck != dk:
            tt.append(f"{field_label_map.get(ck, ck)}: {ck_val}")
        for fdef in field_defs:
            fk = fdef["key"]
            if fk in {dk, ck}:
                continue
            fv = record.get(fk)
            if fv is not None and str(fv).strip():
                tt.append(f"{fdef.get('label', fk)}: {fv}")
        tt.append(f"{tr('overview.tooltipDate')}: {record.get('frozen_at', '-')}")

        button.setToolTip("\n".join(tt))
        base_style = cell_occupied_style(color, is_selected)
        button.setStyleSheet(base_style)
        parts = [
            str(record.get("id", "")),
            str(box_num),
            str(position),
            str(record.get("frozen_at") or ""),
        ]
        for key, value in record.items():
            if key not in STRUCTURAL_FIELD_KEYS and key != "id":
                parts.append(str(value or ""))
        button.setProperty("search_text", " ".join(parts).lower())
        button.setProperty("display_key_value", dk_val)
        button.setProperty("color_key_value", ck_val)
        button.set_record_id(int(record.get("id", 0)))
    else:
        _set_button_font_size(button, fs_empty)
        button.setProperty("display_label_full", display_pos)
        button.setProperty("is_empty", True)
        _update_cell_label_visibility(self, button)
        button.setToolTip(t("overview.emptyCellTooltip", box=box_num, position=position))
        base_style = cell_empty_style(is_selected)
        button.setStyleSheet(base_style)
        button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
        button.setProperty("color_key_value", "")
        button.set_record_id(None)

    marker_map = getattr(self, "_operation_markers", {}) or {}
    marker = marker_map.get((box_num, position)) if isinstance(marker_map, dict) else None
    marker_type = str((marker or {}).get("type") or "").strip().lower()
    move_id = (marker or {}).get("move_id")
    if marker_type:
        button.setStyleSheet(
            (button.styleSheet() or "") + _marker_css_overlay(marker_type, is_selected=is_selected)
        )

    if hasattr(button, "set_operation_marker"):
        button.set_operation_marker(marker_type if marker_type else None, move_id if marker_type else None)

    signatures = getattr(self, "_cell_render_signatures", None)
    if isinstance(signatures, dict):
        signatures[(box_num, position)] = _build_cell_render_signature(self, box_num, position, record)


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
