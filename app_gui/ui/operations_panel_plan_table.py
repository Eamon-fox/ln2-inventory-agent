"""Plan table rendering helpers for OperationsPanel."""

import json
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidgetItem,
)

from app_gui.error_localizer import localize_error_payload
from app_gui.ui.theme import pick_contrasting_text_color
from app_gui.ui.utils import cell_color
from lib.position_fmt import format_box_position_display, format_box_positions_display
from lib.schema_aliases import get_input_stored_at

PLAN_ROW_TINT_ROLE = int(Qt.UserRole) + 201


class _PlanTableTintDelegate(QStyledItemDelegate):
    """Render row tint for plan table items under QSS-themed tables."""

    def paint(self, painter, option, index):
        tint_hex = index.data(PLAN_ROW_TINT_ROLE)
        if not tint_hex:
            super().paint(painter, option, index)
            return

        tint = QColor(str(tint_hex))
        if not tint.isValid():
            super().paint(painter, option, index)
            return

        # Draw the standard item visuals without display text to avoid
        # text ghosting under tint overlays.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = str(opt.text or "")
        opt.text = ""
        opt.features = opt.features & ~QStyleOptionViewItem.HasDisplay

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        # Overlay tint — use same alpha as overview table for visual consistency.
        win_color = option.palette.color(QPalette.Window)
        is_light = win_color.lightnessF() > 0.5
        tint.setAlpha(90 if is_light else 128)
        painter.save()
        painter.fillRect(opt.rect, tint)
        painter.restore()

        if not text:
            return

        # Respect display role in case style option text was normalized.
        display_text = str(index.data(Qt.DisplayRole) or text)
        text = display_text
        if not text:
            return

        alignment = int(getattr(opt, "displayAlignment", Qt.AlignLeft | Qt.AlignVCenter))

        text_color = QColor(option.palette.color(QPalette.Text))
        fg_role = index.data(Qt.ForegroundRole)
        if hasattr(fg_role, "color"):
            role_color = fg_role.color()
            if isinstance(role_color, QColor) and role_color.isValid():
                text_color = role_color
        elif isinstance(fg_role, QColor) and fg_role.isValid():
            text_color = fg_role

        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        if not text_rect.isValid():
            text_rect = opt.rect.adjusted(6, 0, -6, 0)
        elided = painter.fontMetrics().elidedText(text, Qt.ElideRight, max(0, text_rect.width()))
        painter.save()
        painter.setPen(text_color)
        painter.drawText(text_rect, alignment | int(Qt.TextSingleLine), elided)
        painter.restore()


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
    box_label = _tr("operations.box", default="Box")
    position_label = _tr("operations.position", default="Position")
    positions_label = _tr("operations.positions", default="Positions")

    if action_norm == "rollback":
        return "-"

    box = item.get("box", "")

    if action_norm == "add":
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        shown_positions = list(positions[:6]) if positions else []
        suffix = f", ... +{len(positions) - 6}" if len(positions) > 6 else ""
        base_text = format_box_positions_display(
            box,
            shown_positions,
            layout=self._current_layout,
            box_label=box_label,
            positions_label=positions_label,
        )
        return base_text[:-1] + f"{suffix}]" if base_text.endswith("]") and suffix else base_text

    to_pos = item.get("to_position")
    to_box = item.get("to_box")
    if to_pos and (to_box is None or to_box == box):
        return (
            f"{format_box_position_display(box, item.get('position'), layout=self._current_layout, box_label=box_label, position_label=position_label)}"
            f" -> "
            f"{format_box_position_display(box, to_pos, layout=self._current_layout, box_label=box_label, position_label=position_label)}"
        )
    if to_pos and to_box:
        return (
            f"{format_box_position_display(box, item.get('position'), layout=self._current_layout, box_label=box_label, position_label=position_label)}"
            f" -> "
            f"{format_box_position_display(to_box, to_pos, layout=self._current_layout, box_label=box_label, position_label=position_label)}"
        )
    return format_box_position_display(
        box,
        item.get("position"),
        layout=self._current_layout,
        box_label=box_label,
        position_label=position_label,
    )


