"""Cell interaction helpers for OverviewPanel."""

from PySide6.QtCore import Qt

from app_gui.i18n import tr, t
from app_gui.system_notice import build_system_notice
from lib.position_fmt import box_tag_text, format_box_position_display, position_display_text


def _emit_selected_empty_add_prefill(self, *, background=True, fallback_key=None):
    selected_keys = self._selected_empty_keys_for_box()
    fallback = tuple(fallback_key) if isinstance(fallback_key, (list, tuple)) else None
    if not selected_keys and fallback and self._cell_is_empty_slot(fallback[0], fallback[1]):
        selected_keys = [fallback]
    if not selected_keys:
        return False

    box_num = int(selected_keys[0][0])
    positions = sorted(int(position) for _box, position in selected_keys)
    emitter = self._emit_add_prefill_background if background else self._emit_add_prefill
    if len(positions) > 1:
        emitter(box_num, positions[0], positions=positions)
    else:
        emitter(box_num, positions[0])
    return True


def _build_empty_range_selection(self, start_key, end_key):
    start = tuple(start_key)
    end = tuple(end_key)
    if start[0] != end[0]:
        return []

    lower = min(int(start[1]), int(end[1]))
    upper = max(int(start[1]), int(end[1]))
    keys = []
    for position in range(lower, upper + 1):
        if self._cell_is_empty_slot(start[0], position, require_visible=True):
            keys.append((int(start[0]), int(position)))
    return keys


def on_cell_clicked(self, box_num, position, modifiers=None):
    key = (int(box_num), int(position))
    record = self.overview_pos_map.get(key)
    modifiers = Qt.NoModifier if modifiers is None else modifiers

    if record:
        self._clear_empty_multi_selection(clear_anchor=True, clear_active=False)
        self._select_grid_cell(key[0], key[1])
        self._prefill_grid_cell_to_operations_panel(key[0], key[1])
        return

    if not self._select_grid_cell(key[0], key[1]):
        return

    if modifiers & Qt.ShiftModifier:
        anchor_key = getattr(self, "_overview_selection_anchor_key", None)
        if (
            not isinstance(anchor_key, tuple)
            or len(anchor_key) != 2
            or int(anchor_key[0]) != key[0]
            or not self._cell_is_empty_slot(anchor_key[0], anchor_key[1])
        ):
            self._set_empty_multi_selection([key], anchor_key=key, active_key=key)
        else:
            range_keys = _build_empty_range_selection(self, anchor_key, key)
            self._set_empty_multi_selection(range_keys, anchor_key=anchor_key, active_key=key)
        _emit_selected_empty_add_prefill(self, background=True, fallback_key=key)
        return

    if modifiers & Qt.ControlModifier:
        selected_keys = self._selected_empty_keys_for_box()
        if selected_keys and int(selected_keys[0][0]) != key[0]:
            selected_keys = []

        selection_set = set(selected_keys)
        anchor_key = getattr(self, "_overview_selection_anchor_key", None)
        if key in selection_set:
            selection_set.remove(key)
            if anchor_key == key:
                anchor_key = None
            active_key = None
        else:
            selection_set.add(key)
            if not selection_set or anchor_key is None or int(anchor_key[0]) != key[0]:
                anchor_key = key
            active_key = key

        self._set_empty_multi_selection(selection_set, anchor_key=anchor_key, active_key=active_key)
        _emit_selected_empty_add_prefill(self, background=True, fallback_key=key)
        return

    self._set_empty_multi_selection([key], anchor_key=key, active_key=key)
    _emit_selected_empty_add_prefill(self, background=True, fallback_key=key)


def on_cell_double_clicked(self, box_num, position):
    on_cell_clicked(self, box_num, position, modifiers=Qt.NoModifier)


def _prefill_grid_cell_to_operations_panel(self, box_num, position):
    key = (int(box_num), int(position))
    record = self.overview_pos_map.get(key)
    if record:
        rec_id = int(record.get("id"))
        self._emit_takeout_prefill_background(key[0], key[1], rec_id)
        return

    if not self._selected_empty_keys_for_box(key[0]):
        self._set_empty_multi_selection([key], anchor_key=key, active_key=key)
    _emit_selected_empty_add_prefill(self, background=True, fallback_key=key)


def _navigate_grid_selection(self, direction):
    previous_key = getattr(self, "overview_selected_key", None)
    target_key = self._resolve_grid_navigation_target(direction)
    if target_key is None:
        return False

    if not self._select_grid_cell(target_key[0], target_key[1]):
        return False

    if self.overview_pos_map.get(target_key):
        self._clear_empty_multi_selection(clear_anchor=True, clear_active=False)
    else:
        self._set_empty_multi_selection([target_key], anchor_key=target_key, active_key=target_key)

    if target_key != previous_key:
        self._prefill_grid_cell_to_operations_panel(target_key[0], target_key[1])
    return True


