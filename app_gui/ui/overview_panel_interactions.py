"""Cell interaction helpers for OverviewPanel."""

from app_gui.i18n import tr, t


def on_cell_clicked(self, box_num, position):
    self.on_cell_double_clicked(box_num, position)


def on_cell_double_clicked(self, box_num, position):
    record = self.overview_pos_map.get((box_num, position))
    self._set_selected_cell(box_num, position)
    self.on_cell_hovered(box_num, position, force=True)

    # Keep double click low-friction: prefill common forms directly.
    if record:
        rec_id = int(record.get("id"))
        self._emit_takeout_prefill_background(box_num, position, rec_id)
    else:
        self._emit_add_prefill_background(box_num, position)


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
    keys = [get_display_key(meta), get_color_key(meta)]
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
    if not record:
        self.hover_stats_changed.emit(t("overview.previewEmpty", box=box_num, pos=position))
        return

    from lib.custom_fields import get_display_key

    meta = getattr(self, "_current_meta", {})
    dk = get_display_key(meta)
    rec_id = str(record.get("id", "-"))
    dk_val = str(record.get(dk, "-"))
    frozen_at = str(record.get("frozen_at", "-"))
    self.hover_stats_changed.emit(
        f"ID {rec_id} | {box_num}:{position} | {dk_val} | {tr('operations.frozenDate')}: {frozen_at}"
    )


def _show_detail(self, box_num, position, record):
    if not record:
        self.ov_hover_hint.setText(t("overview.previewEmpty", box=box_num, pos=position))
        return

    rec_id = str(record.get("id", "-"))
    values = self._resolve_preview_values(record)
    if len(values) >= 2:
        self.ov_hover_hint.setText(
            t(
                "overview.previewRecord",
                box=box_num,
                pos=position,
                id=rec_id,
                cell=values[0],
                short=values[1],
            )
        )
        return

    value = values[0] if values else "-"
    self.ov_hover_hint.setText(
        t("overview.previewRecordSingle", box=box_num, pos=position, id=rec_id, value=value)
    )


def on_cell_context_menu(self, box_num, position, global_pos):
    from app_gui.ui import overview_panel as _ov_panel

    record = self.overview_pos_map.get((box_num, position))
    self._set_selected_cell(box_num, position)
    self.on_cell_hovered(box_num, position, force=True)

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
    box_tags = (getattr(self, "_current_layout", {}) or {}).get("box_tags")
    if not isinstance(box_tags, dict):
        return ""
    raw_value = box_tags.get(str(box_num))
    if raw_value is None:
        return ""
    return str(raw_value).replace("\r", " ").replace("\n", " ").strip()


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
        self.status_message.emit(tr("overview.boxTagUpdateFailed"), 2500)
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
            self.refresh()
            self.status_message.emit(t("overview.boxTagUpdated", box=box_num), 2500)
        else:
            self.status_message.emit(
                localize_error_payload(response, fallback=tr("overview.boxTagUpdateFailed")),
                3500,
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
            self.refresh()
            self.status_message.emit(t("overview.boxTagCleared", box=box_num), 2500)
        else:
            self.status_message.emit(
                localize_error_payload(response, fallback=tr("overview.boxTagUpdateFailed")),
                3500,
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
