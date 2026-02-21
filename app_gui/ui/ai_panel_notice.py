"""System notice formatting helpers for AIPanel."""

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr


def _format_blocked_item(item):
    action = str(item.get("action") or "?")
    rid = item.get("record_id")
    box = item.get("box")
    pos = item.get("position")
    to_pos = item.get("to_position")
    to_box = item.get("to_box")

    id_text = f"ID {rid}" if rid not in (None, "") else "NEW"
    location = "unknown"
    if box not in (None, "") and pos not in (None, ""):
        location = f"Box {box}:{pos}"
    elif pos not in (None, ""):
        location = f"Pos {pos}"

    if action == "move" and to_pos not in (None, ""):
        if to_box not in (None, ""):
            location = f"{location} -> Box {to_box}:{to_pos}"
        else:
            location = f"{location} -> {to_pos}"

    return f"{action} ({id_text}, {location})"


def _blocked_items_summary(self, tool_name, blocked_items):
    count = len(blocked_items)
    lines = [f"**Tool blocked** `{tool_name}`: {count} item(s) failed validation"]
    for item in blocked_items[:3]:
        payload = item if isinstance(item, dict) else {}
        desc = self._format_blocked_item(payload)
        message = localize_error_payload(payload, fallback="Validation failed")
        lines.append(f"- {desc}: {message}")
    if count > 3:
        lines.append(f"- ... and {count - 3} more")
    return "\n".join(lines)


def _single_line_text(value, limit=180):
    text = str(value or "").strip()
    text = " | ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def _trf(key, default, **kwargs):
    """Translate and format with safe fallback when locale catalog is not loaded."""
    text = tr(key, default=default)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def _format_notice_operation(self, item, row=None):
    payload = item.get("payload") if isinstance(item, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}

    desc = self._format_blocked_item(item if isinstance(item, dict) else {})
    cell_line = item.get("cell_line") if isinstance(item, dict) else None
    short_name = item.get("short_name") if isinstance(item, dict) else None
    if cell_line in (None, ""):
        cell_line = fields.get("cell_line")
    if short_name in (None, ""):
        short_name = fields.get("short_name")

    if isinstance(row, dict):
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        preview = response.get("preview") if isinstance(response.get("preview"), dict) else {}
        operations = preview.get("operations") if isinstance(preview.get("operations"), list) else []
        if operations and isinstance(operations[0], dict):
            op0 = operations[0]
            if cell_line in (None, ""):
                cell_line = op0.get("cell_line")
            if short_name in (None, ""):
                short_name = op0.get("short_name")

    tags = []
    if cell_line not in (None, ""):
        tags.append(f"cell_line={cell_line}")
    if short_name not in (None, ""):
        tags.append(f"short_name={short_name}")
    if tags:
        desc += " | " + ", ".join(tags)
    return desc


