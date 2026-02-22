"""Plan table rendering helpers for OperationsPanel."""

import json
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem

from app_gui.error_localizer import localize_error_payload
from app_gui.ui.utils import cell_color


def _tr(key, **kwargs):
    # Keep tests and monkeypatch points stable on operations_panel.tr.
    from app_gui.ui import operations_panel as _ops_panel

    return _ops_panel.tr(key, **kwargs)


def _trf(key, default, **kwargs):
    """Translate with resilient formatting, even when key falls back to default."""
    text = _tr(key, default=default, **kwargs)
    if kwargs:
        try:
            return str(text).format(**kwargs)
        except Exception:
            return str(text)
    return str(text)


def _plan_value_text(value):
    """Render field values in table-friendly text form."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)
    return str(value)


def _summarize_change_parts(parts, max_parts=None):
    """Build summary + full detail for the Operation Summary column."""
    cleaned = [str(part).strip() for part in parts if str(part).strip()]
    if not cleaned:
        return "-", ""

    detail = "\n".join(cleaned)
    limit = None
    try:
        limit = int(max_parts) if max_parts is not None else None
    except Exception:
        limit = None

    if limit and limit > 0 and len(cleaned) > limit:
        summary = "; ".join(cleaned[:limit])
        summary = f"{summary}; +{len(cleaned) - limit}"
        return summary, detail

    summary = "; ".join(cleaned)
    return summary, detail


def _build_plan_action_text(self, action_norm, item):
    from app_gui.ui import operations_panel as _ops_panel

    record_id = item.get("record_id")
    if action_norm == "rollback":
        return _tr("operations.rollback")
    if action_norm == "add":
        return _tr("operations.add")

    action_label = _ops_panel._localized_action(str(item.get("action", "") or ""))
    return f"{action_label} (ID {record_id})" if record_id else action_label


def _build_plan_target_text(self, action_norm, item, payload):
    if action_norm == "rollback":
        return "-"

    box = item.get("box", "")
    pos = item.get("position", "")
    pos_text = self._position_to_display(pos)
    box_text = box if box not in (None, "") else "?"
    box_prefix = f"Box {box_text}"

    if action_norm == "add":
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        if not positions:
            return f"{box_prefix}: ?"
        shown = ", ".join(self._position_to_display(p) for p in positions[:6])
        suffix = f", ... +{len(positions) - 6}" if len(positions) > 6 else ""
        return f"{box_prefix}: [{shown}{suffix}]"

    to_pos = item.get("to_position")
    to_box = item.get("to_box")
    to_pos_text = self._position_to_display(to_pos)
    if to_pos and (to_box is None or to_box == box):
        return f"{box_prefix}:{pos_text} -> {box_prefix}:{to_pos_text}"
    if to_pos and to_box:
        return f"{box_prefix}:{pos_text} -> Box {to_box}:{to_pos_text}"
    return f"{box_prefix}:{pos_text}"


def _build_plan_date_text(self, action_norm, payload):
    if action_norm == "rollback":
        source_event = payload.get("source_event") if isinstance(payload, dict) else None
        if isinstance(source_event, dict) and source_event.get("timestamp"):
            return str(source_event.get("timestamp"))
        return ""
    if action_norm == "add":
        return str(payload.get("frozen_at", ""))
    return str(payload.get("date_str", ""))


def _build_plan_changes(self, action_norm, item, payload, custom_fields):
    record_id = item.get("record_id")
    record = self.records_cache.get(record_id) if record_id in self.records_cache else {}
    label_map = {
        str(fdef.get("key")): str(fdef.get("label") or fdef.get("key"))
        for fdef in custom_fields
        if isinstance(fdef, dict) and fdef.get("key")
    }
    label_map.setdefault("short_name", _tr("operations.shortName"))
    label_map.setdefault("cell_line", _tr("operations.cellLine"))
    label_map.setdefault("frozen_at", _tr("operations.frozenDate"))
    label_map.setdefault("box", _tr("operations.box"))
    label_map.setdefault("position", _tr("operations.position"))
    label_map.setdefault("note", _tr("operations.note"))

    parts = []
    detail_parts = []
    summary_limit = 2

    def _collect_sample_tokens(*sources):
        tokens = []
        for source in sources:
            if not isinstance(source, dict):
                continue

            for key in ("cell_line", "short_name"):
                text = self._plan_value_text(source.get(key)).strip()
                if text and text not in tokens:
                    tokens.append(text)

            for fdef in custom_fields:
                key = str((fdef or {}).get("key") or "")
                if not key or key in {"cell_line", "short_name", "note"}:
                    continue
                text = self._plan_value_text(source.get(key)).strip()
                if text and text not in tokens:
                    tokens.append(text)
                if len(tokens) >= 3:
                    break
            if len(tokens) >= 3:
                break
        return tokens[:2]

    if action_norm == "rollback":
        source_event = payload.get("source_event") if isinstance(payload, dict) else None
        backup_path = payload.get("backup_path") if isinstance(payload, dict) else None
        rollback_target = os.path.basename(str(backup_path)) if backup_path else _tr("operations.planRollbackLatest")
        summary_limit = None
        parts.append(
            _trf(
                "operations.planChangeRollbackCore",
                default="[High risk] Rollback to {target}",
                target=rollback_target,
            )
        )

        if isinstance(source_event, dict) and source_event:
            detail_parts.append(
                _tr(
                    "operations.planRollbackSourceEvent",
                    timestamp=str(source_event.get("timestamp") or "-"),
                    action=str(source_event.get("action") or "-"),
                    trace_id=str(source_event.get("trace_id") or "-"),
                )
            )
        if backup_path:
            detail_parts.append(_tr("operations.planRollbackBackupPath", path=os.path.basename(str(backup_path))))
            backup_abs = os.path.abspath(str(backup_path))
            try:
                stat = os.stat(backup_abs)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = self._format_size_bytes(stat.st_size)
                detail_parts.append(_tr("operations.planRollbackBackupMeta", mtime=mtime, size=size))
            except Exception:
                detail_parts.append(_tr("operations.planRollbackBackupMissing", path=backup_abs))

    elif action_norm == "add":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        sample_tokens = _collect_sample_tokens(fields)
        if sample_tokens:
            parts.append(" / ".join(sample_tokens))
        else:
            parts.append(_tr("operations.add"))
        for key, value in fields.items():
            value_text = self._plan_value_text(value)
            if not value_text:
                continue
            label = label_map.get(str(key), str(key))
            detail_parts.append(f"{label}={value_text}")

    elif action_norm == "edit":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        for key, new_value in fields.items():
            label = label_map.get(str(key), str(key))
            old_value = record.get(key, "") if isinstance(record, dict) else ""
            old_text = self._plan_value_text(old_value)
            new_text = self._plan_value_text(new_value)
            if old_text != new_text:
                parts.append(f"{label}: {old_text} -> {new_text}")
        if not parts:
            parts.append(_tr("operations.planSummaryNoEffectiveEdit", default="No effective field change"))

    else:
        if action_norm == "move":
            box = item.get("box", "?")
            to_box = item.get("to_box")
            if to_box in (None, ""):
                to_box = box
            if to_box not in (None, "", box):
                parts.append(_tr("operations.planSummaryCrossBox", default="Cross-box"))

        sample_tokens = _collect_sample_tokens(record)
        if sample_tokens:
            parts.append(" / ".join(sample_tokens))
        elif action_norm == "move":
            parts.append(_tr("operations.move"))
        else:
            parts.append(_tr("overview.takeout", default="Takeout"))

    summary, base_detail = self._summarize_change_parts(parts, max_parts=summary_limit)
    if detail_parts:
        combined_detail = base_detail + "\n" + "\n".join(detail_parts) if base_detail else "\n".join(detail_parts)
        return summary, combined_detail
    return summary, base_detail


def _build_plan_status(self, item):
    validation = self._plan_validation_by_key.get(self._plan_item_key(item)) or {}
    if validation.get("blocked"):
        return _tr("operations.planStatusBlocked"), localize_error_payload(validation)
    return _tr("operations.planStatusReady"), localize_error_payload(validation, fallback="")


def _build_plan_row_semantics(self, item, custom_fields=None):
    """Build a normalized row model shared by UI table and printable table."""
    action_text = str(item.get("action", "") or "")
    action_norm = action_text.lower()
    payload = item.get("payload") or {}
    fields = custom_fields if custom_fields is not None else self._current_custom_fields

    action_display = self._build_plan_action_text(action_norm, item)
    target_display = self._build_plan_target_text(action_norm, item, payload)
    date_display = self._build_plan_date_text(action_norm, payload)
    changes_summary, changes_detail = self._build_plan_changes(action_norm, item, payload, fields)
    status_text, status_detail = self._build_plan_status(item)

    validation = self._plan_validation_by_key.get(self._plan_item_key(item)) or {}
    status_blocked = bool(validation.get("blocked"))

    return {
        "action_norm": action_norm,
        "action": action_display,
        "target": target_display,
        "date": date_display,
        "changes": changes_summary,
        "changes_detail": changes_detail,
        "status": status_text,
        "status_detail": status_detail,
        "status_blocked": status_blocked,
    }


def _refresh_plan_table(self):
    from lib.custom_fields import get_color_key

    has_items = bool(self._plan_store.count())
    self.plan_empty_label.setVisible(not has_items)
    self.plan_table.setVisible(has_items)

    custom_fields = self._current_custom_fields
    meta = self._current_meta
    color_key = get_color_key(meta)
    headers = [
        _tr("operations.colAction"),
        _tr("operations.colPosition"),
        _tr("operations.date"),
        _tr("operations.colChanges"),
        _tr("operations.colStatus"),
    ]

    self._setup_table(
        self.plan_table,
        headers,
        sortable=False,
    )

    header = self.plan_table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    plan_items = self._plan_store.list_items()
    for row, item in enumerate(plan_items):
        self.plan_table.insertRow(row)
        row_model = self._build_plan_row_semantics(item, custom_fields=custom_fields)

        action_item = QTableWidgetItem(str(row_model.get("action", "")))
        self.plan_table.setItem(row, 0, action_item)

        target_item = QTableWidgetItem(str(row_model.get("target", "")))
        self.plan_table.setItem(row, 1, target_item)

        date_item = QTableWidgetItem(str(row_model.get("date", "")))
        self.plan_table.setItem(row, 2, date_item)

        changes_summary = str(row_model.get("changes", ""))
        changes_detail = str(row_model.get("changes_detail", ""))
        changes_item = QTableWidgetItem(changes_summary)
        if changes_detail and changes_detail != changes_summary:
            changes_item.setToolTip(changes_detail)
        self.plan_table.setItem(row, 3, changes_item)

        status_text = str(row_model.get("status", ""))
        status_detail = str(row_model.get("status_detail", ""))
        status_item = QTableWidgetItem(status_text)
        if status_detail:
            status_item.setToolTip(status_detail)
        self.plan_table.setItem(row, 4, status_item)

        record_id = item.get("record_id")
        if record_id:
            record = self.records_cache.get(record_id)
            if record:
                color_value = record.get(color_key, "")
                row_color = cell_color(color_value if color_value else None)
                qcolor = QColor(row_color)
                for col in range(self.plan_table.columnCount()):
                    cell_item = self.plan_table.item(row, col)
                    if cell_item:
                        cell_item.setBackground(qcolor)

    for col in range(self.plan_table.columnCount()):
        self.plan_table.resizeColumnToContents(col)
    header.setSectionResizeMode(QHeaderView.Interactive)

    self._refresh_plan_toolbar_state()
