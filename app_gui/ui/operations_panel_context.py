"""Record context helpers for OperationsPanel."""

from contextlib import suppress

from app_gui.i18n import tr
from lib.schema_aliases import get_storage_events, get_stored_at


def _coerce_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_matches_slot(record, box, position):
    if not isinstance(record, dict):
        return False
    return (
        _coerce_int_or_none(record.get("box")) == _coerce_int_or_none(box)
        and _coerce_int_or_none(record.get("position")) == _coerce_int_or_none(position)
    )


def _take_form_row(form, widget):
    if form is None or widget is None:
        return None
    # Check the widget is actually in this form to avoid
    # "QFormLayout::takeRow: Invalid widget" warnings from Qt.
    idx = form.indexOf(widget)
    if idx < 0:
        return None
    try:
        return form.takeRow(widget)
    except Exception:
        return None


def _delete_form_row_items(row):
    if row is None:
        return
    for item_name in ("labelItem", "fieldItem"):
        item = getattr(row, item_name, None)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def _rebuild_ctx_user_fields(self, prefix, custom_fields):
    """Rebuild user field context rows in takeout/move form."""
    if prefix == "takeout":
        form = getattr(self, "_takeout_ctx_form", None)
        widgets = getattr(self, "_takeout_ctx_widgets", {})
        frozen_label = getattr(self, "_t_ctx_frozen_label", None)
        frozen_container = getattr(self, "_t_ctx_frozen_container", None)
        note_label = getattr(self, "_t_ctx_note_label", None)
        note_container = getattr(self, "_t_ctx_note_container", None)
        cell_line_label = getattr(self, "_t_ctx_cell_line_label", None)
        cell_line_container = getattr(self, "_t_ctx_cell_line_container", None)
        history_label = getattr(self, "_t_ctx_history_label", None)
        history_container = getattr(self, "_t_ctx_history_container", None)
        rid_fn = lambda: self.t_id.value()
        refresh_fn = lambda: _refresh_takeout_record_context(self)
    else:
        form = getattr(self, "_move_ctx_form", None)
        widgets = getattr(self, "_move_ctx_widgets", {})
        frozen_label = getattr(self, "_m_ctx_frozen_label", None)
        frozen_container = getattr(self, "_m_ctx_frozen_container", None)
        note_label = getattr(self, "_m_ctx_note_label", None)
        note_container = getattr(self, "_m_ctx_note_container", None)
        cell_line_label = getattr(self, "_m_ctx_cell_line_label", None)
        cell_line_container = getattr(self, "_m_ctx_cell_line_container", None)
        history_label = getattr(self, "_m_ctx_history_label", None)
        history_container = getattr(self, "_m_ctx_history_container", None)
        rid_fn = lambda: self.m_id.value()
        refresh_fn = lambda: _refresh_move_record_context(self)
    if form is None:
        return

    fixed_rows = [
        (frozen_label, frozen_container),
        (note_label, note_container),
        (cell_line_label, cell_line_container),
        (history_label, history_container),
    ]

    for _label, container in fixed_rows:
        _take_form_row(form, container)

    for _key, (container, _label_widget) in widgets.items():
        _delete_form_row_items(_take_form_row(form, container))
    widgets.clear()

    if frozen_label is not None and frozen_container is not None:
        form.addRow(frozen_label, frozen_container)

    added_fixed_keys = set()
    for fdef in (custom_fields or []):
        key = fdef["key"]
        if key == "note":
            if "note" not in added_fixed_keys and note_label is not None and note_container is not None:
                form.addRow(note_label, note_container)
                added_fixed_keys.add("note")
            continue
        if key == "cell_line":
            if (
                "cell_line" not in added_fixed_keys
                and cell_line_label is not None
                and cell_line_container is not None
            ):
                form.addRow(cell_line_label, cell_line_container)
                added_fixed_keys.add("cell_line")
            continue
        flabel = fdef.get("label", key)
        from app_gui.ui import operations_panel_forms as _ops_forms

        container, lbl_widget = _ops_forms._make_editable_field(self, key, rid_fn, refresh_fn)
        form.addRow(flabel, container)
        widgets[key] = (container, lbl_widget)

    if "note" not in added_fixed_keys and note_label is not None and note_container is not None:
        form.addRow(note_label, note_container)

    if history_label is not None and history_container is not None:
        form.addRow(history_label, history_container)

    if prefix == "takeout":
        self._takeout_ctx_widgets = widgets
    else:
        self._move_ctx_widgets = widgets

