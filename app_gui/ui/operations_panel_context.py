"""Record context helpers for OperationsPanel."""

from app_gui.i18n import tr

def _takeout_record_id(self):
    return self.t_id.value()

def _move_record_id(self):
    return self.m_id.value()

def _rebuild_ctx_user_fields(self, prefix, custom_fields):
    """Rebuild user field context rows in takeout/move form."""
    if prefix == "takeout":
        form = getattr(self, "_takeout_ctx_form", None)
        widgets = getattr(self, "_takeout_ctx_widgets", {})
        rid_fn = self._takeout_record_id
        refresh_fn = self._refresh_takeout_record_context
    else:
        form = getattr(self, "_move_ctx_form", None)
        widgets = getattr(self, "_move_ctx_widgets", {})
        rid_fn = self._move_record_id
        refresh_fn = self._refresh_move_record_context
    if form is None:
        return
    # Remove old user field rows
    for key, (container, label) in widgets.items():
        form.removeRow(container)
    widgets.clear()
    # Insert new user field rows
    for fdef in (custom_fields or []):
        key = fdef["key"]
        flabel = fdef.get("label", key)
        container, lbl_widget = self._make_editable_field(key, rid_fn, refresh_fn)
        form.insertRow(form.rowCount(), flabel, container)
        widgets[key] = (container, lbl_widget)
    if prefix == "takeout":
        self._takeout_ctx_widgets = widgets
    else:
        self._move_ctx_widgets = widgets

def _lookup_record(self, rid):
    try:
        return self.records_cache.get(int(rid))
    except (ValueError, TypeError):
        return None

def _clear_context_label_groups(base_labels, extra_widgets):
    for lbl in base_labels or []:
        lbl.setText("-")
    for _key, widget_pair in (extra_widgets or {}).items():
        if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
            widget_pair[1].setText("-")

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
    box = str(record.get("box") or "-")
    position = record.get("position")
    box_label.setText(box)
    position_label.setText(self._position_to_display(position) if position is not None else "-")
    frozen_label.setText(str(record.get("frozen_at") or "-"))
    note_label.setText(str(record.get("note") or "-"))
    cell_line_label.setText(str(record.get("cell_line") or "-"))
    for key, widget_pair in (extra_widgets or {}).items():
        if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
            widget_pair[1].setText(str(record.get(key) or "-"))
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
    # Lookup record by box + position, or by ID if box/position not set
    from_box = self.t_from_box.value()
    from_pos = self._parse_position_text(self.t_from_position.text(), allow_empty=True)

    # Find record at this position
    record = None
    record_id = None

    # First try lookup by box + position
    if from_box > 0 and from_pos is not None:
        for rid, rec in self.records_cache.items():
            if rec.get("box") == from_box and rec.get("position") == from_pos:
                record = rec
                record_id = rid
                break

    # If not found and ID is set, try reverse lookup by ID
    if not record and self.t_id.value() > 0:
        record_id = self.t_id.value()
        record = self.records_cache.get(record_id)
        if record:
            # Update box/position fields from record
            rec_box = record.get("box")
            rec_pos = record.get("position")
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
        self._clear_context_label_groups(
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

    _box, position = self._populate_record_context_labels(
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

    self._set_last_event_summary_label(self.t_ctx_events, record.get("thaw_events"))

def _on_move_source_changed(self):
    """Called when user manually changes source box/position."""
    # Reset user-specified flag so target box can auto-fill
    self._m_to_box_user_specified = False
    self._refresh_move_record_context()

def _refresh_move_record_context(self):
    if not hasattr(self, "m_ctx_status"):
        return

    # Lookup record by box + position
    from_box = self.m_from_box.value()
    from_pos = self._parse_position_text(self.m_from_position.text(), allow_empty=True)

    # Find record at this position
    record = None
    record_id = None
    if from_pos is not None:
        for rid, rec in self.records_cache.items():
            if rec.get("box") == from_box and rec.get("position") == from_pos:
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
        self._clear_context_label_groups(
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

    box = str(record.get("box") or "-")

    # Auto-fill target box with source box (only if not user-specified)
    if not getattr(self, "_m_to_box_user_specified", False):
        try:
            box_num = int(box)
            self.m_to_box.blockSignals(True)
            self.m_to_box.setValue(box_num)
            self.m_to_box.blockSignals(False)
        except (ValueError, TypeError):
            pass

    self._populate_record_context_labels(
        record=record,
        box_label=self.m_ctx_box,
        position_label=self.m_ctx_position,
        frozen_label=self.m_ctx_frozen,
        note_label=self.m_ctx_note,
        cell_line_label=self.m_ctx_cell_line,
        extra_widgets=self._move_ctx_widgets,
    )
    self._set_last_event_summary_label(self.m_ctx_events, record.get("thaw_events"))