def on_cell_hovered(self, box_num, position, force=False):
    hover_key = (box_num, position)
    if not force and self.overview_hover_key == hover_key:
        return
    button = self.overview_cells.get((box_num, position))
    if button is not None and button.isHidden():
        return
    record = self.overview_pos_map.get((box_num, position))
    self.overview_hover_key = hover_key
    self._show_detail(box_num, position, record)
    self._emit_hover_stats(box_num, position, record)


def _reset_detail(self):
    self.overview_hover_key = None
    self.ov_hover_hint.setText(tr("overview.hoverHint"))
    self.hover_stats_changed.emit("")


def _normalize_preview_value(raw):
    if raw is None:
        return ""
    return str(raw).strip()


def _resolve_preview_values(self, record):
    from lib.custom_fields import get_display_key, get_color_key

    meta = getattr(self, "_current_meta", {})
    current_records = getattr(self, "_current_records", []) or []
    keys = [
        get_display_key(meta, inventory=current_records or [record]),
        get_color_key(meta, inventory=current_records or [record]),
    ]
    values = []
    for key in keys:
        if not key:
            continue
        value = self._normalize_preview_value(record.get(key))
        if not value:
            continue
        if value in values:
            continue
        values.append(value)
    return values


def _emit_hover_stats(self, box_num, position, record):
    """Emit formatted hover stats for status bar display."""
    layout = getattr(self, "_current_layout", {}) or {}
    position_text = position_display_text(position, layout, default="?")
    if not record:
        self.hover_stats_changed.emit(t("overview.previewEmpty", box=box_num, pos=position_text))
        return

    from lib.custom_fields import get_display_key

    meta = getattr(self, "_current_meta", {})
    current_records = getattr(self, "_current_records", []) or []
    dk = get_display_key(meta, inventory=current_records or [record])
    rec_id = str(record.get("id", "-"))
    dk_val = str(record.get(dk, "-"))
    frozen_at = str(record.get("frozen_at", "-"))
    location_text = format_box_position_display(
        box_num,
        position,
        layout=layout,
        box_label=tr("operations.box", default="Box"),
        position_label=tr("operations.position", default="Position"),
    )
    self.hover_stats_changed.emit(
        t(
            "overview.hoverStatsRecord",
            id=rec_id,
            location=location_text,
            value=dk_val,
            date_label=tr("operations.frozenDate"),
            date=frozen_at,
        )
    )


def _show_detail(self, box_num, position, record):
    layout = getattr(self, "_current_layout", {}) or {}
    position_text = position_display_text(position, layout, default="?")
    if not record:
        self.ov_hover_hint.setText(t("overview.previewEmpty", box=box_num, pos=position_text))
        return

    rec_id = str(record.get("id", "-"))
    values = self._resolve_preview_values(record)
    if len(values) >= 2:
        self.ov_hover_hint.setText(
            t(
                "overview.previewRecord",
                box=box_num,
                pos=position_text,
                id=rec_id,
                cell=values[0],
                short=values[1],
            )
        )
        return

    value = values[0] if values else "-"
    self.ov_hover_hint.setText(
        t("overview.previewRecordSingle", box=box_num, pos=position_text, id=rec_id, value=value)
    )


def on_cell_context_menu(self, box_num, position, global_pos):
    from app_gui.ui import overview_panel as _ov_panel

    record = self.overview_pos_map.get((box_num, position))
    if record:
        self._clear_empty_multi_selection(clear_anchor=True, clear_active=False)
    else:
        key = (int(box_num), int(position))
        self._set_empty_multi_selection([key], anchor_key=key, active_key=key)
    self._select_grid_cell(box_num, position)

    # Use overview_panel.QMenu to keep monkeypatch target stable in tests.
    menu = _ov_panel.QMenu(self)
    act_add = None
    act_takeout = None

    if record:
        act_takeout = menu.addAction(tr("overview.takeout"))
    else:
        act_add = menu.addAction(tr("operations.add"))

    selected = menu.exec(global_pos)
    if selected is None:
        return

    if selected == act_add:
        self._emit_add_prefill(box_num, position)
        return

    if not record:
        return

    rec_id = int(record.get("id"))
    if selected == act_takeout:
        self._create_takeout_plan_item(rec_id, box_num, position, record)


def _current_box_tag(self, box_num):
    return box_tag_text(box_num, getattr(self, "_current_layout", {}) or {})


def _emit_box_tag_notice(self, *, operation, box_num, tag_value, response, text, level, timeout_ms):
    payload = response if isinstance(response, dict) else {}
    notice = build_system_notice(
        code=f"box.tag.{str(operation or 'set').lower()}",
        text=str(text or ""),
        level=str(level or "info"),
        source="overview_panel",
        timeout_ms=int(timeout_ms or 0),
        data={
            "operation": str(operation or ""),
            "box": int(box_num),
            "tag": str(tag_value or ""),
            "ok": bool(payload.get("ok")),
            "error_code": payload.get("error_code"),
        },
    )
    self.operation_event.emit(notice)


