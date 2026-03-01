import json
import os
from html import escape as _escape_html
from PySide6.QtCore import Qt, QDate, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QStyle, QStyledItemDelegate,
    QFormLayout, QDateEdit
)
from app_gui.i18n import tr
from app_gui.ui.icons import get_icon, Icons
from app_gui.ui.theme import resolve_theme_token
from lib.yaml_ops import get_audit_log_paths, read_audit_events
from lib.plan_item_factory import build_rollback_plan_item


def _safe_html(value):
    return _escape_html(str(value or ""), quote=True)


def _format_record_label(rec):
    """Format a compact label like '#101 HeLa Box2:5 [Note: xxx] [key: val]'."""
    rid = rec.get("record_id", "?")
    parts = [f"#{rid}"]
    cl = rec.get("cell_line") or rec.get("short_name")
    if cl:
        parts.append(str(cl))
    box = rec.get("box")
    pos = rec.get("position")
    if box is not None and pos is not None:
        parts.append(f"{tr('operations.auditDetailBox')}{box}:{pos}")
    note = rec.get("note")
    if note:
        parts.append(f"[{tr('operations.auditDetailNote')}: {note}]")
    custom = rec.get("custom_fields") or {}
    for k, v in custom.items():
        parts.append(f"[{k}: {v}]")
    return " ".join(parts)