def _extract_notice_operation_lines(self, code, data):
    sample = data.get("sample") if isinstance(data.get("sample"), list) else []
    sample_lines = [self._single_line_text(v, limit=180) for v in sample if str(v or "").strip()]
    if sample_lines:
        return sample_lines

    if code == "record.edit.saved":
        rid = data.get("record_id")
        rid_text = f"ID {rid}" if rid not in (None, "") else "ID ?"
        field = str(data.get("field") or "field")
        before = self._single_line_text(data.get("before"), limit=80)
        after = self._single_line_text(data.get("after"), limit=80)
        return [f"edit ({rid_text}) | {field}: {before} -> {after}"]

    if code == "plan.stage.blocked":
        blocked_items = data.get("blocked_items") if isinstance(data.get("blocked_items"), list) else []
        lines = []
        for blocked in blocked_items[:8]:
            payload = blocked if isinstance(blocked, dict) else {}
            desc = self._format_notice_operation(payload)
            message = localize_error_payload(payload, fallback="")
            if message:
                desc += f" | {self._single_line_text(message, limit=140)}"
            lines.append(desc)
        return lines

    if code == "plan.execute.result":
        report = data.get("report") if isinstance(data.get("report"), dict) else {}
        report_items = report.get("items") if isinstance(report.get("items"), list) else []
        lines = []
        for row in report_items[:8]:
            row_data = row if isinstance(row, dict) else {}
            item = row_data.get("item") if isinstance(row_data.get("item"), dict) else {}
            if not item:
                continue
            is_ok = bool(row_data.get("ok"))
            if is_ok:
                status = tr("ai.systemNotice.statusOk", default="OK")
            elif row_data.get("blocked"):
                status = tr("ai.systemNotice.statusBlocked", default="BLOCKED")
            else:
                status = tr("ai.systemNotice.statusFail", default="FAIL")
            line = self._trf(
                "ai.systemNotice.operationStatusLine",
                default="{status}: {operation}",
                status=status,
                operation=self._format_notice_operation(item, row=row_data),
            )
            if not is_ok:
                message = localize_error_payload(row_data, fallback="")
                if not message:
                    response = row_data.get("response") if isinstance(row_data.get("response"), dict) else {}
                    message = localize_error_payload(response, fallback=response.get("message"))
                if message:
                    line += f" | {self._single_line_text(message, limit=140)}"
            lines.append(line)
        return lines

    items = data.get("items") if isinstance(data.get("items"), list) else []
    lines = []
    for item in items[:8]:
        if isinstance(item, dict):
            lines.append(self._format_notice_operation(item))
    return lines


def _format_system_notice_details(self, event):
    """Render system_notice details with operations first and meta last."""
    code = str(event.get("code") or "notice")
    level = str(event.get("level") or "info")
    text = str(event.get("text") or "").strip()
    timestamp = event.get("timestamp")

    lines = []
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    op_lines = self._extract_notice_operation_lines(code, data) if data else []
    meta_lines = self._extract_notice_meta_lines(code, data) if data else []

    details = event.get("details")
    details_text = ""
    if details and str(details).strip() and str(details).strip() != text:
        details_text = self._single_line_text(details, limit=360)
        if self._should_hide_notice_details_line(code, details_text, op_lines):
            details_text = ""

    if op_lines:
        lines.append(
            self._trf(
                "ai.systemNotice.operationsHeader",
                default="Operations ({count}):",
                count=len(op_lines),
            )
        )
        for op in op_lines[:8]:
            lines.append(f"- {op}")
        if len(op_lines) > 8:
            lines.append(
                "- "
                + self._trf(
                    "ai.systemNotice.andMore",
                    default="... and {count} more",
                    count=len(op_lines) - 8,
                )
            )

    if details_text:
        if lines:
            lines.append("")
        lines.append(
            self._trf(
                "ai.systemNotice.detailsLine",
                default="Details: {details}",
                details=details_text,
            )
        )

    if meta_lines:
        if lines:
            lines.append("")
        lines.extend(meta_lines)

    if not op_lines and not meta_lines and data:
        scalar_lines = []
        for key, value in sorted(data.items()):
            if key == "legacy_event":
                continue
            if isinstance(value, (str, int, float, bool)):
                scalar_lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                scalar_lines.append(f"{key}: <list {len(value)}>")
            elif isinstance(value, dict):
                scalar_lines.append(f"{key}: <object {len(value)} keys>")
        if scalar_lines:
            if lines:
                lines.append("")
            lines.append(tr("ai.systemNotice.dataHeader", default="Data:"))
            lines.extend(scalar_lines[:8])

    if not lines:
        lines.append(text or code)

    meta = [
        f"{tr('ai.systemNotice.metaCode', default='code')}={code}",
        f"{tr('ai.systemNotice.metaLevel', default='level')}={level}",
    ]
    if timestamp:
        meta.append(f"{tr('ai.systemNotice.metaTime', default='time')}={timestamp}")
    lines.append("")
    lines.append(f"{tr('ai.systemNotice.metaHeader', default='Meta')}: " + ", ".join(meta))
    return "\n".join(lines)