def on_box_context_menu(self, box_num, global_pos):
    from PySide6.QtWidgets import QInputDialog

    from app_gui.error_localizer import localize_error_payload
    from app_gui.ui import overview_panel as _ov_panel

    menu = _ov_panel.QMenu(self)
    act_set_tag = menu.addAction(tr("overview.setBoxTag"))
    act_clear_tag = menu.addAction(tr("overview.clearBoxTag"))
    current_tag = _current_box_tag(self, box_num)
    act_clear_tag.setEnabled(bool(current_tag))

    selected = menu.exec(global_pos)
    if selected is None:
        return

    yaml_path = self.yaml_path_getter()
    if not yaml_path:
        msg = tr("overview.boxTagUpdateFailed")
        self.status_message.emit(msg, 2500)
        _emit_box_tag_notice(
            self,
            operation="set",
            box_num=box_num,
            tag_value="",
            response={"ok": False, "error_code": "yaml_path_missing"},
            text=msg,
            level="error",
            timeout_ms=2500,
        )
        return

    if selected == act_set_tag:
        tag_text, ok = QInputDialog.getText(
            self,
            tr("overview.boxTagDialogTitle"),
            t("overview.boxTagDialogPrompt", box=box_num),
            text=current_tag,
        )
        if not ok:
            return
        response = self.bridge.set_box_tag(
            yaml_path=yaml_path,
            box=box_num,
            tag=str(tag_text or ""),
            execution_mode="execute",
        )
        if response.get("ok"):
            msg = t("overview.boxTagUpdated", box=box_num)
            self.refresh()
            self.status_message.emit(msg, 2500)
            _emit_box_tag_notice(
                self,
                operation="updated",
                box_num=box_num,
                tag_value=str(tag_text or ""),
                response=response,
                text=msg,
                level="success",
                timeout_ms=2500,
            )
        else:
            error_text = localize_error_payload(response, fallback=tr("overview.boxTagUpdateFailed"))
            self.status_message.emit(
                error_text,
                3500,
            )
            _emit_box_tag_notice(
                self,
                operation="updated",
                box_num=box_num,
                tag_value=str(tag_text or ""),
                response=response,
                text=error_text,
                level="error",
                timeout_ms=3500,
            )
        return

    if selected == act_clear_tag:
        response = self.bridge.set_box_tag(
            yaml_path=yaml_path,
            box=box_num,
            tag="",
            execution_mode="execute",
        )
        if response.get("ok"):
            msg = t("overview.boxTagCleared", box=box_num)
            self.refresh()
            self.status_message.emit(msg, 2500)
            _emit_box_tag_notice(
                self,
                operation="cleared",
                box_num=box_num,
                tag_value="",
                response=response,
                text=msg,
                level="success",
                timeout_ms=2500,
            )
        else:
            error_text = localize_error_payload(response, fallback=tr("overview.boxTagUpdateFailed"))
            self.status_message.emit(
                error_text,
                3500,
            )
            _emit_box_tag_notice(
                self,
                operation="cleared",
                box_num=box_num,
                tag_value="",
                response=response,
                text=error_text,
                level="error",
                timeout_ms=3500,
            )


def _create_takeout_plan_item(self, record_id, box_num, position, record):
    """Create a takeout plan item directly from overview context menu."""
    from datetime import date
    from lib.plan_item_factory import build_record_plan_item, resolve_record_box

    item = build_record_plan_item(
        action="Takeout",
        record_id=record_id,
        position=position,
        box=resolve_record_box(record, fallback_box=box_num),
        date_str=date.today().isoformat(),
        source="context_menu",
        payload_action="Takeout",
    )

    self.plan_items_requested.emit([item])
    self.status_message.emit(
        t("overview.takeoutAdded", id=record_id),
        2000,
    )


def _create_move_plan_item(self, *, record_id, from_box, from_pos, to_box, to_pos, record):
    """Create a move plan item directly from overview drag-and-drop."""
    from datetime import date
    from lib.plan_item_factory import build_record_plan_item, resolve_record_box

    resolved_box = resolve_record_box(record, fallback_box=from_box)
    to_box_param = int(to_box) if int(to_box) != int(resolved_box) else None
    item = build_record_plan_item(
        action="move",
        record_id=int(record_id),
        position=int(from_pos),
        box=int(resolved_box),
        date_str=date.today().isoformat(),
        to_position=int(to_pos),
        to_box=to_box_param,
        source="overview_drag",
        payload_action="Move",
    )
    self.plan_items_requested.emit([item])
    self.status_message.emit(
        t(
            "overview.moveAdded",
            id=record_id,
            from_box=from_box,
            from_pos=from_pos,
            to_box=to_box,
            to_pos=to_pos,
        ),
        2000,
    )


def _on_cell_drop(self, from_box, from_pos, to_box, to_pos, record_id):
    if from_box == to_box and from_pos == to_pos:
        return

    record = self.overview_pos_map.get((from_box, from_pos))
    self._create_move_plan_item(
        record_id=record_id,
        from_box=from_box,
        from_pos=from_pos,
        to_box=to_box,
        to_pos=to_pos,
        record=record,
    )