def _format_audit_details(details, muted_color):
    """Return HTML lines for structured audit details rendering."""
    if not isinstance(details, dict):
        return []
    op = details.get("op")
    h = _safe_html
    m = lambda label: f"<span style='color: {muted_color};'>{h(label)}</span>"

    if op == "add_entry":
        ids = details.get("record_ids") or []
        box = details.get("box")
        positions = details.get("positions") or []
        frozen = details.get("frozen_at") or ""
        cell_line = details.get("cell_line") or ""
        note = details.get("note")
        pos_str = ",".join(str(p) for p in positions)
        line1 = (
            f"{m(tr('operations.auditDetailBox'))} {h(box)}  "
            f"{m(tr('operations.auditDetailPos'))} {h(pos_str)}  "
            f"{m('ID')} {h(','.join(str(i) for i in ids))}"
        )
        line2_parts = []
        if cell_line:
            line2_parts.append(h(cell_line))
        if frozen:
            line2_parts.append(f"{m(tr('operations.auditDetailFrozenAt'))} {h(frozen)}")
        if note:
            line2_parts.append(f"{m(tr('operations.auditDetailNote'))} {h(note)}")
        custom = details.get("custom_fields") or {}
        for k, v in custom.items():
            line2_parts.append(f"{m(h(k))} {h(v)}")
        lines = [line1]
        if line2_parts:
            lines.append(" &nbsp;|&nbsp; ".join(line2_parts))
        return lines

    if op == "edit_entry":
        rid = details.get("record_id")
        cl = details.get("cell_line") or details.get("short_name") or ""
        box = details.get("box")
        pos = details.get("position")
        loc = f"{tr('operations.auditDetailBox')}{box}:{pos}" if box is not None else ""
        header = f"#{h(rid)}"
        if cl:
            header += f" {h(cl)}"
        if loc:
            header += f" ({h(loc)})"
        note = details.get("note")
        if note:
            header += f" &nbsp;{m(tr('operations.auditDetailNote'))} {h(note)}"
        custom = details.get("custom_fields") or {}
        for k, v in custom.items():
            header += f" &nbsp;{m(h(k))} {h(v)}"
        lines = [header]
        changes = details.get("field_changes") or {}
        for field, diff in changes.items():
            before = diff.get("before") if isinstance(diff, dict) else "?"
            after = diff.get("after") if isinstance(diff, dict) else "?"
            lines.append(f"{m(h(field))} {h(before)} → {h(after)}")
        return lines

    if op in ("takeout", "thaw", "discard"):
        date = details.get("date") or ""
        records = details.get("records") or []
        rec_labels = [_format_record_label(r) for r in records]
        lines = []
        if date:
            lines.append(f"{m(tr('operations.auditDetailDate'))} {h(date)}")
        lines.append(", ".join(h(lbl) for lbl in rec_labels))
        return lines

    if op == "move":
        date = details.get("date") or ""
        moves = details.get("moves") or []
        lines = []
        if date:
            lines.append(f"{m(tr('operations.auditDetailDate'))} {h(date)}")
        for mv in moves:
            rid = mv.get("record_id", "?")
            cl = mv.get("cell_line") or mv.get("short_name") or ""
            fb, fp = mv.get("from_box"), mv.get("from_position")
            tb, tp = mv.get("to_box"), mv.get("to_position")
            label = f"#{h(rid)}"
            if cl:
                label += f" {h(cl)}"
            if fb == tb:
                label += f" {tr('operations.auditDetailBox')}{h(fb)}:{h(fp)}→{h(tp)}"
            else:
                label += f" {tr('operations.auditDetailBox')}{h(fb)}:{h(fp)}→{tr('operations.auditDetailBox')}{h(tb)}:{h(tp)}"
            swap = mv.get("swap_with_record_id")
            if swap is not None:
                label += f" (↔ #{h(swap)})"
            note = mv.get("note")
            if note:
                label += f" [{h(tr('operations.auditDetailNote'))}: {h(note)}]"
            custom = mv.get("custom_fields") or {}
            for k, v in custom.items():
                label += f" [{h(k)}: {h(v)}]"
            lines.append(label)
        return lines

    if op == "set_box_tag":
        box = details.get("box")
        before = details.get("tag_before") or "''"
        after = details.get("tag_after") or "''"
        return [f"{tr('operations.auditDetailBox')} {h(box)}: '{h(before)}' → '{h(after)}'"]

    if op == "adjust_box_count":
        sub = details.get("sub_op")
        cb = details.get("box_count_before")
        ca = details.get("box_count_after")
        if sub == "add":
            added = details.get("added_boxes") or []
            return [
                f"{h(cb)} → {h(ca)} {tr('operations.auditDetailBoxes')}  "
                f"{m('+' + ','.join(str(b) for b in added))}"
            ]
        else:
            removed = details.get("removed_box")
            mode = details.get("renumber_mode") or ""
            line = f"{h(cb)} → {h(ca)} {tr('operations.auditDetailBoxes')}"
            if removed is not None:
                line += f"  {m(tr('operations.auditDetailRemoved'))} {tr('operations.auditDetailBox')}{h(removed)}"
            if mode:
                line += f"  ({h(mode)})"
            return [line]

    if op == "rollback":
        restored = details.get("restored_from") or details.get("requested_backup") or ""
        lines = []
        if restored:
            import os as _os
            lines.append(f"{m(tr('operations.auditDetailFrom'))} {h(_os.path.basename(str(restored)))}")
        return lines

    # Fallback — unknown op or no op: show JSON
    return []


def _summarize_details(details):
    """Return a concise plain-text summary for the table column."""
    if not isinstance(details, dict) or not details:
        return ""
    op = details.get("op")

    if op == "add_entry":
        box = details.get("box", "?")
        positions = details.get("positions") or []
        cl = details.get("cell_line") or ""
        parts = [f"Box{box} Pos{','.join(str(p) for p in positions)}"]
        if cl:
            parts.append(cl)
        count = details.get("count")
        if count:
            parts.append(f"x{count}")
        return " | ".join(parts)

    if op == "edit_entry":
        rid = details.get("record_id", "?")
        changes = details.get("field_changes") or {}
        fields = ", ".join(changes.keys()) if changes else ""
        return f"#{rid} [{fields}]" if fields else f"#{rid}"

    if op in ("takeout", "thaw", "discard"):
        count = details.get("count", 0)
        date = details.get("date") or ""
        return f"{op} x{count} ({date})" if date else f"{op} x{count}"

    if op == "move":
        count = details.get("count", 0)
        return f"move x{count}"

    if op == "set_box_tag":
        box = details.get("box", "?")
        after = details.get("tag_after") or "''"
        return f"Box{box} → '{after}'"

    if op == "adjust_box_count":
        sub = details.get("sub_op", "?")
        cb = details.get("box_count_before")
        ca = details.get("box_count_after")
        return f"{sub} {cb}→{ca} boxes"

    if op == "rollback":
        bak = details.get("restored_from") or details.get("requested_backup") or ""
        if bak:
            return os.path.basename(str(bak))
        return "rollback"

    try:
        return json.dumps(details, ensure_ascii=False)[:80]
    except Exception:
        return str(details)[:80]


