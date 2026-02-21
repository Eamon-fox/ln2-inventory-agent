"""Action helpers for OperationsPanel print/export/undo flows."""

import os
from datetime import date

from PySide6.QtCore import QTimer

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr
from app_gui.ui.utils import open_html_in_browser


def _print_items_with_grid(self, items_to_print, *, empty_message, opened_message):
    if not items_to_print:
        self.status_message.emit(str(empty_message), 3000, "error")
        return

    grid_state = self._build_print_grid_state(items_to_print)
    self._print_operation_sheet_with_grid(
        items_to_print,
        grid_state,
        opened_message=str(opened_message),
    )


def print_plan(self):
    """Print current staged plan (not yet executed)."""
    self._print_items_with_grid(
        self._plan_store.list_items(),
        empty_message=tr("operations.noCurrentPlanToPrint"),
        opened_message=tr("operations.planPrintOpened"),
    )


def print_last_executed(self):
    """Print the last successfully applied execution result."""
    self._print_items_with_grid(
        self._last_executed_plan,
        empty_message=tr("operations.noLastExecutedToPrint"),
        opened_message=tr("operations.guideOpened"),
    )


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


def _print_operation_sheet_with_grid(self, items, grid_state, opened_message=None):
    """Print operation sheet with grid visualization."""
    if opened_message is None:
        opened_message = tr("operations.operationSheetOpened")

    # Keep tests and monkeypatch points stable on operations_panel module symbols.
    from app_gui.ui import operations_panel as _ops_panel
    from app_gui.plan_model import render_operation_sheet_with_grid

    html = render_operation_sheet_with_grid(items, grid_state)
    open_html_in_browser(html, open_url_fn=_ops_panel.QDesktopServices.openUrl)
    self.status_message.emit(opened_message, 2000, "info")


def clear_plan(self):
    cleared_items = self._plan_store.clear()
    self._reset_plan_feedback_and_validation()
    self._refresh_after_plan_items_changed()
    self._publish_plan_items_notice(
        code="plan.cleared",
        text=tr("operations.planCleared"),
        level="info",
        timeout=2000,
        items=cleared_items,
        count_key="cleared_count",
        count_value=len(cleared_items),
    )


def reset_for_dataset_switch(self):
    """Clear transient plan/undo/audit state when switching datasets."""
    self._plan_store.clear()
    self._reset_plan_feedback_and_validation()
    self._disable_undo(clear_last_executed=True)

    self._refresh_after_plan_items_changed()


def on_export_inventory_csv(self):
    # Keep tests and monkeypatch points stable on operations_panel module symbols.
    from app_gui.ui import operations_panel as _ops_panel

    yaml_path = self.yaml_path_getter()
    default_name = f"inventory_full_{date.today().isoformat()}.csv"
    suggested_path = default_name
    if yaml_path:
        yaml_abs = os.path.abspath(os.fspath(yaml_path))
        base_name = os.path.splitext(os.path.basename(yaml_abs))[0] or "inventory"
        suggested_path = os.path.join(
            os.path.dirname(yaml_abs),
            f"{base_name}_full_{date.today().isoformat()}.csv",
        )

    path, _ = _ops_panel.QFileDialog.getSaveFileName(
        self,
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
        self._publish_system_notice(
            code="inventory.export.success",
            text=notice_text,
            level="success",
            timeout=3000,
            data=notice_data,
        )
        return

    error_text = localize_error_payload(payload, fallback=tr("operations.unknownError"))
    self._publish_system_notice(
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
    self._undo_timer.timeout.connect(self._undo_tick)
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
        self._disable_undo()
    else:
        self._update_undo_button_text()


def _disable_undo(self, *, clear_last_executed=False):
    """Disable undo countdown and optionally clear last executed context."""
    if self._undo_timer is not None:
        self._undo_timer.stop()
        self._undo_timer = None

    self._undo_remaining = 0
    self._last_operation_backup = None
    if clear_last_executed:
        self._last_executed_plan = []
    self._sync_result_actions()


def on_undo_last(self):
    if not self._last_operation_backup:
        self._publish_system_notice(
            code="undo.unavailable",
            text=tr("operations.noOperationToUndo"),
            level="error",
            timeout=3000,
        )
        return

    yaml_path = os.path.abspath(str(self.yaml_path_getter()))
    confirm_lines = self._build_rollback_confirmation_lines(
        backup_path=self._last_operation_backup,
        yaml_path=yaml_path,
        include_action_prefix=False,
    )
    if not self._confirm_execute(
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
    self._disable_undo(clear_last_executed=True)

    restored_data = None
    if response.get("ok") and executed_plan_backup:
        summary = self._collect_plan_notice_summary(executed_plan_backup)
        restored_data = {
            "restored_count": len(executed_plan_backup),
            "action_counts": summary["action_counts"],
            "sample": summary["sample"],
        }

    self._handle_response(
        response,
        tr("operations.undo"),
        notice_code="plan.restored" if restored_data else "undo.result",
        notice_data=restored_data,
    )
    if response.get("ok") and executed_plan_backup:
        self._plan_store.replace_all(executed_plan_backup)
        self._refresh_after_plan_items_changed()
