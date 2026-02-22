"""Confirmation and rollback-detail helpers for OperationsPanel."""

import os
from datetime import datetime

from PySide6.QtWidgets import QMessageBox


def _ops_tr(key, **kwargs):
    """Resolve translations through operations_panel module for monkeypatch compatibility."""
    from app_gui.ui import operations_panel as _ops_panel

    return _ops_panel.tr(key, **kwargs)


def _confirm_warning_dialog(self, *, title, text, informative_text, detailed_text=None):
    msg = QMessageBox(self)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setInformativeText(informative_text)
    if detailed_text:
        msg.setDetailedText(detailed_text)
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    return msg.exec() == QMessageBox.Yes


def _confirm_execute(self, title, details):
    return self._confirm_warning_dialog(
        title=title,
        text=_ops_tr("operations.confirmModify"),
        informative_text=details,
    )


def _format_size_bytes(size_bytes):
    try:
        value = float(size_bytes)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"


def _build_rollback_confirmation_lines(
    self,
    *,
    backup_path,
    yaml_path,
    source_event=None,
    include_action_prefix=True,
):
    yaml_abs = os.path.abspath(str(yaml_path or ""))
    raw_backup = str(backup_path or "").strip()
    backup_abs = os.path.abspath(raw_backup) if raw_backup else ""
    backup_label = os.path.basename(backup_abs) if backup_abs else _ops_tr("operations.planRollbackLatest")

    lines = []
    restore_line = _ops_tr("operations.planRollbackRestore", backup=backup_label)
    if include_action_prefix:
        restore_line = f"{_ops_tr('operations.rollback')}: {restore_line}"
    lines.append(restore_line)
    lines.append(_ops_tr("operations.planRollbackYamlPath", path=yaml_abs or "-"))

    if backup_abs:
        lines.append(_ops_tr("operations.planRollbackBackupPath", path=backup_abs))
        try:
            stat = os.stat(backup_abs)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size = self._format_size_bytes(stat.st_size)
            lines.append(_ops_tr("operations.planRollbackBackupMeta", mtime=mtime, size=size))
        except Exception:
            lines.append(_ops_tr("operations.planRollbackBackupMissing", path=backup_abs))

    if isinstance(source_event, dict) and source_event:
        timestamp = str(source_event.get("timestamp") or "-")
        action = str(source_event.get("action") or "-")
        trace_id = str(source_event.get("trace_id") or "-")
        lines.append(
            _ops_tr(
                "operations.planRollbackSourceEvent",
                timestamp=timestamp,
                action=action,
                trace_id=trace_id,
            )
        )
    return lines