def _lookup_record(self, rid):
    try:
        return self.records_cache.get(int(rid))
    except (ValueError, TypeError):
        return None


def _set_text_widget_value(widget, value):
    text = str(value or "")
    if hasattr(widget, "setPlainText"):
        widget.setPlainText(text)
        is_read_only = getattr(widget, "isReadOnly", None)
        if callable(is_read_only) and bool(is_read_only()):
            cursor_getter = getattr(widget, "textCursor", None)
            cursor_setter = getattr(widget, "setTextCursor", None)
            if callable(cursor_getter) and callable(cursor_setter):
                with suppress(Exception):
                    cursor = cursor_getter()
                    if cursor is not None and hasattr(cursor, "setPosition"):
                        cursor.setPosition(0)
                        cursor_setter(cursor)
            for bar_name in ("verticalScrollBar", "horizontalScrollBar"):
                bar_getter = getattr(widget, bar_name, None)
                if callable(bar_getter):
                    with suppress(Exception):
                        bar = bar_getter()
                        if bar is not None and hasattr(bar, "setValue") and hasattr(bar, "minimum"):
                            bar.setValue(int(bar.minimum()))
            ensure_visible = getattr(widget, "ensureCursorVisible", None)
            if callable(ensure_visible):
                with suppress(Exception):
                    ensure_visible()
        return
    if hasattr(widget, "setText"):
        widget.setText(text)
        is_read_only = getattr(widget, "isReadOnly", None)
        if callable(is_read_only) and bool(is_read_only()):
            set_cursor = getattr(widget, "setCursorPosition", None)
            if callable(set_cursor):
                with suppress(Exception):
                    set_cursor(0)
            deselect = getattr(widget, "deselect", None)
            if callable(deselect):
                with suppress(Exception):
                    deselect()


def _clear_context_label_groups(base_labels, extra_widgets):
    for lbl in base_labels or []:
        _set_text_widget_value(lbl, "-")
    for _key, widget_pair in (extra_widgets or {}).items():
        if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
            _set_text_widget_value(widget_pair[1], "-")


def _clear_staging_feedback(self):
    from app_gui.ui import operations_panel_forms as _ops_forms

    _ops_forms._set_plan_feedback(self, "")

def _populate_record_context_labels(
    self,
    *,
    record,
    box_label,
    position_label,
    frozen_label,
    note_label,
    cell_line_label,
    extra_widgets,
):
    box = self._normalize_box_value(
        record.get("box"),
        field_name="box",
        allow_empty=True,
    )
    position = self._normalize_position_value(
        record.get("position"),
        field_name="position",
        allow_empty=True,
    )
    _set_text_widget_value(box_label, str(box) if box is not None else "-")
    _set_text_widget_value(
        position_label,
        self._position_to_display(position) if position is not None else "-",
    )
    _set_text_widget_value(frozen_label, str(get_stored_at(record, default="-") or "-"))
    _set_text_widget_value(note_label, str(record.get("note") or "-"))
    _set_text_widget_value(cell_line_label, str(record.get("cell_line") or "-"))
    for key, widget_pair in (extra_widgets or {}).items():
        if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
            _set_text_widget_value(widget_pair[1], str(record.get(key) or "-"))
    return box, position

def _set_last_event_summary_label(self, label_widget, events):
    event_list = events or []
    if event_list:
        last = event_list[-1]
        label_widget.setText(
            tr(
                "operations.historySummary",
                count=len(event_list),
                date=str(last.get("date") or "-"),
                action=str(last.get("action") or "-"),
                positions=str(last.get("position") or "-"),
            )
        )
        return
    label_widget.setText(tr("operations.noHistory"))