def _normalize_notice_lines_for_compare(self, values):
    normalized = []
    for value in values or []:
        text = str(value or "")
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if line:
                normalized.append(line)
    return normalized


def _should_hide_notice_details_line(self, code, details_text, op_lines):
    """Hide Details only when it duplicates operation lines for safe notice types."""
    dedupe_allowed_codes = {
        "plan.stage.accepted",
        "plan.removed",
        "plan.cleared",
        "plan.restored",
    }
    if code not in dedupe_allowed_codes:
        return False

    op_norm = set(self._normalize_notice_lines_for_compare(op_lines))
    if not op_norm:
        return False

    details_norm = self._normalize_notice_lines_for_compare([details_text])
    if not details_norm:
        return False

    return all(line in op_norm for line in details_norm)


def _extract_notice_meta_lines(self, code, data):
    lines = []
    if code == "plan.stage.accepted":
        lines.append(
            self._trf(
                "ai.systemNotice.countsAdded",
                default="Counts: added={added}, total={total}",
                added=int(data.get("added_count") or 0),
                total=int(data.get("total_count") or 0),
            )
        )
    elif code == "plan.removed":
        lines.append(
            self._trf(
                "ai.systemNotice.countsRemoved",
                default="Counts: removed={removed}, total={total}",
                removed=int(data.get("removed_count") or 0),
                total=int(data.get("total_count") or 0),
            )
        )
    elif code == "plan.cleared":
        lines.append(
            self._trf(
                "ai.systemNotice.countsCleared",
                default="Counts: cleared={cleared}",
                cleared=int(data.get("cleared_count") or 0),
            )
        )
    elif code == "plan.restored":
        lines.append(
            self._trf(
                "ai.systemNotice.countsRestored",
                default="Counts: restored={restored}",
                restored=int(data.get("restored_count") or 0),
            )
        )
    elif code == "plan.stage.blocked":
        blocked_items = data.get("blocked_items") if isinstance(data.get("blocked_items"), list) else []
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        lines.append(
            self._trf(
                "ai.systemNotice.countsBlocked",
                default="Counts: blocked={blocked}, total={total}",
                blocked=len(blocked_items),
                total=int(stats.get("total") or 0),
            )
        )
    elif code == "plan.execute.result":
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        lines.append(
            self._trf(
                "ai.systemNotice.statsSummary",
                default="Stats: applied={applied}, failed={failed}, blocked={blocked}, remaining={remaining}, total={total}",
                applied=int(stats.get("applied") or 0),
                failed=int(stats.get("failed") or 0),
                blocked=int(stats.get("blocked") or 0),
                remaining=int(stats.get("remaining") or 0),
                total=int(stats.get("total") or 0),
            )
        )

        rollback = data.get("rollback") if isinstance(data.get("rollback"), dict) else {}
        if rollback:
            if rollback.get("ok"):
                lines.append(
                    tr(
                        "ai.systemNotice.rollbackSucceeded",
                        default="Rollback: succeeded",
                    )
                )
            elif rollback.get("attempted"):
                reason = self._single_line_text(localize_error_payload(rollback))
                lines.append(
                    self._trf(
                        "ai.systemNotice.rollbackFailed",
                        default="Rollback: failed | {reason}",
                        reason=reason,
                    )
                )
            else:
                reason = self._single_line_text(localize_error_payload(rollback))
                lines.append(
                    self._trf(
                        "ai.systemNotice.rollbackUnavailable",
                        default="Rollback: unavailable | {reason}",
                        reason=reason,
                    )
                )

        report = data.get("report") if isinstance(data.get("report"), dict) else {}
        backup_path = report.get("backup_path")
        if backup_path:
            lines.append(
                self._trf(
                    "ai.systemNotice.backupPath",
                    default="Backup: {path}",
                    path=backup_path,
                )
            )

    return lines
