"""Staging helpers for OperationsPanel single/batch record actions."""

from app_gui.i18n import tr
from lib.plan_item_factory import (
    build_add_plan_item,
    build_record_plan_item,
    iter_batch_entries,
    resolve_record_box,
)
from lib.tool_api import parse_batch_entries
from lib.validators import parse_positions

def on_add_entry(self):
    self._ensure_today_defaults()
    positions_text = self.a_positions.text().strip()

    try:
        positions = parse_positions(positions_text, layout=self._current_layout)
    except ValueError as exc:
        self._emit_exception_status(exc, 5000)
        return

    fields = self._collect_custom_add_values() or {}

    # cell_line is structural but passed through fields (tool_api extracts it)
    cl = self.a_cell_line.currentText().strip()
    if cl:
        fields["cell_line"] = cl
    note = self.a_note.text().strip()
    if note:
        fields["note"] = note

    item = build_add_plan_item(
        box=self.a_box.value(),
        positions=positions,
        frozen_at=self.a_date.date().toString("yyyy-MM-dd"),
        fields=fields,
        source="human",
    )
    self.add_plan_items([item])

def _record_takeout_with_action(self, action_text):
    action_text = str(action_text or "Takeout")
    idx = self.t_action.findData(action_text)
    if idx >= 0:
        self.t_action.setCurrentIndex(idx)
    else:
        self.t_action.setCurrentText(str(action_text))
    self.on_record_takeout()

def on_record_takeout(self):
    self._ensure_today_defaults()
    action_text = self.t_action.currentData() or self.t_action.currentText()

    fallback_box = int((self.t_prefill_source or {}).get("box", 0) or 0)

    position = self.t_position.currentData()
    if position is None:
        self._show_error(tr("operations.positionRequired"))
        return

    item = self._build_human_record_plan_item(
        action=action_text,
        record_id=self.t_id.value(),
        position=position,
        date_str=self.t_date.date().toString("yyyy-MM-dd"),
        payload_action=action_text,
        fallback_box=fallback_box,
    )

    self.add_plan_items([item])

def on_record_move(self):
    self._ensure_today_defaults()

    record = self._lookup_record(self.m_id.value())
    if not record:
        return

    from_pos = record.get("position")
    from_box = resolve_record_box(record, fallback_box=0)
    try:
        to_pos = self._parse_position_text(self.m_to_position.text())
    except ValueError as exc:
        self._emit_exception_status(exc, 4000)
        return
    to_box = self.m_to_box.value()

    if from_pos == to_pos and from_box == to_box:
        self.status_message.emit(tr("operations.moveMustDiffer"), 4000, "error")
        return

    to_box_param = to_box if to_box != from_box else None

    item = self._build_human_record_plan_item(
        action="move",
        record_id=self.m_id.value(),
        position=from_pos,
        date_str=self.m_date.date().toString("yyyy-MM-dd"),
        payload_action="Move",
        to_position=to_pos,
        to_box=to_box_param,
        fallback_box=from_box,
    )
    self.add_plan_items([item])

def _read_required_table_texts(table, row, required_columns):
    texts = []
    for col in required_columns:
        cell_item = table.item(row, col)
        if not cell_item:
            return None
        cell_text = str(cell_item.text() or "").strip()
        if not cell_text:
            return None
        texts.append(cell_text)
    return texts

def _collect_move_batch_from_table(self):
    """Collect move entries from the move batch table. Returns list of 3- or 4-tuples or None."""
    entries = []
    for row in range(self.bm_table.rowCount()):
        required_texts = self._read_required_table_texts(self.bm_table, row, (0, 1, 2))
        if not required_texts:
            continue
        id_text, from_text, to_text = required_texts
        to_box_item = self.bm_table.item(row, 3)

        try:
            entry = (
                int(id_text),
                self._parse_position_text(from_text),
                self._parse_position_text(to_text),
            )
            if to_box_item:
                tb_text = to_box_item.text().strip()
                if tb_text:
                    entry = entry + (int(tb_text),)
            entries.append(entry)
        except ValueError as exc:
            raise ValueError(
                tr("operations.invalidMoveRow", row=row + 1)
            ) from exc

    return entries if entries else None