def _refresh_takeout_record_context(self):
    _clear_staging_feedback(self)
    # Lookup record by box + position, or by ID if box/position not set
    from_box = self.t_from_box.value()
    from_pos = self._parse_position_text(self.t_from_position.text(), allow_empty=True)

    # Find record at this position
    record = None
    record_id = None

    # First try lookup by box + position
    if from_box > 0 and from_pos is not None:
        for rid, rec in self.records_cache.items():
            if _record_matches_slot(rec, from_box, from_pos):
                record = rec
                record_id = rid
                break

    # If not found and ID is set, try reverse lookup by ID
    if not record and self.t_id.value() > 0:
        record_id = self.t_id.value()
        record = self.records_cache.get(record_id)
        if record:
            # Update box/position fields from record
            rec_box = self._normalize_box_value(
                record.get("box"),
                field_name="box",
                allow_empty=True,
            )
            rec_pos = self._normalize_position_value(
                record.get("position"),
                field_name="position",
                allow_empty=True,
            )
            if rec_box is not None:
                self.t_from_box.blockSignals(True)
                self.t_from_box.setValue(int(rec_box))
                self.t_from_box.blockSignals(False)
            if rec_pos is not None:
                self.t_from_position.blockSignals(True)
                self.t_from_position.setText(self._position_to_display(rec_pos))
                self.t_from_position.blockSignals(False)

    # Update internal ID
    if record_id:
        self.t_id.blockSignals(True)
        self.t_id.setValue(record_id)
        self.t_id.blockSignals(False)

    source_text = "-"
    if self.t_prefill_source:
        source_box = self.t_prefill_source.get("box")
        source_prefill = self.t_prefill_source.get("position")
        if source_box is not None and source_prefill is not None:
            source_text = tr(
                "operations.boxSourceText",
                box=source_box,
                position=self._position_to_display(source_prefill),
            )
    self.t_ctx_source.setText(source_text)

    if not record:
        self.t_ctx_status.setText(tr("operations.recordNotFound"))
        self.t_ctx_status.setProperty("role", "statusWarning")
        self.t_ctx_status.setVisible(True)
        self.t_position.clear()
        _clear_context_label_groups(
            [
                self.t_ctx_box,
                self.t_ctx_position,
                self.t_ctx_frozen,
                self.t_ctx_note,
                self.t_ctx_cell_line,
                self.t_ctx_events,
            ],
            self._takeout_ctx_widgets,
        )
        return

    self.t_ctx_status.setVisible(False)

    _box, position = _populate_record_context_labels(
        self,
        record=record,
        box_label=self.t_ctx_box,
        position_label=self.t_ctx_position,
        frozen_label=self.t_ctx_frozen,
        note_label=self.t_ctx_note,
        cell_line_label=self.t_ctx_cell_line,
        extra_widgets=self._takeout_ctx_widgets,
    )

    # Set single position (hidden combo, kept for compat)
    self.t_position.blockSignals(True)
    self.t_position.clear()
    if position is not None:
        self.t_position.addItem(self._position_to_display(position), position)
        self.t_position.setCurrentIndex(0)
    self.t_position.blockSignals(False)

    _set_last_event_summary_label(self, self.t_ctx_events, get_storage_events(record))

def _on_move_source_changed(self):
    """Called when user manually changes source box/position."""
    _refresh_move_record_context(self)

def _refresh_move_record_context(self):
    if not hasattr(self, "m_ctx_status"):
        return

    _clear_staging_feedback(self)

    # Lookup record by box + position
    from_box = self.m_from_box.value()
    from_pos = self._parse_position_text(self.m_from_position.text(), allow_empty=True)

    # Find record at this position
    record = None
    record_id = None
    if from_pos is not None:
        for rid, rec in self.records_cache.items():
            if _record_matches_slot(rec, from_box, from_pos):
                record = rec
                record_id = rid
                break

    # Update internal ID
    if record_id:
        self.m_id.blockSignals(True)
        self.m_id.setValue(record_id)
        self.m_id.blockSignals(False)

    if not record:
        self.m_ctx_status.setText(tr("operations.recordNotFound"))
        self.m_ctx_status.setProperty("role", "statusWarning")
        self.m_ctx_status.setVisible(True)
        _clear_context_label_groups(
            [
                self.m_ctx_box,
                self.m_ctx_position,
                self.m_ctx_frozen,
                self.m_ctx_note,
                self.m_ctx_cell_line,
                self.m_ctx_events,
            ],
            self._move_ctx_widgets,
        )
        return

    self.m_ctx_status.setVisible(False)

    # Keep target box aligned with source box by default.
    box_num = self._normalize_box_value(
        record.get("box"),
        field_name="box",
        allow_empty=True,
    )
    if box_num is not None:
        self.m_to_box.blockSignals(True)
        self.m_to_box.setValue(int(box_num))
        self.m_to_box.blockSignals(False)

    _populate_record_context_labels(
        self,
        record=record,
        box_label=self.m_ctx_box,
        position_label=self.m_ctx_position,
        frozen_label=self.m_ctx_frozen,
        note_label=self.m_ctx_note,
        cell_line_label=self.m_ctx_cell_line,
        extra_widgets=self._move_ctx_widgets,
    )
    _set_last_event_summary_label(self, self.m_ctx_events, get_storage_events(record))

