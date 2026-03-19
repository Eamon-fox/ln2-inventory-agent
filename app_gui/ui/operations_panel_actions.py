"""Action helpers for OperationsPanel print/export/undo flows."""

import os
from copy import deepcopy
from datetime import date

from PySide6.QtCore import QTimer

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr


def _print_items_with_grid(self, items_to_print, *, empty_message, opened_message, grid_state=None, table_rows=None):
    items = list(items_to_print or [])
    if not items:
        self.status_message.emit(str(empty_message), 3000, "error")
        return

    if grid_state is None:
        grid_state = _build_print_grid_state(self, items)
    if table_rows is None:
        table_rows = _build_print_table_rows(self, items)
    _print_operation_sheet_with_grid(
        self,
        items,
        grid_state,
        table_rows=table_rows,
        opened_message=str(opened_message),
    )


def print_plan(self):
    """Print current staged plan (not yet executed)."""
    _print_items_with_grid(
        self,
        self._plan_store.list_items(),
        empty_message=tr("operations.noCurrentPlanToPrint"),
        opened_message=tr("operations.planPrintOpened"),
    )


def print_last_executed(self):
    """Print the last successfully applied execution result."""
    snapshot = self._last_executed_print_snapshot if isinstance(self._last_executed_print_snapshot, dict) else {}
    snapshot_items = snapshot.get("items")
    use_snapshot = isinstance(snapshot_items, list) and bool(snapshot_items)
    items_to_print = list(snapshot_items if use_snapshot else (self._last_executed_plan or []))

    if not items_to_print:
        self.status_message.emit(str(tr("operations.noLastExecutedToPrint")), 3000, "error")
        return

    grid_state = deepcopy(snapshot.get("grid_state")) if use_snapshot else None
    table_rows = deepcopy(snapshot.get("table_rows")) if use_snapshot else None
    if not isinstance(table_rows, list) or len(table_rows) != len(items_to_print):
        table_rows = _build_last_executed_print_table_rows(self, items_to_print)

    _print_items_with_grid(
        self,
        items_to_print,
        empty_message=tr("operations.noLastExecutedToPrint"),
        opened_message=tr("operations.lastExecutedPrintOpened"),
        grid_state=grid_state,
        table_rows=table_rows,
    )


def _build_last_executed_print_table_rows(self, items_to_print):
    rows = _build_print_table_rows(self, items_to_print)
    executed_status = tr("operations.planStatusExecuted")
    normalized_rows = []
    for row in list(rows or []):
        merged = dict(row) if isinstance(row, dict) else {}
        merged["status"] = executed_status
        merged["status_detail"] = ""
        merged["status_blocked"] = False
        normalized_rows.append(merged)
    return normalized_rows


def _capture_last_executed_print_snapshot(self, items_to_print):
    items = list(items_to_print or [])
    if not items:
        return None

    grid_state = _build_print_grid_state(self, items)
    table_rows = _build_last_executed_print_table_rows(self, items)
    return {
        "items": deepcopy(items),
        "grid_state": deepcopy(grid_state),
        "table_rows": deepcopy(table_rows),
    }


def _build_print_grid_state(self, items_to_print):
    grid_state = None
    if hasattr(self, "_overview_panel_ref") and self._overview_panel_ref:
        try:
            from app_gui.plan_model import (
                extract_grid_state_for_print,
                apply_operation_markers_to_grid,
            )

            grid_state = extract_grid_state_for_print(self._overview_panel_ref)
            grid_state = apply_operation_markers_to_grid(grid_state, items_to_print)
        except Exception as exc:
            print(f"Warning: Could not extract grid state: {exc}")
    return grid_state


def _build_print_table_rows(self, items_to_print):
    """Build print-table rows using the same semantics as plan table."""
    from app_gui.ui import operations_panel_plan_table as _ops_plan_table

    rows = []
    fields = self._current_custom_fields if isinstance(self._current_custom_fields, list) else []
    for item in list(items_to_print or []):
        try:
            rows.append(_ops_plan_table._build_plan_row_semantics(self, item, custom_fields=fields))
        except Exception:
            # Defensive fallback: print should still work when row enrichment fails.
            action_text = str(item.get("action", "") or "")
            rows.append(
                {
                    "action_norm": action_text.lower(),
                    "action": action_text,
                    "target": "",
                    "date": "",
                    "changes": "",
                    "changes_detail": "",
                    "status": "",
                    "status_detail": "",
                    "status_blocked": False,
                }
            )
    return rows


def _print_operation_sheet_with_grid(self, items, grid_state, *, table_rows=None, opened_message=None):
    """Open operation sheet in the system browser for printing."""
    if opened_message is None:
        opened_message = tr("operations.operationSheetOpened")

    from app_gui.plan_model import render_operation_sheet_with_grid
    from app_gui.ui.utils import open_html_in_browser

    html = render_operation_sheet_with_grid(items, grid_state, table_rows=table_rows)
    open_html_in_browser(html)
    self.status_message.emit(opened_message, 2000, "info")


def clear_plan(self):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
        return
    cleared_items = self._plan_store.clear()
    _ops_plan_store._reset_plan_feedback_and_validation(self)
    _ops_plan_toolbar._refresh_after_plan_items_changed(self)
    _ops_plan_store._publish_plan_items_notice(
        self,
        code="plan.cleared",
        text=tr("operations.planCleared"),
        level="info",
        timeout=2000,
        items=cleared_items,
        count_key="cleared_count",
        count_value=len(cleared_items),
    )


def reset_for_dataset_switch(self):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    """Clear transient plan/undo/audit state when switching datasets."""
    self._plan_store.clear()
    _ops_plan_store._reset_plan_feedback_and_validation(self)
    _disable_undo(self, clear_last_executed=True)

    _ops_plan_toolbar._refresh_after_plan_items_changed(self)


