"""Guidance helpers for AgentToolRunner responses."""

MIGRATION_SESSION_CHECKLIST = "migrate/output/migration_checklist.md"


def _path_scope_hint(self):
    return self._msg(
        "hint.pathOutsideScope",
        "Path is outside repository scope. Use repository-relative paths only.",
    )


def _write_scope_hint(self):
    return self._msg(
        "hint.writeNotAllowed",
        "Write operations are allowed only under migrate/.",
    )


def _hint_for_error(self, tool_name, payload):
    error_code = str(payload.get("error_code") or "").strip()
    input_schema = self._tool_input_schema(tool_name)
    required_fields, optional_fields = self._tool_input_field_sets(tool_name)

    if tool_name == "validate_migration_output" and error_code in {
        "validation_failed",
        "file_not_found",
        "load_failed",
    }:
        return ""

    if tool_name == "add_entry" and error_code in {
        "invalid_tool_input",
        "forbidden_fields",
        "missing_required_fields",
        "validation_failed",
    }:
        required_text = ", ".join(required_fields) if required_fields else "(none)"
        optional_text = ", ".join(optional_fields) if optional_fields else "(none)"
        return self._msg(
            "hint.addEntrySharedFields",
            "`add_entry` uses one shared `fields` object for all `positions` in that call. It does not support per-position cell_line/note. Split into multiple add_entry calls (or staged items) when metadata differs. Required: {required_text}. Optional: {optional_text}.",
            required_text=required_text,
            optional_text=optional_text,
        )

    if error_code == "invalid_tool_input":
        required_text = ", ".join(required_fields) if required_fields else "(none)"
        optional_text = ", ".join(optional_fields) if optional_fields else "(none)"
        return self._msg(
            "hint.invalidToolInput",
            "Input does not match `{tool_name}` schema. Fix field names/types first, then retry. Required: {required_text}. Optional: {optional_text}.",
            tool_name=tool_name,
            required_text=required_text,
            optional_text=optional_text,
        )

    if error_code == "unknown_tool":
        available = payload.get("available_tools") or self.list_tools()
        available_text = ", ".join(str(name) for name in available)
        return self._msg(
            "hint.unknownTool",
            "Use one of available tools: {available_text}.",
            available_text=available_text,
        )

    if error_code == "invalid_mode":
        return self._msg(
            "hint.invalidMode",
            "For `search_records`, use mode: fuzzy / exact / keywords.",
        )

    if error_code in {"load_failed", "write_failed", "rollback_failed", "backup_load_failed"}:
        return self._msg(
            "hint.pathOrPermission",
            "Verify yaml_path exists and file permissions are correct, then retry.",
        )

    if error_code == "write_requires_execute_mode":
        return self._msg(
            "hint.writeRequiresExecuteMode",
            "Write tools are execute-gated. Stage operations first, then let a human run Execute in GUI Plan tab.",
        )

    if error_code == "record_not_found":
        return self._msg(
            "hint.recordNotFound",
            "Call `search_records` first and use a valid `record_id` from results.",
        )

    if error_code == "position_not_found":
        return self._msg(
            "hint.positionNotFound",
            "Use a position that belongs to the target record.",
        )

    if error_code == "position_conflict":
        return self._msg(
            "hint.positionConflict",
            "Choose free slots via `list_empty_positions` or `recommend_positions`, then retry.",
        )

    if error_code == "box_not_empty":
        return self._msg(
            "hint.boxNotEmpty",
            "Remove all active tubes from that box first, then retry remove operation.",
        )

    if error_code in {"renumber_mode_required", "invalid_renumber_mode"}:
        return self._msg(
            "hint.renumberModeRequired",
            "When removing a middle box, choose renumber_mode: keep_gaps or renumber_contiguous.",
        )

    if error_code == "min_box_count":
        return self._msg(
            "hint.minBoxCount",
            "At least one box must remain; do not remove the last box.",
        )

    if error_code == "user_cancelled":
        return self._msg(
            "hint.userCancelled",
            "User cancelled the confirmation dialog.",
        )

    if error_code == "terminal_timeout":
        return self._msg(
            "hint.terminalTimeout",
            "Terminal command timed out. Simplify the command or run a shorter non-interactive step first.",
        )

    if error_code in {"terminal_exec_failed", "terminal_nonzero_exit"}:
        return self._msg(
            "hint.terminalExecFailed",
            "Check `raw_output` for terminal details, fix the command, then retry.",
        )

    if error_code == "bash_unavailable":
        return self._msg(
            "hint.bashUnavailable",
            "`bash` is unavailable in current runtime. Use `powershell` tool or install bash.",
        )

    if error_code == "powershell_unavailable":
        return self._msg(
            "hint.powershellUnavailable",
            "`powershell` is unavailable in current runtime. Use `bash` tool or install PowerShell.",
        )

    if error_code in {"path_outside_scope", "path.escape_detected", "path.scope_read_denied"}:
        return _path_scope_hint(self)

    if error_code in {"write_not_allowed", "path.scope_write_denied", "path.scope_workdir_denied"}:
        return _write_scope_hint(self)

    if error_code == "path.absolute_not_allowed":
        return _path_scope_hint(self)

    if error_code == "path.backup_scope_denied":
        return self._msg(
            "hint.backupNotInTimeline",
            "Selected backup_path is not in timeline backup events. Re-select from `list_audit_timeline` action=backup rows.",
        )

    if error_code in {"path_not_found", "path_not_directory", "path_is_directory"}:
        return self._msg(
            "hint.pathTypeMismatch",
            "Verify the target path exists and matches required file/directory type.",
        )

    if error_code in {"file_ops_service_failed", "file_ops_service_timeout", "file_ops_invalid_response"}:
        return self._msg(
            "hint.fileOpsServiceFailed",
            "File operation service failed. Retry once; if it persists, inspect service/runtime configuration.",
        )

    if error_code == "file_exists_and_overwrite_false":
        return self._msg(
            "hint.fileExistsNoOverwrite",
            "Destination already exists. Set `overwrite=true` if replacement is intended.",
        )

    if error_code == "invalid_move_target":
        return self._msg(
            "hint.invalidMoveTarget",
            "For move operations, provide a valid `to_position` different from source position.",
        )

    if error_code in {"invalid_date"}:
        return self._msg(
            "hint.invalidDate",
            "Use date format `YYYY-MM-DD` (for example: 2026-02-10).",
        )

    if error_code in {"invalid_box", "invalid_position", "invalid_record_id"}:
        return self._msg(
            "hint.invalidBoxOrPositionOrRecordId",
            "Provide valid box IDs and valid positions in the current layout (e.g. 12 or A1).",
        )

    if error_code == "invalid_action":
        return self._msg(
            "hint.invalidAction",
            "Use a supported action value: takeout / move.",
        )

    if error_code in {"empty_positions", "empty_entries"}:
        return self._msg(
            "hint.emptyPositionsOrEntries",
            "Provide at least one target position or entry before retrying.",
        )

    if error_code == "missing_backup_path":
        return self._msg(
            "hint.backupPathRequired",
            "Provide explicit `backup_path` from `list_audit_timeline` before calling rollback.",
        )

    if error_code == "backup_not_in_timeline":
        return self._msg(
            "hint.backupNotInTimeline",
            "Selected backup_path is not in timeline backup events. Re-select from `list_audit_timeline` action=backup rows.",
        )

    if error_code == "missing_audit_seq":
        return self._msg(
            "hint.missingAuditSeq",
            "Selected backup event has no valid audit_seq. Do not infer by timestamp; pick a backup row with audit_seq.",
        )

    if error_code == "no_backups":
        return self._msg(
            "hint.noBackups",
            "No backups exist yet in audit timeline. Use `list_audit_timeline` as source of truth before choosing a rollback backup_path.",
        )

    if error_code in {"validation_failed", "integrity_validation_failed", "rollback_backup_invalid"}:
        return self._msg(
            "hint.validationOrRollbackInvalid",
            "Rollback target is invalid for current file state. Re-select backup_path from `list_audit_timeline` and retry.",
        )

    if error_code == "plan_preflight_failed":
        record_ids = self._extract_record_ids_from_payload(
            payload.get("message"),
            payload.get("blocked_items"),
            payload.get("errors"),
            payload.get("repair_candidates"),
        )
        if record_ids:
            ids_text = ", ".join(str(i) for i in record_ids[:12])
            return self._msg(
                "hint.planPreflightFailedWithIds",
                "Preflight failed due to baseline integrity issues. Fetch affected records with `get_raw_entries` ids=[{ids_text}], then repair invalid fields via `edit_entry` (for example, normalize `cell_line` to configured options), and retry staging.",
                ids_text=ids_text,
            )
        return self._msg(
            "hint.planPreflightFailedNoIds",
            "One or more write operations are invalid against current inventory state. Review blocked details, then retry only corrected operations.",
        )

    if input_schema:
        return self._msg(
            "hint.adjustInputByToolSchema",
            "Adjust `{tool_name}` inputs according to the tool schema, then retry.",
            tool_name=tool_name,
        )
    return self._msg(
        "hint.retryWithCorrectedInput",
        "Retry with corrected tool input.",
    )


def merge_hint_text(*values):
    seen = set()
    ordered = []
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return "\n".join(ordered)


def _with_hint(self, tool_name, response):
    if not isinstance(response, dict):
        response = {
            "ok": False,
            "error_code": "invalid_tool_response",
            "message": self._msg(
                "response.nonDict",
                "Tool `{tool_name}` returned non-dict response.",
                tool_name=tool_name,
            ),
        }

    response = dict(response)
    existing_hint = response.get("_hint")
    generated_hint = ""
    if response.get("ok") is False:
        generated_hint = self._hint_for_error(tool_name, response)

    merged_hint = merge_hint_text(existing_hint, generated_hint)
    if merged_hint:
        response["_hint"] = merged_hint
    else:
        response.pop("_hint", None)
    return response
