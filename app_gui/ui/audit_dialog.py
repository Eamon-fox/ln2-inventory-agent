import json
import os
import tempfile
from datetime import datetime
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QGroupBox,
    QFormLayout, QDateEdit, QLineEdit
)
from app_gui.i18n import tr
from app_gui.audit_guide import build_operation_guide_from_audit_events
from app_gui.plan_model import render_operation_sheet
from lib.yaml_ops import get_audit_log_path, get_legacy_audit_log_path
from lib.plan_item_factory import build_rollback_plan_item


class AuditLogDialog(QDialog):
    """Independent audit log viewer with filtering, guide generation, and rollback."""

    def __init__(self, parent, yaml_path_getter, bridge):
        super().__init__(parent)
        self.yaml_path_getter = yaml_path_getter
        self.bridge = bridge
        self._audit_events = []
        self._last_printable_plan = []

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
        self.audit_action_filter.addItem(tr("operations.auditActionRecordThaw"), "record_thaw")
        self.audit_action_filter.addItem(tr("operations.auditActionBatchThaw"), "batch_thaw")
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
        load_btn.clicked.connect(self.on_load_audit)
        btn_row.addWidget(load_btn)

        self.audit_guide_btn = QPushButton(tr("operations.auditGuideFromSelected"))
        self.audit_guide_btn.clicked.connect(self.on_generate_audit_guide)
        btn_row.addWidget(self.audit_guide_btn)

        self.audit_print_selected_btn = QPushButton(tr("operations.auditPrintSelectedGuide"))
        self.audit_print_selected_btn.clicked.connect(self.on_print_selected_audit_guide)
        btn_row.addWidget(self.audit_print_selected_btn)

        self.audit_rollback_selected_btn = QPushButton(tr("operations.auditRollbackFromSelected"))
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
            [tr("operations.colTimestamp"), tr("operations.colAction"), tr("operations.colActor"),
             tr("operations.colStatus"), tr("operations.colChannel"), tr("operations.colDetails")],
            sortable=True,
        )
        self.audit_table.cellClicked.connect(self._on_audit_row_clicked)

        # Event detail display
        self.event_detail = QLabel()
        self.event_detail.setWordWrap(True)
        self.event_detail.setStyleSheet(
            "background-color: var(--background-inset); "
            "border: 1px solid var(--border-weak); "
            "border-radius: var(--radius-sm); "
            "padding: 8px;"
        )
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
        refresh_btn.clicked.connect(self.on_refresh_backups)
        btn_row.addWidget(refresh_btn)

        select_btn = QPushButton(tr("operations.useSelected"))
        select_btn.clicked.connect(self.on_use_selected_backup)
        btn_row.addWidget(select_btn)

        rollback_latest_btn = QPushButton(tr("operations.rollbackLatest"))
        rollback_latest_btn.clicked.connect(self.on_rollback_latest)
        btn_row.addWidget(rollback_latest_btn)

        rollback_selected_btn = QPushButton(tr("operations.rollbackSelected"))
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
        yaml_abs = os.path.abspath(yaml_path)
        audit_path = get_audit_log_path(yaml_abs)
        if not os.path.isfile(audit_path):
            # Backward compatibility for logs written by older versions.
            legacy_path = get_legacy_audit_log_path(yaml_abs)
            if os.path.isfile(legacy_path):
                audit_path = legacy_path

        if not os.path.isfile(audit_path):
            self.audit_info.setText(tr("operations.auditFileNotFound", path=audit_path))
            return

        start = self.audit_start_date.date().toString("yyyy-MM-dd")
        end = self.audit_end_date.date().toString("yyyy-MM-dd")
        action_filter = self.audit_action_filter.currentData() or self.audit_action_filter.currentText()
        status_filter = self.audit_status_filter.currentData() or self.audit_status_filter.currentText()

        events = []
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = ev.get("timestamp", "")[:10]
                    if ts < start or ts > end:
                        continue
                    if action_filter != "All" and ev.get("action") != action_filter:
                        continue
                    if status_filter != "All" and ev.get("status") != status_filter:
                        continue

                    events.append(ev)
        except Exception as exc:
            self.audit_info.setText(tr("operations.failedToLoadAudit", error=exc))
            return

        # Newest first
        events.reverse()
        self._audit_events = events

        self._setup_table(
            self.audit_table,
            [
                tr("operations.colTimestamp"),
                tr("operations.colAction"),
                tr("operations.colActor"),
                tr("operations.colStatus"),
                tr("operations.colChannel"),
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
            self.audit_table.setItem(row, 2, QTableWidgetItem(ev.get("actor_type", "")))
            self.audit_table.setItem(row, 3, QTableWidgetItem(ev.get("status", "")))
            self.audit_table.setItem(row, 4, QTableWidgetItem(ev.get("channel", "")))

            details = ev.get("details") or {}
            error = ev.get("error") or {}
            if ev.get("status") == "failed":
                summary = str(error.get("message", ""))[:80] if error else str(details)[:80]
            else:
                summary = json.dumps(details, ensure_ascii=False)[:80] if details else ""
            self.audit_table.setItem(row, 5, QTableWidgetItem(summary))

        self.audit_info.setText(
            tr("operations.auditEventsShown", count=len(events), start=start, end=end)
        )

    def _on_audit_row_clicked(self, row, _col):
        """Show summary of selected audit event."""
        if row >= len(self._audit_events):
            return
        ev = self._audit_events[row]
        action = str(ev.get("action") or "")
        status = str(ev.get("status") or "")
        actor = str(ev.get("actor_id") or "")
        channel = str(ev.get("channel") or "")
        ts = str(ev.get("timestamp") or "")

        details = ev.get("details") or {}
        error = ev.get("error") or {}
        backup_path = ev.get("backup_path") or ""

        title_color = "var(--status-success)" if status == "success" else "var(--status-error)"
        lines = [f"<b style='color: {title_color};'>{tr('operations.audit')}：{action} ({status})</b>"]
        if ts:
            lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.timeLabel')}</span> {ts}")
        if actor:
            lines.append(
                f"<span style='color: var(--status-muted);'>{tr('operations.actorLabel')}</span> {actor} ({channel})"
            )
        if backup_path:
            lines.append(
                f"<span style='color: var(--status-muted);'>{tr('operations.backupLabel')}</span> {os.path.basename(str(backup_path))}"
            )

        if status == "failed" and isinstance(error, dict) and error:
            if error.get("error_code"):
                lines.append(
                    f"<span style='color: var(--status-muted);'>{tr('operations.errorLabel')}</span> {error.get('error_code')}"
                )
            if error.get("message"):
                lines.append(str(error.get("message")))
        elif isinstance(details, dict) and details:
            try:
                preview = json.dumps(details, ensure_ascii=False)
            except Exception:
                preview = str(details)
            lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.detailsLabel')}</span> {preview}")

        self.event_detail.setText("<br/>".join(lines))
        border = "var(--success)" if status == "success" else "var(--error)"
        self.event_detail.setStyleSheet(
            f"background-color: var(--background-inset); "
            f"border: 1px solid {border}; "
            f"border-radius: var(--radius-sm); "
            f"padding: 8px;"
        )
        self.event_detail.setVisible(True)

    def _get_selected_audit_events(self):
        model = self.audit_table.selectionModel()
        if model is None:
            return []
        selected = []
        for idx in model.selectedRows():
            row = idx.row()
            item = self.audit_table.item(row, 0)
            source_idx = item.data(Qt.UserRole) if item is not None else row
            try:
                event_idx = int(source_idx)
            except (TypeError, ValueError):
                event_idx = row
            if 0 <= event_idx < len(self._audit_events):
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
        for key in ("timestamp", "action", "trace_id", "session_id", "actor_id", "channel"):
            value = event.get(key)
            if value not in (None, ""):
                source_event[str(key)] = value
        return source_event

    def _apply_generated_audit_guide(self, guide, selected_count, print_now=False):
        items = list(guide.get("items") or [])
        warnings = list(guide.get("warnings") or [])
        stats = dict(guide.get("stats") or {})

        if not items:
            lines = [
                f"<b style='color: var(--status-error);'>{tr('operations.noPrintableFromSelection')}</b>",
                tr("operations.selectedEvents", count=selected_count),
            ]
            if warnings:
                preview = "<br/>".join(str(w) for w in warnings[:3])
                more = (
                    f"<br/><span style='color: var(--status-muted);'>{tr('operations.moreWarnings', count=len(warnings) - 3)}</span>"
                    if len(warnings) > 3
                    else ""
                )
                lines.append(
                    f"{tr('operations.warningsLabel')} {len(warnings)}<br/>{preview}{more}"
                )
            self.event_detail.setText("<br/>".join(lines))
            self.event_detail.setStyleSheet(
                "background-color: var(--background-inset); "
                "border: 1px solid var(--error); "
                "border-radius: var(--radius-sm); "
                "padding: 8px;"
            )
            self.event_detail.setVisible(True)
            return

        self._last_printable_plan = list(items)
        lines = [
            f"<b style='color: var(--status-success);'>{tr('operations.auditGuideGenerated')}</b>",
            tr("operations.selectedEvents", count=selected_count),
            tr("operations.finalOperations", count=len(items)),
        ]
        if warnings:
            preview = "<br/>".join(str(w) for w in warnings[:3])
            more = (
                f"<br/><span style='color: var(--status-muted);'>{tr('operations.moreWarnings', count=len(warnings) - 3)}</span>"
                if len(warnings) > 3
                else ""
            )
            lines.append(
                f"{tr('operations.warningsLabel')} {len(warnings)}<br/>{preview}{more}"
            )
        self.event_detail.setText("<br/>".join(lines))
        self.event_detail.setStyleSheet(
            "background-color: var(--background-inset); "
            "border: 1px solid var(--success); "
            "border-radius: var(--radius-sm); "
            "padding: 8px;"
        )
        self.event_detail.setVisible(True)

        if print_now:
            self._print_operation_sheet(items, tr("operations.auditGuideOpened"))

    def _print_operation_sheet(self, items, title):
        """Generate and open HTML operation sheet."""
        html = render_operation_sheet(items, title=title)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            temp_path = f.name
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(temp_path))

    def on_generate_audit_guide(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.audit_info.setText(tr("operations.selectAuditRowsFirst"))
            return
        guide = build_operation_guide_from_audit_events(selected_events)
        self._apply_generated_audit_guide(guide, selected_count=len(selected_events), print_now=False)

    def on_print_selected_audit_guide(self):
        selected_events = self._get_selected_audit_events()
        if not selected_events:
            self.audit_info.setText(tr("operations.selectAuditRowsFirst"))
            return
        guide = build_operation_guide_from_audit_events(selected_events)
        self._apply_generated_audit_guide(guide, selected_count=len(selected_events), print_now=True)

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