_ACTION_TR_KEYS = {
    "add_entry": "operations.auditActionAddEntry",
    "takeout": "operations.auditActionTakeout",
    "thaw": "operations.auditActionTakeout",
    "discard": "operations.auditActionTakeout",
    "move": "operations.auditActionMove",
    "rollback": "operations.auditActionRollback",
    "backup": "operations.auditActionBackup",
    "edit_entry": "operations.auditActionEditEntry",
    "set_box_tag": "operations.auditActionSetBoxTag",
    "adjust_box_count": "operations.auditActionAdjustBoxCount",
}


def _translate_action(action):
    """Return translated display name for an audit action."""
    key = _ACTION_TR_KEYS.get(action)
    if key:
        return tr(key)
    return action


_AUDIT_BACKUP_ROW_ROLE = Qt.UserRole + 101


class _AuditBackupTintDelegate(QStyledItemDelegate):
    """Ensure backup-row tint remains visible under custom table themes."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not bool(index.data(_AUDIT_BACKUP_ROW_ROLE)):
            return

        tint = QColor("#FFF4CC")
        # Selected cells get a lighter overlay so selection state is still recognizable.
        tint.setAlpha(72 if option.state & QStyle.State_Selected else 120)
        painter.save()
        painter.fillRect(option.rect, tint)
        painter.restore()


class AuditLogDialog(QDialog):
    """Independent audit log viewer with filtering and rollback staging."""

    def __init__(self, parent, yaml_path_getter, bridge):
        super().__init__(parent)
        self.yaml_path_getter = yaml_path_getter
        self.bridge = bridge
        self._audit_events = []

        self.setWindowTitle(tr("operations.auditLog"))
        self.resize(1000, 700)

        layout = QVBoxLayout(self)

        # Filter controls
        filter_form = QFormLayout()

        self.audit_start_date = QDateEdit()
        self.audit_start_date.setCalendarPopup(True)
        self.audit_start_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_start_date.setDate(QDate.currentDate().addDays(-7))
        filter_form.addRow(tr("operations.from"), self.audit_start_date)

        self.audit_end_date = QDateEdit()
        self.audit_end_date.setCalendarPopup(True)
        self.audit_end_date.setDisplayFormat("yyyy-MM-dd")
        self.audit_end_date.setDate(QDate.currentDate())
        filter_form.addRow(tr("operations.to"), self.audit_end_date)

        self.audit_action_filter = QComboBox()
        self.audit_action_filter.addItem(tr("operations.all"), "All")
        self.audit_action_filter.addItem(tr("operations.auditActionAddEntry"), "add_entry")
        self.audit_action_filter.addItem(tr("operations.auditActionTakeout"), "takeout")
        self.audit_action_filter.addItem(tr("operations.auditActionMove"), "move")
        self.audit_action_filter.addItem(tr("operations.auditActionRollback"), "rollback")
        self.audit_action_filter.addItem(tr("operations.auditActionBackup"), "backup")
        filter_form.addRow(tr("operations.auditAction"), self.audit_action_filter)

        self.audit_status_filter = QComboBox()
        self.audit_status_filter.addItem(tr("operations.all"), "All")
        self.audit_status_filter.addItem(tr("operations.auditStatusSuccess"), "success")
        self.audit_status_filter.addItem(tr("operations.auditStatusFailed"), "failed")
        filter_form.addRow(tr("operations.auditStatus"), self.audit_status_filter)

        layout.addLayout(filter_form)

        # Action buttons
        btn_row = QHBoxLayout()
        load_btn = QPushButton(tr("operations.loadAuditLog"))
        load_btn.setIcon(get_icon(Icons.FOLDER_OPEN))
        load_btn.setIconSize(QSize(16, 16))
        load_btn.clicked.connect(self.on_load_audit)
        btn_row.addWidget(load_btn)

        self.audit_rollback_selected_btn = QPushButton(tr("operations.auditRollbackFromSelected"))
        self.audit_rollback_selected_btn.setIcon(get_icon(Icons.ROTATE_CCW))
        self.audit_rollback_selected_btn.setIconSize(QSize(16, 16))
        self.audit_rollback_selected_btn.clicked.connect(self.on_stage_rollback_from_selected_audit)
        self.audit_rollback_selected_btn.setEnabled(False)
        btn_row.addWidget(self.audit_rollback_selected_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Info label
        self.audit_info = QLabel(tr("operations.clickLoadAudit"))
        layout.addWidget(self.audit_info)

        # Audit table
        self.audit_table = QTableWidget()
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audit_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.audit_table.setItemDelegate(_AuditBackupTintDelegate(self.audit_table))
        layout.addWidget(self.audit_table, 1)
        self._setup_table(
            self.audit_table,
            [
                tr("operations.colTimestamp"),
                tr("operations.colAction"),
                tr("operations.colStatus"),
                tr("operations.colDetails"),
            ],
            sortable=True,
        )
        self.audit_table.cellClicked.connect(self._on_audit_row_clicked)
        self.audit_table.itemSelectionChanged.connect(self._update_rollback_button_state)

        # Event detail display
        self.event_detail = QLabel()
        self.event_detail.setObjectName("auditEventDetail")
        self.event_detail.setWordWrap(True)
        self.event_detail.setProperty("state", "default")
        self.event_detail.setVisible(False)
        layout.addWidget(self.event_detail)

    def _setup_table(self, table, headers, sortable=False):
        """Setup table with headers."""
        table.clear()
        table.setRowCount(0)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        if sortable:
            table.setSortingEnabled(True)

    @staticmethod
    def _coerce_audit_seq(value):
        try:
            seq = int(value)
        except Exception:
            return None
        if seq <= 0:
            return None
        return seq

    @classmethod
    def _sort_events_newest_first(cls, events, *, reverse_if_no_seq):
        ordered = list(events or [])
        decorated = []
        has_seq = False
        for index, event in enumerate(ordered, start=1):
            seq = None
            if isinstance(event, dict):
                seq = cls._coerce_audit_seq(event.get("audit_seq"))
            if seq is not None:
                has_seq = True
            decorated.append((seq, index, event))

        if has_seq:
            # When sequence exists, it is the only ordering source of truth.
            decorated.sort(
                key=lambda row: (row[0] if row[0] is not None else -1, row[1]),
                reverse=True,
            )
            return [row[2] for row in decorated]

        if reverse_if_no_seq:
            return list(reversed(ordered))
        return ordered

    def on_load_audit(self):
        """Load and display audit events from JSONL file."""
        self.audit_rollback_selected_btn.setEnabled(False)
        yaml_path = self.yaml_path_getter()
        yaml_abs = os.path.abspath(str(yaml_path or ""))

        start = self.audit_start_date.date().toString("yyyy-MM-dd")
        end = self.audit_end_date.date().toString("yyyy-MM-dd")
        action_filter = self.audit_action_filter.currentData() or self.audit_action_filter.currentText()
        status_filter = self.audit_status_filter.currentData() or self.audit_status_filter.currentText()

        timeline_loader = getattr(self.bridge, "list_audit_timeline", None)
        events = []
        loaded_from_timeline_api = False
        if callable(timeline_loader):
            response = timeline_loader(
                yaml_path=yaml_abs,
                limit=None,
                offset=0,
                action_filter=None if action_filter == "All" else action_filter,
                status_filter=None if status_filter == "All" else status_filter,
                start_date=start,
                end_date=end,
            )
            if not isinstance(response, dict) or not response.get("ok"):
                message = (
                    (response or {}).get("message")
                    if isinstance(response, dict)
                    else tr("operations.unknownError")
                )
                self.audit_info.setText(tr("operations.failedToLoadAudit", error=message))
                return
            events = list((response.get("result") or {}).get("items") or [])
            loaded_from_timeline_api = True
        else:
            candidate_paths = get_audit_log_paths(yaml_abs)
            if not any(os.path.isfile(path) for path in candidate_paths):
                hint_path = candidate_paths[0] if candidate_paths else ""
                self.audit_info.setText(tr("operations.auditFileNotFound", path=hint_path))
                return

            try:
                for ev in read_audit_events(yaml_abs):
                    ts = str(ev.get("timestamp") or "")[:10]
                    if ts and (ts < start or ts > end):
                        continue
                    if action_filter != "All" and str(ev.get("action") or "") != action_filter:
                        continue
                    if status_filter != "All" and str(ev.get("status") or "") != status_filter:
                        continue
                    events.append(ev)
            except Exception as exc:
                self.audit_info.setText(tr("operations.failedToLoadAudit", error=exc))
                return

        events = self._sort_events_newest_first(
            events,
            reverse_if_no_seq=not loaded_from_timeline_api,
        )
        self._audit_events = events

        self._setup_table(
            self.audit_table,
            [
                tr("operations.colTimestamp"),
                tr("operations.colAction"),
                tr("operations.colStatus"),
                tr("operations.colDetails"),
            ],
            sortable=True,
        )
        for row, ev in enumerate(events):
            self.audit_table.insertRow(row)
            ts_item = QTableWidgetItem(ev.get("timestamp", ""))
            ts_item.setData(Qt.UserRole, row)
            self.audit_table.setItem(row, 0, ts_item)
            action_item = QTableWidgetItem(_translate_action(ev.get("action", "")))
            self.audit_table.setItem(row, 1, action_item)
            self.audit_table.setItem(row, 2, QTableWidgetItem(ev.get("status", "")))

            details = ev.get("details") or {}
            error = ev.get("error") or {}
            if ev.get("status") == "failed":
                if isinstance(error, dict):
                    summary = str(error.get("message", ""))[:80] if error else str(details)[:80]
                else:
                    summary = str(error)[:80] if error else str(details)[:80]
            else:
                summary = _summarize_details(details)
            self.audit_table.setItem(row, 3, QTableWidgetItem(summary))
            if self._is_backup_event(ev):
                self._highlight_backup_row(row)

        self._update_rollback_button_state()

        self.audit_info.setText(
            tr("operations.auditEventsShown", count=len(events), start=start, end=end)
        )

    def _event_index_for_table_row(self, row):
        if row < 0:
            return None
        item = self.audit_table.item(row, 0)
        source_idx = item.data(Qt.UserRole) if item is not None else row
        try:
            event_idx = int(source_idx)
        except (TypeError, ValueError):
            event_idx = row
        if 0 <= event_idx < len(self._audit_events):
            return event_idx
        return None

    @staticmethod
    def _is_backup_event(event):
        if not isinstance(event, dict):
            return False
        action = str(event.get("action") or "").strip().lower()
        if action != "backup":
            return False
        backup_path = str(event.get("backup_path") or "").strip()
        if not backup_path:
            return False
        try:
            return int(event.get("audit_seq")) > 0
        except Exception:
            return False

    def _highlight_backup_row(self, row):
        for col in range(self.audit_table.columnCount()):
            cell = self.audit_table.item(row, col)
            if cell is not None:
                cell.setData(_AUDIT_BACKUP_ROW_ROLE, True)
                font = cell.font()
                font.setBold(True)
                cell.setFont(font)

    def _update_rollback_button_state(self):
        selected_events = self._get_selected_audit_events()
        enabled = len(selected_events) == 1 and self._is_backup_event(selected_events[0])
        self.audit_rollback_selected_btn.setEnabled(enabled)

    def _on_audit_row_clicked(self, row, _col):
        """Show summary of selected audit event."""
        event_idx = self._event_index_for_table_row(row)
        if event_idx is None:
            return
        ev = self._audit_events[event_idx]
        action = str(ev.get("action") or "")
        status = str(ev.get("status") or "")
        ts = str(ev.get("timestamp") or "")

        details = ev.get("details") or {}
        error = ev.get("error") or {}
        backup_path = ev.get("backup_path") or ""

        success_color = resolve_theme_token("status-success", fallback="#22c55e")
        error_color = resolve_theme_token("status-error", fallback="#ef4444")
        muted_color = resolve_theme_token("status-muted", fallback="#94a3b8")
        title_color = success_color if status == "success" else error_color
        action_display = _translate_action(action)
        lines = [
            f"<b style='color: {title_color};'>{_safe_html(tr('operations.audit'))}: "
            f"{_safe_html(action_display)} ({_safe_html(status)})</b>"
        ]
        if ts:
            lines.append(
                f"<span style='color: {muted_color};'>{_safe_html(tr('operations.timeLabel'))}</span> "
                f"{_safe_html(ts)}"
            )
        if backup_path:
            lines.append(
                f"<span style='color: {muted_color};'>{_safe_html(tr('operations.backupLabel'))}</span> "
                f"{_safe_html(os.path.basename(str(backup_path)))}"
            )

        if status == "failed" and isinstance(error, dict) and error:
            if error.get("error_code"):
                lines.append(
                    f"<span style='color: {muted_color};'>{_safe_html(tr('operations.errorLabel'))}</span> "
                    f"{_safe_html(error.get('error_code'))}"
                )
            if error.get("message"):
                lines.append(_safe_html(error.get("message")))
        elif isinstance(details, dict) and details:
            detail_lines = _format_audit_details(details, muted_color)
            if detail_lines:
                lines.extend(detail_lines)
            else:
                try:
                    preview = json.dumps(details, ensure_ascii=False)
                except Exception:
                    preview = str(details)
                lines.append(
                    f"<span style='color: {muted_color};'>{_safe_html(tr('operations.detailsLabel'))}</span> "
                    f"{_safe_html(preview)}"
                )

        self.event_detail.setText("<br/>".join(lines))
        self.event_detail.setProperty("state", "success" if status == "success" else "error")
        self.event_detail.style().unpolish(self.event_detail)
        self.event_detail.style().polish(self.event_detail)
        self.event_detail.setVisible(True)

    def _get_selected_audit_events(self):
        model = self.audit_table.selectionModel()
        if model is None:
            return []
        selected = []
        for idx in model.selectedRows():
            event_idx = self._event_index_for_table_row(idx.row())
            if event_idx is not None:
                selected.append((event_idx, self._audit_events[event_idx]))

        dedup = {}
        for event_idx, event in selected:
            dedup[event_idx] = event
        ordered = [dedup[key] for key in sorted(dedup)]
        return ordered

    def _build_audit_source_event(self, event):
        if not isinstance(event, dict):
            return {}
        source_event = {}
        for key in ("timestamp", "action", "trace_id", "session_id"):
            value = event.get(key)
            if value not in (None, ""):
                source_event[str(key)] = value
        return source_event

    def on_stage_rollback_from_selected_audit(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.audit_info.setText(tr("operations.selectAuditRowsFirst"))
            return
        if len(selected_events) != 1:
            self.audit_info.setText(tr("operations.selectSingleAuditRow"))
            return

        event = selected_events[0]
        if not self._is_backup_event(event):
            self.audit_info.setText(tr("operations.selectedAuditNoBackup"))
            return
        backup_path = str(event.get("backup_path") or "").strip()

        item = build_rollback_plan_item(
            backup_path=backup_path,
            source="human",
            source_event=self._build_audit_source_event(event),
        )

        # Notify parent to add plan item
        if hasattr(self.parent(), 'operations_panel'):
            self.parent().operations_panel.add_plan_items([item])
            self.audit_info.setText(
                tr("operations.auditRollbackStaged", backup=os.path.basename(str(backup_path)))
            )


