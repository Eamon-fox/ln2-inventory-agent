"""Result rendering and notice helpers for OperationsPanel."""

import os

from app_gui.error_localizer import localize_error_payload


def _tr(key, **kwargs):
    # Keep tests and monkeypatch points stable on operations_panel.tr.
    from app_gui.ui import operations_panel as _ops_panel

    return _ops_panel.tr(key, **kwargs)


def _handle_response(
    self,
    response,
    context,
    *,
    notice_code=None,
    notice_data=None,
    allow_undo_from_backup=True,
):
    payload = response if isinstance(response, dict) else {}
    self._display_result_summary(response, context)

    ok = payload.get("ok", False)
    msg = localize_error_payload(payload, fallback=_tr("operations.unknownResult"))
    code = str(notice_code or ("operation.success" if ok else "operation.failed"))

    if ok:
        self._publish_system_notice(
            code=code,
            text=_tr("operations.contextSuccess", context=context),
            level="success",
            timeout=3000,
            data=notice_data if isinstance(notice_data, dict) else None,
        )
        self.operation_completed.emit(True)
        backup_path = payload.get("backup_path")
        if backup_path and allow_undo_from_backup:
            self._last_operation_backup = backup_path
            self._enable_undo(timeout_sec=30)
    else:
        self._publish_system_notice(
            code=code,
            text=_tr("operations.contextFailed", context=context, error=msg),
            level="error",
            timeout=5000,
            data=notice_data
            if isinstance(notice_data, dict)
            else {"message": msg, "error_code": payload.get("error_code")},
        )
        self.operation_completed.emit(False)


def _result_header_html(context, *, ok):
    color = "success" if ok else "error"
    key = "operations.contextResultSuccess" if ok else "operations.contextResultFailed"
    return f"<b style='color: var(--status-{color});'>{_tr(key, context=context)}</b>"


def _build_add_entry_result_lines(self, preview, result):
    new_ids = result.get("new_ids") or []
    new_id = result.get("new_id", "?")
    fields = preview.get("fields") or {}
    from lib.custom_fields import get_display_key

    dk = get_display_key(None)
    cell = str(fields.get("cell_line", ""))
    short = str(fields.get(dk, ""))
    box = preview.get("box", "")
    positions = preview.get("positions", [])
    pos_text = self._positions_to_display_text(positions)
    if new_ids:
        ids_text = ", ".join(str(i) for i in new_ids)
        return [
            _tr(
                "operations.addedTubesSummary",
                count=len(new_ids),
                ids=ids_text,
                cell=cell,
                short=short,
                box=box,
                positions=pos_text,
            )
        ]
    return [
        _tr(
            "operations.addedTubeSummary",
            id=new_id,
            cell=cell,
            short=short,
            box=box,
            positions=pos_text,
        )
    ]


def _build_single_operation_result_lines(self, preview):
    rid = preview.get("record_id", "?")
    action = preview.get("action_en", preview.get("action_cn", ""))
    pos = self._position_to_display(preview.get("position", "?"))
    to_pos = preview.get("to_position")
    before = preview.get("positions_before", [])
    after = preview.get("positions_after", [])
    lines = []
    if to_pos is not None:
        lines.append(
            _tr(
                "operations.operationRowActionWithTarget",
                rid=rid,
                action=action,
                pos=pos,
                to_pos=self._position_to_display(to_pos),
            )
        )
    else:
        lines.append(
            _tr("operations.operationRowActionWithPosition", rid=rid, action=action, pos=pos)
        )
    if before or after:
        lines.append(
            _tr(
                "operations.operationPositionsTransition",
                before=self._positions_to_display_text(before),
                after=self._positions_to_display_text(after),
            )
        )
    return lines


def _build_batch_operation_result_lines(preview, result):
    count = result.get("count", preview.get("count", 0))
    ids = result.get("record_ids", [])
    return [
        _tr(
            "operations.processedBatchEntries",
            count=count,
            ids=", ".join(str(i) for i in ids),
        )
    ]


def _build_restore_result_lines(result):
    restored = result.get("restored_from", "?")
    return [_tr("operations.restoredFrom", path=os.path.basename(str(restored)))]


def _build_success_result_lines(self, context, preview, result):
    if context == "Add Entry":
        return self._build_add_entry_result_lines(preview, result)
    if context == "Single Operation":
        return self._build_single_operation_result_lines(preview)
    if context == "Batch Operation":
        return self._build_batch_operation_result_lines(preview, result)
    if context == "Rollback" or context == "Undo":
        return self._build_restore_result_lines(result)
    return []


def _display_result_summary(self, response, context):
    """Show a human-readable summary card for the operation result."""
    payload = response if isinstance(response, dict) else {}
    ok = payload.get("ok", False)
    preview = payload.get("preview", {}) or {}
    result = payload.get("result", {}) or {}

    if ok:
        lines = [self._result_header_html(context, ok=True)]
        lines.extend(self._build_success_result_lines(context, preview, result))
        self._show_result_card(lines, "success")
    else:
        msg = localize_error_payload(payload, fallback=_tr("operations.unknownError"))
        error_code = payload.get("error_code", "")
        lines = [self._result_header_html(context, ok=False)]
        lines.append(str(msg))
        if error_code:
            lines.append(
                f"<span style='color: var(--status-muted);'>{_tr('operations.codeLabel', code=error_code)}</span>"
            )
        self._show_result_card(lines, "error")