def on_export_inventory_csv(self, checked=False, *, parent=None, yaml_path_override=None):
    # Keep tests and monkeypatch points stable on operations_panel module symbols.
    from app_gui.ui import operations_panel as _ops_panel

    _ = checked
    yaml_path = str(yaml_path_override or "").strip() or self.yaml_path_getter()
    from lib.inventory_paths import managed_dataset_name_from_yaml_path
    dataset_name = managed_dataset_name_from_yaml_path(yaml_path) if yaml_path else ""
    base_name = dataset_name or "inventory"
    default_name = f"{base_name}_full_{date.today().isoformat()}.csv"
    suggested_path = default_name
    if yaml_path:
        yaml_abs = os.path.abspath(os.fspath(yaml_path))
        suggested_path = os.path.join(
            os.path.dirname(yaml_abs),
            default_name,
        )

    path, _ = _ops_panel.QFileDialog.getSaveFileName(
        parent or self,
        tr("operations.exportDialogTitle"),
        suggested_path,
        tr("operations.exportCsvFilter"),
    )
    if not path:
        return

    if not str(path).lower().endswith(".csv"):
        path = f"{path}.csv"

    response = self.bridge.export_inventory_csv(
        yaml_path,
        output_path=path,
    )
    payload = response if isinstance(response, dict) else {}
    if payload.get("ok"):
        result = payload.get("result", {})
        exported_path = result.get("path") if isinstance(result, dict) else None
        count = result.get("count") if isinstance(result, dict) else None
        target_path = exported_path or path
        notice_data = {"path": target_path}
        if isinstance(count, int):
            notice_data["count"] = count
            notice_text = tr(
                "operations.exportedToWithCount",
                count=count,
                path=target_path,
            )
        else:
            notice_text = tr("operations.exportedTo", path=target_path)
        from app_gui.ui import operations_panel_execution as _ops_exec

        _ops_exec._publish_system_notice(
            self,
            code="inventory.export.success",
            text=notice_text,
            level="success",
            timeout=3000,
            data=notice_data,
        )
        return

    error_text = localize_error_payload(payload, fallback=tr("operations.unknownError"))
    from app_gui.ui import operations_panel_execution as _ops_exec

    _ops_exec._publish_system_notice(
        self,
        code="inventory.export.failed",
        text=tr(
            "operations.exportFailed",
            error=error_text,
        ),
        level="error",
        timeout=5000,
        data={
            "error_code": payload.get("error_code"),
            "message": error_text,
            "path": path,
        },
    )


def _enable_undo(self, timeout_sec=30):
    """Enable undo countdown while keeping last-result print available."""
    if not self._last_operation_backup:
        self._sync_result_actions()
        return

    # Start countdown timer
    self._undo_remaining = timeout_sec
    if self._undo_timer is not None:
        self._undo_timer.stop()

    self._undo_timer = QTimer(self)
    self._undo_timer.timeout.connect(lambda: _undo_tick(self))
    self._undo_timer.start(1000)
    self._sync_result_actions()


def _update_undo_button_text(self):
    """Update undo button text with countdown."""
    self.undo_btn.setText(
        tr(
            "operations.undoLastWithCountdown",
            operation=tr("operations.undoLast"),
            seconds=self._undo_remaining,
        )
    )


def _undo_tick(self):
    self._undo_remaining -= 1
    if self._undo_remaining <= 0:
        _disable_undo(self)
    else:
        _update_undo_button_text(self)


def _disable_undo(self, *, clear_last_executed=False):
    """Disable undo countdown and optionally clear last executed context."""
    if self._undo_timer is not None:
        self._undo_timer.stop()
        self._undo_timer = None

    self._undo_remaining = 0
    self._last_operation_backup = None
    if clear_last_executed:
        self._last_executed_plan = []
        self._last_executed_print_snapshot = None
    self._sync_result_actions()


def on_undo_last(self):
    from app_gui.ui import operations_panel_confirm as _ops_confirm
    from app_gui.ui import operations_panel_execution as _ops_exec
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar
    from app_gui.ui import operations_panel_results as _ops_results

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
        return
    if not self._last_operation_backup:
        _ops_exec._publish_system_notice(
            self,
            code="undo.unavailable",
            text=tr("operations.noOperationToUndo"),
            level="error",
            timeout=3000,
        )
        return

    yaml_path = os.path.abspath(str(self.yaml_path_getter()))
    confirm_lines = _ops_confirm._build_rollback_confirmation_lines(
        self,
        backup_path=self._last_operation_backup,
        yaml_path=yaml_path,
        include_action_prefix=False,
    )
    if not _ops_confirm._confirm_execute(
        self,
        tr("operations.undo"),
        "\n".join(confirm_lines),
    ):
        return

    executed_plan_backup = list(self._last_executed_plan)
    response = self.bridge.rollback(
        self.yaml_path_getter(),
        backup_path=self._last_operation_backup,
        execution_mode="execute",
    )
    _disable_undo(self, clear_last_executed=True)

    restored_data = None
    if response.get("ok") and executed_plan_backup:
        from app_gui.ui import operations_panel_plan_store as _ops_plan_store

        summary = _ops_plan_store._collect_plan_notice_summary(self, executed_plan_backup)
        restored_data = {
            "restored_count": len(executed_plan_backup),
            "action_counts": summary["action_counts"],
            "sample": summary["sample"],
        }

    _ops_results._handle_response(
        self,
        response,
        tr("operations.undo"),
        notice_code="plan.restored" if restored_data else "undo.result",
        notice_data=restored_data,
        allow_undo_from_backup=False,
    )
    if response.get("ok") and executed_plan_backup:
        self._plan_store.replace_all(executed_plan_backup)
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)
