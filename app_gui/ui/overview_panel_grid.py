"""Grid and cell rendering helpers for OverviewPanel."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QSizePolicy, QVBoxLayout

from app_gui.i18n import t, tr
from app_gui.ui.overview_panel_cell_button import CellButton
from app_gui.ui.theme import SPACE_1, SPACE_2, cell_empty_style, cell_occupied_style, resolve_theme_token
from app_gui.ui.utils import cell_color
from lib.position_fmt import (
    box_tag_text,
    box_to_display,
    format_box_position_compact,
    pos_to_display,
    position_display_text,
)

_BOX_TAG_TITLE_MAX_CHARS = 18
_OCCUPIED_TEXT_SHOW_MIN_CELL_PX = 52
_CELL_TEXT_MODE_DEFAULT = "default"
_CELL_TEXT_MODE_WRAPPED = "wrapped"
_SELECTION_EDGE_ORDER = ("top", "right", "bottom", "left")


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
    position_label = str(button.property("position_label") or "")

    if is_empty:
        target_text = label_text
    else:
        target_text = label_text if _should_show_occupied_label(button, label_text) else str(button.property("position_label") or "")

    target_mode = _CELL_TEXT_MODE_DEFAULT
    if not is_empty and target_text == label_text and label_text and label_text != position_label:
        target_mode = _CELL_TEXT_MODE_WRAPPED
    if hasattr(button, "set_text_display_mode"):
        button.set_text_display_mode(target_mode)
    else:
        button.setProperty("cell_text_mode", target_mode)

    if button.text() != target_text:
        button.setText(target_text)
    elif target_mode == _CELL_TEXT_MODE_WRAPPED:
        button.update()


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


def _normalize_cell_key(raw_key):
    if not isinstance(raw_key, (list, tuple)) or len(raw_key) != 2:
        return None
    box_num = _normalize_positive_int(raw_key[0])
    position = _normalize_positive_int(raw_key[1])
    if box_num is None or position is None:
        return None
    return box_num, position


def _cell_is_empty_slot(self, box_num, position, *, require_visible=False):
    key = _normalize_cell_key((box_num, position))
    if key is None:
        return False

    button = self.overview_cells.get(key)
    if not _is_navigable_cell_button(button):
        return False
    if require_visible and button.isHidden():
        return False
    return self.overview_pos_map.get(key) is None


def _is_cell_selected(self, box_num, position):
    key = _normalize_cell_key((box_num, position))
    if key is None:
        return False

    empty_keys = set(getattr(self, "overview_empty_multi_selected_keys", set()) or set())
    if key in empty_keys:
        return True

    if getattr(self, "overview_selected_key", None) != key:
        return False

    if self.overview_pos_map.get(key) is not None:
        return True
    return not empty_keys


def _is_active_selected_cell(self, box_num, position):
    key = _normalize_cell_key((box_num, position))
    if key is None:
        return False
    return bool(getattr(self, "overview_selected_key", None) == key and _is_cell_selected(self, key[0], key[1]))


def _selection_edge_mask(self, box_num, position):
    key = _normalize_cell_key((box_num, position))
    if key is None or key not in set(getattr(self, "overview_empty_multi_selected_keys", set()) or set()):
        if _is_cell_selected(self, box_num, position):
            return _SELECTION_EDGE_ORDER
        return ()

    rows, cols = _grid_dimensions(self)
    row = (int(key[1]) - 1) // cols
    col = (int(key[1]) - 1) % cols
    offsets = {
        "top": (-1, 0),
        "right": (0, 1),
        "bottom": (1, 0),
        "left": (0, -1),
    }
    edges = []
    selected_keys = set(getattr(self, "overview_empty_multi_selected_keys", set()) or set())
    for edge_name in _SELECTION_EDGE_ORDER:
        dr, dc = offsets[edge_name]
        neighbor_row = row + dr
        neighbor_col = col + dc
        if neighbor_row < 0 or neighbor_col < 0 or neighbor_row >= rows or neighbor_col >= cols:
            edges.append(edge_name)
            continue
        neighbor_position = neighbor_row * cols + neighbor_col + 1
        neighbor_key = (int(key[0]), int(neighbor_position))
        if neighbor_key not in selected_keys:
            edges.append(edge_name)
    return tuple(edges)


def _selected_empty_keys_for_box(self, box_num=None):
    selected_keys = []
    for raw_key in set(getattr(self, "overview_empty_multi_selected_keys", set()) or set()):
        key = _normalize_cell_key(raw_key)
        if key is not None:
            selected_keys.append(key)
    selected_keys.sort()
    results = []
    box_filter = _normalize_positive_int(box_num) if box_num is not None else None
    for key in selected_keys:
        if key is None:
            continue
        if box_filter is not None and key[0] != box_filter:
            continue
        if not _cell_is_empty_slot(self, key[0], key[1]):
            continue
        results.append(key)
    return results


def _set_empty_multi_selection(self, keys, *, anchor_key=None, active_key=None):
    old_keys = set(getattr(self, "overview_empty_multi_selected_keys", set()) or set())
    old_active_key = getattr(self, "overview_selected_key", None)

    normalized_keys = []
    seen = set()
    box_scope = None
    for raw_key in list(keys or []):
        key = _normalize_cell_key(raw_key)
        if key is None:
            continue
        if box_scope is None:
            box_scope = key[0]
        if key[0] != box_scope:
            continue
        if not _cell_is_empty_slot(self, key[0], key[1]):
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized_keys.append(key)

    normalized_keys = sorted(normalized_keys)
    normalized_key_set = set(normalized_keys)

    resolved_active_key = _normalize_cell_key(active_key)
    if resolved_active_key not in normalized_key_set:
        if old_active_key in normalized_key_set:
            resolved_active_key = old_active_key
        elif normalized_keys:
            resolved_active_key = normalized_keys[-1]
        else:
            resolved_active_key = None

    resolved_anchor_key = _normalize_cell_key(anchor_key)
    if resolved_anchor_key not in normalized_key_set:
        if getattr(self, "_overview_selection_anchor_key", None) in normalized_key_set:
            resolved_anchor_key = getattr(self, "_overview_selection_anchor_key", None)
        elif resolved_active_key in normalized_key_set:
            resolved_anchor_key = resolved_active_key
        elif normalized_keys:
            resolved_anchor_key = normalized_keys[0]
        else:
            resolved_anchor_key = None

    self.overview_empty_multi_selected_keys = normalized_key_set
    self._overview_selection_anchor_key = resolved_anchor_key
    self.overview_selected_key = resolved_active_key

    for key in old_keys | normalized_key_set | {old_active_key, resolved_active_key}:
        normalized_key = _normalize_cell_key(key)
        if normalized_key is None:
            continue
        button = self.overview_cells.get(normalized_key)
        if button is None:
            continue
        record = self.overview_pos_map.get(normalized_key)
        self._paint_cell(button, normalized_key[0], normalized_key[1], record)


def _clear_empty_multi_selection(self, *, clear_anchor=True, clear_active=False):
    old_keys = set(getattr(self, "overview_empty_multi_selected_keys", set()) or set())
    old_active_key = getattr(self, "overview_selected_key", None)

    self.overview_empty_multi_selected_keys = set()
    if clear_anchor:
        self._overview_selection_anchor_key = None
    if clear_active:
        self.overview_selected_key = None

    repaint_keys = set(old_keys)
    if clear_active:
        repaint_keys.add(old_active_key)
    for key in repaint_keys:
        normalized_key = _normalize_cell_key(key)
        if normalized_key is None:
            continue
        button = self.overview_cells.get(normalized_key)
        if button is None:
            continue
        record = self.overview_pos_map.get(normalized_key)
        self._paint_cell(button, normalized_key[0], normalized_key[1], record)


def _prune_empty_multi_selection(self):
    valid_keys = _selected_empty_keys_for_box(self)
    if valid_keys:
        _set_empty_multi_selection(self, valid_keys)
        return

    if getattr(self, "overview_empty_multi_selected_keys", None):
        _clear_empty_multi_selection(self, clear_anchor=True, clear_active=False)

    anchor_key = _normalize_cell_key(getattr(self, "_overview_selection_anchor_key", None))
    if anchor_key is not None and not _cell_is_empty_slot(self, anchor_key[0], anchor_key[1]):
        self._overview_selection_anchor_key = None


def _build_cell_render_signature(self, box_num, position, record):
    from lib.custom_fields import get_color_key, get_display_key

    layout = getattr(self, "_current_layout", {}) or {}
    meta = getattr(self, "_current_meta", {}) or {}
    current_records = getattr(self, "_current_records", []) or []
    marker_map = getattr(self, "_operation_markers", {}) or {}
    marker = marker_map.get((box_num, position)) if isinstance(marker_map, dict) else None
    marker_type = str((marker or {}).get("type") or "").strip().lower()
    move_id = (marker or {}).get("move_id")
    marker_preview = str((marker or {}).get("preview_label") or "")
    selected = bool(_is_cell_selected(self, box_num, position))
    active_selected = bool(_is_active_selected_cell(self, box_num, position))
    selection_edges = tuple(_selection_edge_mask(self, box_num, position))
    # NOTE: zoom / fonts are intentionally excluded from the signature.
    # Font size is set via QFont.setPixelSize() in _apply_zoom(), not in
    # the stylesheet, so zoom changes should NOT invalidate cell styles.
    display_key = str(get_display_key(meta, inventory=current_records) or "")
    color_key = str(get_color_key(meta, inventory=current_records) or "")
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
        active_selected,
        selection_edges,
        marker_type,
        move_id,
        marker_preview,
        record_signature,
    )


def _marker_border_color(marker_type):
    marker = str(marker_type or "").strip().lower()
    if marker == "add":
        return resolve_theme_token("marker-add", fallback="#22c55e")
    if marker == "takeout":
        return resolve_theme_token("marker-takeout", fallback="#ef4444")
    if marker == "edit":
        return resolve_theme_token("marker-edit", fallback="#06b6d4")
    if marker in {"move-source", "move-target"}:
        return resolve_theme_token("marker-move", fallback="#63b3ff")
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
    return box_tag_text(box_num, layout)


def _truncate_box_tag_for_title(tag_text, max_chars=_BOX_TAG_TITLE_MAX_CHARS):
    text = str(tag_text or "").strip()
    limit = max(1, int(max_chars or 1))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _format_box_group_title(box_num, layout):
    box_label = box_to_display(box_num, layout)
    title = t("overview.boxLabel", box=box_label)
    tag_text = _get_box_tag(layout, box_num)
    if not tag_text:
        return title
    return f"{title} | {_truncate_box_tag_for_title(tag_text)}"


def _format_box_group_tooltip(box_num, layout):
    box_label = box_to_display(box_num, layout)
    title = t("overview.boxLabel", box=box_label)
    tag_text = _get_box_tag(layout, box_num)
    if not tag_text:
        return title
    return f"{title} | {tag_text}"


def _build_operation_marker_map(plan_items, *, display_key=None):
    marker_map = {}
    move_counter = 1
    display_key_name = str(display_key or "").strip()
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
            preview_label = ""
            if display_key_name:
                fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
                raw_value = fields.get(display_key_name) if isinstance(fields, dict) else None
                preview_label = str(raw_value).strip() if raw_value is not None else ""
            for add_pos in add_positions:
                marker = {"type": "add"}
                if preview_label:
                    marker["preview_label"] = preview_label
                marker_map[(box, add_pos)] = marker
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
    from lib.custom_fields import get_display_key

    meta = getattr(self, "_current_meta", {}) or {}
    inventory = getattr(self, "_current_records", []) or []
    display_key = str(get_display_key(meta, inventory=inventory) or "")
    self._operation_markers = _build_operation_marker_map(plan_items, display_key=display_key)
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
    self.overview_empty_multi_selected_keys = set()
    self._overview_selection_anchor_key = None
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
        group_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        group_layout.setSpacing(SPACE_1)

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
                lambda _checked=False, b=box_num, p=position, btn=button: self.on_cell_clicked(
                    b,
                    p,
                    modifiers=btn.last_click_modifiers(),
                )
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

    is_selected = _is_cell_selected(self, box_num, position)
    layout = getattr(self, "_current_layout", {})
    meta = getattr(self, "_current_meta", {})
    current_records = getattr(self, "_current_records", []) or []
    display_pos = pos_to_display(position, layout)
    fs_occ, fs_empty = getattr(self, "_current_font_sizes", (9, 8))
    if record:
        inventory = current_records or [record]
        dk = get_display_key(meta, inventory=inventory)
        ck = get_color_key(meta, inventory=inventory)
        dk_val = str(record.get(dk) or "")
        ck_val = str(record.get(ck) or "")
        display_label = dk_val if dk_val else display_pos
        color = cell_color(ck_val or None)
        _set_button_font_size(button, fs_occ)
        button.setProperty("display_label_full", display_label)
        button.setProperty("position_label", display_pos)
        button.setProperty("is_empty", False)
        _update_cell_label_visibility(self, button)

        compact_location = format_box_position_compact(box_num, position, layout=layout)
        tt = [
            f"{tr('overview.tooltipId')}: {record.get('id', '-')}",
            f"{tr('overview.tooltipPos')}: {compact_location}",
        ]
        field_defs = get_effective_fields(meta, inventory=inventory)
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
        button.setProperty("cell_color", color)
        parts = [
            str(record.get("id", "")),
            str(box_num),
            str(position),
            compact_location,
            display_pos,
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
        marker_map = getattr(self, "_operation_markers", {}) or {}
        marker_for_empty = marker_map.get((box_num, position)) if isinstance(marker_map, dict) else None
        pending_preview = ""
        if isinstance(marker_for_empty, dict) and str(marker_for_empty.get("type") or "").strip().lower() == "add":
            pending_preview = str(marker_for_empty.get("preview_label") or "").strip()

        _set_button_font_size(button, fs_occ if pending_preview else fs_empty)
        display_label = pending_preview if pending_preview else display_pos
        button.setProperty("display_label_full", display_label)
        button.setProperty("position_label", display_pos)
        button.setProperty("is_empty", True)
        _update_cell_label_visibility(self, button)
        button.setToolTip(
            t(
                "overview.emptyCellTooltip",
                box=box_num,
                position=position_display_text(position, layout, default="?"),
            )
        )
        base_style = cell_empty_style(is_selected)
        button.setStyleSheet(base_style)
        search_parts = [
            "empty",
            f"box {box_num}",
            f"position {position}",
            display_pos,
        ]
        if pending_preview:
            search_parts.append(pending_preview)
        button.setProperty("search_text", " ".join(search_parts).lower())
        button.setProperty("display_key_value", pending_preview)
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
    if hasattr(button, "set_selection_ring"):
        ring_color = resolve_theme_token("cell-selected-border", fallback="#63b3ff")
        button.set_selection_ring(
            bool(is_selected),
            ring_color=ring_color,
            active=bool(_is_active_selected_cell(self, box_num, position)),
            edge_mask=_selection_edge_mask(self, box_num, position),
        )

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


def _is_navigable_cell_button(button):
    return button is not None and not button.isHidden()


def _grid_dimensions(self):
    shape = getattr(self, "overview_shape", None)
    if isinstance(shape, tuple) and len(shape) >= 2:
        try:
            rows = max(1, int(shape[0]))
            cols = max(1, int(shape[1]))
            return rows, cols
        except (TypeError, ValueError):
            pass

    layout = getattr(self, "_current_layout", {}) or {}
    rows = max(1, int(layout.get("rows", 9) or 9))
    cols = max(1, int(layout.get("cols", 9) or 9))
    return rows, cols


def _first_visible_cell_key(self):
    for key in sorted(self.overview_cells):
        if _is_navigable_cell_button(self.overview_cells.get(key)):
            return key
    return None


def _select_grid_cell(self, box_num, position, *, focus=True, ensure_visible=True):
    key = (int(box_num), int(position))
    button = self.overview_cells.get(key)
    if not _is_navigable_cell_button(button):
        return False

    self._set_selected_cell(key[0], key[1])
    self.on_cell_hovered(key[0], key[1], force=True)

    if focus:
        try:
            button.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass

    if ensure_visible:
        scroll = getattr(self, "ov_scroll", None)
        if scroll is not None:
            x_margin = max(8, int(button.width() * 0.5))
            y_margin = max(8, int(button.height() * 0.5))
            try:
                scroll.ensureWidgetVisible(button, x_margin, y_margin)
            except Exception:
                pass

    return True


def _resolve_grid_navigation_target(self, direction):
    step_map = {
        "left": (0, -1),
        "right": (0, 1),
        "up": (-1, 0),
        "down": (1, 0),
    }
    step = step_map.get(str(direction or "").strip().lower())
    if step is None:
        return None

    current_key = getattr(self, "overview_selected_key", None)
    current_button = self.overview_cells.get(current_key) if current_key is not None else None
    if not _is_navigable_cell_button(current_button):
        return _first_visible_cell_key(self)

    box_num, position = current_key
    rows, cols = _grid_dimensions(self)
    row = (int(position) - 1) // cols
    col = (int(position) - 1) % cols
    dr, dc = step
    row += dr
    col += dc

    while 0 <= row < rows and 0 <= col < cols:
        next_key = (box_num, row * cols + col + 1)
        if _is_navigable_cell_button(self.overview_cells.get(next_key)):
            return next_key
        row += dr
        col += dc

    return current_key
