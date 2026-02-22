import json
import os
from datetime import datetime
from html import escape as _escape_html
from PySide6.QtCore import Qt, QDate, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QGroupBox,
    QFormLayout, QDateEdit, QLineEdit
)
from app_gui.i18n import tr
from app_gui.ui.icons import get_icon, Icons
from lib.yaml_ops import get_audit_log_paths, read_audit_events
from lib.plan_item_factory import build_rollback_plan_item


def _safe_html(value):
    return _escape_html(str(value or ""), quote=True)


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
        self.audit_action_filter.addItem(tr("operations.auditActionRecordTakeout"), "record_takeout")
        self.audit_action_filter.addItem(tr("operations.auditActionBatchTakeout"), "batch_takeout")
        self.audit_action_filter.addItem(tr("operations.auditActionRollback"), "rollback")
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
        btn_row.addWidget(self.audit_rollback_selected_btn)

        self.audit_backup_toggle_btn = QPushButton(tr("operations.showAdvancedRollback"))
        self.audit_backup_toggle_btn.clicked.connect(self.on_toggle_audit_backup_panel)
        btn_row.addWidget(self.audit_backup_toggle_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Advanced rollback panel
        self.audit_backup_panel = self._build_audit_backup_panel()
        self.audit_backup_panel.setVisible(False)
        layout.addWidget(self.audit_backup_panel)

        # Info label
        self.audit_info = QLabel(tr("operations.clickLoadAudit"))
        layout.addWidget(self.audit_info)

        # Audit table
        self.audit_table = QTableWidget()
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audit_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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

        # Event detail display
        self.event_detail = QLabel()
        self.event_detail.setObjectName("auditEventDetail")
        self.event_detail.setWordWrap(True)
        self.event_detail.setProperty("state", "default")
        self.event_detail.setVisible(False)
        layout.addWidget(self.event_detail)

    def _build_audit_backup_panel(self):
        panel = QGroupBox(tr("operations.auditRollbackAdvanced"))
        layout = QVBoxLayout(panel)

        form = QFormLayout()
        self.rb_backup_path = QLineEdit()
        self.rb_backup_path.setPlaceholderText(tr("operations.backupPh"))

        form.addRow(tr("operations.backupPath"), self.rb_backup_path)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(tr("operations.refreshBackups"))
        refresh_btn.setIcon(get_icon(Icons.REFRESH_CW))
        refresh_btn.setIconSize(QSize(16, 16))
        refresh_btn.clicked.connect(self.on_refresh_backups)
        btn_row.addWidget(refresh_btn)

        select_btn = QPushButton(tr("operations.useSelected"))
        select_btn.clicked.connect(self.on_use_selected_backup)
        btn_row.addWidget(select_btn)

        rollback_latest_btn = QPushButton(tr("operations.rollbackLatest"))
        rollback_latest_btn.setIcon(get_icon(Icons.ROTATE_CCW))
        rollback_latest_btn.setIconSize(QSize(16, 16))
        rollback_latest_btn.clicked.connect(self.on_rollback_latest)
        btn_row.addWidget(rollback_latest_btn)

        rollback_selected_btn = QPushButton(tr("operations.rollbackSelected"))
        rollback_selected_btn.setIcon(get_icon(Icons.ROTATE_CCW))
        rollback_selected_btn.setIconSize(QSize(16, 16))
        rollback_selected_btn.clicked.connect(self.on_rollback_selected)
        btn_row.addWidget(rollback_selected_btn)
        layout.addLayout(btn_row)

        self.backup_info = QLabel(tr("operations.backupsInfo"))
        layout.addWidget(self.backup_info)

        self.backup_table = QTableWidget()
        layout.addWidget(self.backup_table, 1)
        self._setup_table(
            self.backup_table,
            [tr("operations.backupColIndex"), tr("operations.backupColDate"),
             tr("operations.backupColSize"), tr("operations.backupColPath")],
            sortable=True,
        )
        return panel

    def _setup_table(self, table, headers, sortable=False):
        """Setup table with headers."""
        table.clear()
        table.setRowCount(0)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        if sortable:
            table.setSortingEnabled(True)

    def on_toggle_audit_backup_panel(self):
        visible = not self.audit_backup_panel.isVisible()
        self.audit_backup_panel.setVisible(visible)
        self.audit_backup_toggle_btn.setText(
            tr("operations.hideAdvancedRollback") if visible else tr("operations.showAdvancedRollback")
        )
        if visible and self.backup_table.rowCount() == 0:
            self.on_refresh_backups()

    def on_load_audit(self):
        """Load and display audit events from JSONL file."""
        yaml_path = self.yaml_path_getter()
        yaml_abs = os.path.abspath(str(yaml_path or ""))
        candidate_paths = get_audit_log_paths(yaml_abs)
        if not any(os.path.isfile(path) for path in candidate_paths):
            hint_path = candidate_paths[0] if candidate_paths else ""
            self.audit_info.setText(tr("operations.auditFileNotFound", path=hint_path))
            return

        start = self.audit_start_date.date().toString("yyyy-MM-dd")
        end = self.audit_end_date.date().toString("yyyy-MM-dd")
        action_filter = self.audit_action_filter.currentData() or self.audit_action_filter.currentText()
        status_filter = self.audit_status_filter.currentData() or self.audit_status_filter.currentText()

        events = []
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

        events.sort(key=lambda ev: str(ev.get("timestamp") or ""), reverse=True)
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
            self.audit_table.setItem(row, 1, QTableWidgetItem(ev.get("action", "")))
            self.audit_table.setItem(row, 2, QTableWidgetItem(ev.get("status", "")))

            details = ev.get("details") or {}
            error = ev.get("error") or {}
            if ev.get("status") == "failed":
                if isinstance(error, dict):
                    summary = str(error.get("message", ""))[:80] if error else str(details)[:80]
                else:
                    summary = str(error)[:80] if error else str(details)[:80]
            else:
                summary = json.dumps(details, ensure_ascii=False)[:80] if details else ""
            self.audit_table.setItem(row, 3, QTableWidgetItem(summary))

        if self.audit_table.rowCount() > 0:
            self.audit_table.sortItems(0, Qt.DescendingOrder)

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

        title_color = "var(--status-success)" if status == "success" else "var(--status-error)"
        lines = [
            f"<b style='color: {title_color};'>{_safe_html(tr('operations.audit'))}: "
            f"{_safe_html(action)} ({_safe_html(status)})</b>"
        ]
        if ts:
            lines.append(
                f"<span style='color: var(--status-muted);'>{_safe_html(tr('operations.timeLabel'))}</span> "
                f"{_safe_html(ts)}"
            )
        if backup_path:
            lines.append(
                f"<span style='color: var(--status-muted);'>{_safe_html(tr('operations.backupLabel'))}</span> "
                f"{_safe_html(os.path.basename(str(backup_path)))}"
            )

        if status == "failed" and isinstance(error, dict) and error:
            if error.get("error_code"):
                lines.append(
                    f"<span style='color: var(--status-muted);'>{_safe_html(tr('operations.errorLabel'))}</span> "
                    f"{_safe_html(error.get('error_code'))}"
                )
            if error.get("message"):
                lines.append(_safe_html(error.get("message")))
        elif isinstance(details, dict) and details:
            try:
                preview = json.dumps(details, ensure_ascii=False)
            except Exception:
                preview = str(details)
            lines.append(
                f"<span style='color: var(--status-muted);'>{_safe_html(tr('operations.detailsLabel'))}</span> "
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
        backup_path = str(event.get("backup_path") or "").strip()
        if not backup_path:
            self.audit_info.setText(tr("operations.selectedAuditNoBackup"))
            return

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

    def on_refresh_backups(self):
        # Implementation for refresh backups
        resp = self.bridge.list_backups(self.yaml_path_getter())
        backups = resp.get("result", {}).get("backups", [])
        self._setup_table(
            self.backup_table,
            [tr("operations.backupColIndex"), tr("operations.backupColDate"),
             tr("operations.backupColSize"), tr("operations.backupColPath")],
            sortable=True,
        )
        for row, path in enumerate(backups):
            self.backup_table.insertRow(row)
            try:
                stat = os.stat(path)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = str(stat.st_size)
            except:
                mtime, size = "-", "-"
            self.backup_table.setItem(row, 0, QTableWidgetItem(str(row+1)))
            self.backup_table.setItem(row, 1, QTableWidgetItem(mtime))
            self.backup_table.setItem(row, 2, QTableWidgetItem(size))
            self.backup_table.setItem(row, 3, QTableWidgetItem(path))
        self.backup_info.setText(tr("operations.foundBackups", count=len(backups)))

    def on_use_selected_backup(self):
        row = self.backup_table.currentRow()
        if row >= 0:
            path = self.backup_table.item(row, 3).text()
            self.rb_backup_path.setText(path)

    def on_rollback_latest(self):
        resp = self.bridge.list_backups(self.yaml_path_getter())
        backups = resp.get("result", {}).get("backups", []) if isinstance(resp, dict) else []
        if not backups:
            self.audit_info.setText(tr("operations.noBackupsFound"))
            return
        self._stage_rollback(backups[0])

    def on_rollback_selected(self):
        path = self.rb_backup_path.text().strip()
        if not path:
            self.audit_info.setText(tr("operations.selectBackupPathFirst"))
            return
        self._stage_rollback(path)

    def _stage_rollback(self, backup_path):
        """Stage rollback into Plan (human-in-the-loop)."""
        item = build_rollback_plan_item(
            backup_path=backup_path,
            source="human",
        )
        # Notify parent to add plan item
        if hasattr(self.parent(), 'operations_panel'):
            self.parent().operations_panel.add_plan_items([item])