def on_batch_move(self):
    self._ensure_today_defaults()

    entries = self._resolve_batch_entries_with_fallback(
        table_collector=self._collect_move_batch_from_table,
        raw_entries_text=self.bm_entries.text(),
        timeout=3000,
    )
    if entries is None:
        return

    date_str = self.bm_date.date().toString("yyyy-MM-dd")
    items = self._build_move_batch_plan_items(entries, date_str=date_str)
    self.add_plan_items(items)

def _collect_batch_from_table(self):
    """Collect entries from the mini-table. Returns list of tuples or None if empty."""
    entries = []
    for row in range(self.b_table.rowCount()):
        required_texts = self._read_required_table_texts(self.b_table, row, (0, 1))
        if not required_texts:
            continue
        id_text, pos_text = required_texts

        try:
            entries.append((int(id_text), self._parse_position_text(pos_text)))
        except ValueError as exc:
            raise ValueError(
                tr("operations.invalidBatchRow", row=row + 1)
            ) from exc

    return entries if entries else None

def _resolve_batch_entries_with_fallback(
    self,
    *,
    table_collector,
    raw_entries_text,
    timeout=3000,
):
    """Collect batch entries from table first, then fallback to text parser."""
    try:
        entries = table_collector()
    except ValueError as exc:
        self._emit_exception_status(exc, timeout)
        return None

    if entries is not None:
        return entries

    try:
        return parse_batch_entries(
            str(raw_entries_text or "").strip(),
            layout=self._current_layout,
        )
    except ValueError as exc:
        self._emit_exception_status(exc, timeout)
        return None

def _build_human_record_plan_item(
    self,
    *,
    action,
    record_id,
    position,
    date_str,
    payload_action,
    to_position=None,
    to_box=None,
    fallback_box=0,
):
    record = self._lookup_record(int(record_id))
    box = resolve_record_box(record, fallback_box=int(fallback_box or 0))
    payload = {
        "action": action,
        "record_id": int(record_id),
        "position": int(position),
        "box": box,
        "date_str": date_str,
        "source": "human",
        "payload_action": payload_action,
    }
    if to_position is not None:
        payload["to_position"] = to_position
        payload["to_box"] = to_box
    return build_record_plan_item(**payload)

def _build_move_batch_plan_items(self, entries, *, date_str):
    """Build staged move plan items from normalized batch entries."""
    items = []
    for normalized in iter_batch_entries(entries):
        rid = int(normalized.get("record_id", 0) or 0)
        from_pos = int(normalized.get("position", 0) or 0)
        to_pos = normalized.get("to_position")
        to_box = normalized.get("to_box")
        if to_pos is None:
            continue

        items.append(
            self._build_human_record_plan_item(
                action="move",
                record_id=rid,
                position=from_pos,
                date_str=date_str,
                payload_action="Move",
                to_position=to_pos,
                to_box=to_box,
            )
        )
    return items

def _build_takeout_batch_plan_items(self, entries, *, date_str, action_text):
    """Build staged takeout plan items from normalized batch entries."""
    items = []
    for normalized in iter_batch_entries(entries):
        rid = int(normalized.get("record_id", 0) or 0)
        pos = int(normalized.get("position", 0) or 0)
        items.append(
            self._build_human_record_plan_item(
                action=action_text,
                record_id=rid,
                position=pos,
                date_str=date_str,
                payload_action=action_text,
            )
        )
    return items

def on_batch_takeout(self):
    self._ensure_today_defaults()

    entries = self._resolve_batch_entries_with_fallback(
        table_collector=self._collect_batch_from_table,
        raw_entries_text=self.b_entries.text(),
        timeout=3000,
    )
    if entries is None:
        return

    action_text = self.b_action.currentText()
    date_str = self.b_date.date().toString("yyyy-MM-dd")
    items = self._build_takeout_batch_plan_items(
        entries,
        date_str=date_str,
        action_text=action_text,
    )
    self.add_plan_items(items)