def _build_plan_date_text(self, action_norm, payload):
    if action_norm == "rollback":
        source_event = payload.get("source_event") if isinstance(payload, dict) else None
        if isinstance(source_event, dict) and source_event.get("timestamp"):
            return str(source_event.get("timestamp"))
        return ""
    if action_norm == "add":
        return str(get_input_stored_at(payload, default="") or "")
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
    label_map.setdefault("stored_at", _tr("operations.frozenDate"))
    label_map.setdefault("frozen_at", _tr("operations.frozenDate"))
    label_map.setdefault("box", _tr("operations.box"))
    label_map.setdefault("position", _tr("operations.position"))
    label_map.setdefault("note", _tr("operations.note"))

    parts = []
    detail_parts = []
    summary_limit = 2

    def _collect_sample_tokens(*sources):
        tokens = []
        declared_keys = [
            str((fdef or {}).get("key") or "")
            for fdef in custom_fields
            if isinstance(fdef, dict)
        ]
        declared_keys = [key for key in declared_keys if key and key != "note"]
        fallback_keys = ["cell_line", "plasmid_name", "short_name", "plasmid_id"]
        use_fallback_keys = not declared_keys
        for source in sources:
            if not isinstance(source, dict):
                continue

            keys_to_scan = declared_keys or fallback_keys
            for key in keys_to_scan:
                text = _plan_value_text(source.get(key)).strip()
                if text and text not in tokens:
                    tokens.append(text)
                    if use_fallback_keys:
                        break
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
                from app_gui.ui import operations_panel_confirm as _ops_confirm

                size = _ops_confirm._format_size_bytes(stat.st_size)
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
            value_text = _plan_value_text(value)
            if not value_text:
                continue
            label = label_map.get(str(key), str(key))
            detail_parts.append(f"{label}={value_text}")

    elif action_norm == "edit":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        for key, new_value in fields.items():
            label = label_map.get(str(key), str(key))
            old_value = record.get(key, "") if isinstance(record, dict) else ""
            old_text = _plan_value_text(old_value)
            new_text = _plan_value_text(new_value)
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

    summary, base_detail = _summarize_change_parts(parts, max_parts=summary_limit)
    if detail_parts:
        combined_detail = base_detail + "\n" + "\n".join(detail_parts) if base_detail else "\n".join(detail_parts)
        return summary, combined_detail
    return summary, base_detail


def _build_plan_status(self, item):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store

    validation = self._plan_validation_by_key.get(_ops_plan_store._plan_item_key(self, item)) or {}
    if validation.get("blocked"):
        return _tr("operations.planStatusBlocked"), localize_error_payload(validation)
    return _tr("operations.planStatusReady"), localize_error_payload(validation, fallback="")


def _build_plan_row_semantics(self, item, custom_fields=None):
    """Build a normalized row model shared by UI table and printable table."""
    action_text = str(item.get("action", "") or "")
    action_norm = action_text.lower()
    payload = item.get("payload") or {}
    fields = custom_fields if custom_fields is not None else self._current_custom_fields

    action_display = _build_plan_action_text(self, action_norm, item)
    target_display = _build_plan_target_text(self, action_norm, item, payload)
    date_display = _build_plan_date_text(self, action_norm, payload)
    changes_summary, changes_detail = _build_plan_changes(self, action_norm, item, payload, fields)
    status_text, status_detail = _build_plan_status(self, item)

    from app_gui.ui import operations_panel_plan_store as _ops_plan_store

    validation = self._plan_validation_by_key.get(_ops_plan_store._plan_item_key(self, item)) or {}
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
    from app_gui.ui import operations_panel_forms as _ops_forms
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    if not hasattr(self, "_plan_table_tint_delegate"):
        self._plan_table_tint_delegate = _PlanTableTintDelegate(self.plan_table)
        self.plan_table.setItemDelegate(self._plan_table_tint_delegate)

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

    _ops_forms._setup_table(
        self,
        self.plan_table,
        headers,
        sortable=False,
    )

    header = self.plan_table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    plan_items = self._plan_store.list_items()
    for row, item in enumerate(plan_items):
        self.plan_table.insertRow(row)
        row_model = _build_plan_row_semantics(self, item, custom_fields=custom_fields)

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
        record = self.records_cache.get(record_id) if record_id else None
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        payload_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}

        color_value = ""
        if isinstance(record, dict):
            color_value = str(record.get(color_key) or "")
        elif isinstance(payload_fields, dict):
            color_value = str(payload_fields.get(color_key) or "")

        should_tint_row = bool(record is not None) or bool(color_value)
        if should_tint_row:
            row_color = cell_color(color_value if color_value else None)
            for col in range(self.plan_table.columnCount()):
                cell_item = self.plan_table.item(row, col)
                if cell_item:
                    cell_item.setData(PLAN_ROW_TINT_ROLE, row_color)

    for col in range(self.plan_table.columnCount()):
        self.plan_table.resizeColumnToContents(col)
    header.setSectionResizeMode(QHeaderView.Interactive)

    _ops_plan_toolbar._refresh_plan_toolbar_state(self)
