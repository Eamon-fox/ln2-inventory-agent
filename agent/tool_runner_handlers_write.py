"""Write-oriented dispatch handlers for AgentToolRunner."""

from lib import tool_api_write_adapter as _write_adapter
from lib.box_layout_requests import normalize_manage_boxes_request
from lib.path_policy import PathPolicyError, resolve_dataset_backup_read_path
from lib.schema_aliases import coalesce_stored_at_value
from lib.tool_api import tool_list_audit_timeline


def _coerce_positive_int(value):
    try:
        num = int(value)
    except Exception:
        return None
    if num <= 0:
        return None
    return num


def _validate_rollback_backup_candidate(yaml_path, backup_path):
    target_path = str(backup_path or "").strip()
    if not target_path:
        return {
            "ok": False,
            "error_code": "missing_backup_path",
            "message": "backup_path must be a non-empty string",
        }
    try:
        target_abs = str(
            resolve_dataset_backup_read_path(
                yaml_path=yaml_path,
                raw_path=target_path,
                must_exist=True,
                must_be_file=True,
            )
        )
    except PathPolicyError as exc:
        payload = {
            "ok": False,
            "error_code": exc.code,
            "message": exc.message,
        }
        if exc.resolved_path:
            payload["resolved_path"] = exc.resolved_path
        return payload

    timeline = tool_list_audit_timeline(
        yaml_path=yaml_path,
        limit=None,
        offset=0,
        action_filter="backup",
        status_filter="success",
    )
    if not isinstance(timeline, dict) or not timeline.get("ok"):
        message = "Failed to load audit timeline for rollback target validation."
        if isinstance(timeline, dict):
            message = str(timeline.get("message") or message)
        return {
            "ok": False,
            "error_code": "audit_timeline_unavailable",
            "message": message,
        }

    for event in list((timeline.get("result") or {}).get("items") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("action") or "").strip().lower() != "backup":
            continue
        candidate_path = str(event.get("backup_path") or "").strip()
        if not candidate_path:
            continue
        try:
            candidate_abs = str(resolve_dataset_backup_read_path(yaml_path=yaml_path, raw_path=candidate_path))
        except PathPolicyError:
            continue
        if candidate_abs != target_abs:
            continue
        if _coerce_positive_int(event.get("audit_seq")) is None:
            return {
                "ok": False,
                "error_code": "missing_audit_seq",
                "message": "Rollback target is missing audit_seq. Re-select a backup from timeline entries with valid audit_seq.",
            }
        return None

    return {
        "ok": False,
        "error_code": "backup_not_in_timeline",
        "message": "backup_path is not found in backup audit events. Re-select backup_path from list_audit_timeline action=backup rows.",
    }


def _run_manage_boxes(self, payload, trace_id=None):
    tool_name = "manage_boxes"

    def _call_manage_boxes():
        issue, normalized = normalize_manage_boxes_request(payload)
        if issue:
            label = "action" if issue.get("error_code") == "invalid_operation" else "renumber_mode"
            if issue.get("error_code") in {"invalid_operation", "invalid_renumber_mode"}:
                values = "add, remove" if label == "action" else "keep_gaps, renumber_contiguous"
                raise ValueError(
                    self._msg(
                        "validation.mustBeOneOf",
                        "{label} must be one of: {values}",
                        label=label,
                        values=values,
                    )
                )
            raise ValueError(str(issue.get("message") or "Invalid manage boxes request"))

        action = normalized.get("operation")
        dry_run = self._as_bool(payload.get("dry_run", False), default=False)
        if action == "add":
            count = normalized.get("count")
            request = {
                "operation": "add",
                "count": count,
                "box": None,
                "renumber_mode": None,
            }
            if dry_run:
                return _write_adapter.manage_boxes(
                    yaml_path=self._yaml_path,
                    operation="add",
                    count=count,
                    dry_run=True,
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                    backup_event_source="agent.react",
                    default_execute=True,
                )
        else:
            box = normalized.get("box")
            renumber_mode = normalized.get("renumber_mode")
            request = {
                "operation": "remove",
                "count": None,
                "box": box,
                "renumber_mode": renumber_mode,
            }
            if dry_run:
                call_kwargs = {
                    "operation": "remove",
                    "box": box,
                    "dry_run": True,
                    "actor_context": self._actor_context(trace_id=trace_id),
                    "source": "agent.react",
                    "backup_event_source": "agent.react",
                    "default_execute": True,
                }
                if renumber_mode not in (None, ""):
                    call_kwargs["renumber_mode"] = renumber_mode
                return _write_adapter.manage_boxes(
                    yaml_path=self._yaml_path,
                    **call_kwargs,
                )

        return {
            "ok": True,
            "waiting_for_user_confirmation": True,
            "request": request,
            "message": self._msg(
                "manageBoxes.awaitingUserConfirmation",
                "Awaiting user confirmation in GUI.",
            ),
        }

    return self._safe_call(tool_name, _call_manage_boxes, include_expected_schema=True)


def _run_edit_entry(self, payload, trace_id=None):
    tool_name = "edit_entry"

    def _call_edit_entry():
        rid = self._required_int(payload, "record_id")
        fields = payload.get("fields")
        if not fields or not isinstance(fields, dict):
            raise ValueError(
                self._msg(
                    "errors.fieldsMustBeNonEmptyObject",
                    "fields must be a non-empty object",
                )
            )
        return _write_adapter.edit_entry(
            yaml_path=self._yaml_path,
            record_id=rid,
            fields=fields,
            dry_run=self._as_bool(payload.get("dry_run", False), default=False),
            request_backup_path=payload.get("request_backup_path"),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            backup_event_source="agent.react",
            default_execute=True,
        )

    return self._safe_call(tool_name, _call_edit_entry, include_expected_schema=True)


def _run_add_entry(self, payload, trace_id=None):
    tool_name = "add_entry"

    def _call_add_entry():
        layout = self._load_layout()
        box_val = self._required_int(payload, "box")
        stored_at = coalesce_stored_at_value(
            stored_at=payload.get("stored_at"),
            frozen_at=payload.get("frozen_at"),
        )
        positions = self._normalize_positions(payload.get("positions"), layout=layout)
        tool_positions = _write_adapter.to_tool_positions(positions, layout, field_name="positions")
        fields = dict(payload.get("fields") or {})

        return _write_adapter.add_entry(
            yaml_path=self._yaml_path,
            box=box_val,
            positions=tool_positions,
            stored_at=stored_at,
            fields=fields,
            dry_run=self._as_bool(payload.get("dry_run", False), default=False),
            request_backup_path=payload.get("request_backup_path"),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            backup_event_source="agent.react",
            default_execute=True,
        )

    return self._safe_call(tool_name, _call_add_entry, include_expected_schema=True)


def _parse_batch_flat_entries(self, raw_entries, *, layout, include_target):
    entries = []
    for idx, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ValueError(
                self._msg(
                    "validation.mustBeObject",
                    "{label} must be an object",
                    label=f"entries[{idx}]",
                )
            )

        parsed = {
            "record_id": self._required_int(entry, "record_id"),
            "from": {
                "box": self._required_int(entry, "from_box"),
                "position": _write_adapter.to_tool_position(
                    self._parse_position(
                        entry.get("from_position"),
                        layout=layout,
                        field_name=f"entries[{idx}].from_position",
                    ),
                    layout,
                    field_name=f"entries[{idx}].from_position",
                ),
            },
        }
        if include_target:
            parsed["to"] = {
                "box": self._required_int(entry, "to_box"),
                "position": _write_adapter.to_tool_position(
                    self._parse_position(
                        entry.get("to_position"),
                        layout=layout,
                        field_name=f"entries[{idx}].to_position",
                    ),
                    layout,
                    field_name=f"entries[{idx}].to_position",
                ),
            }
        entries.append(parsed)
    return entries


def _call_batch_flat_tool(self, payload, trace_id, *, tool_fn, include_target):
    layout = self._load_layout()
    entries = _parse_batch_flat_entries(
        self,
        payload.get("entries") or [],
        layout=layout,
        include_target=include_target,
    )
    return tool_fn(
        yaml_path=self._yaml_path,
        entries=entries,
        date_str=payload.get("date"),
        dry_run=self._as_bool(payload.get("dry_run", False), default=False),
        request_backup_path=payload.get("request_backup_path"),
        actor_context=self._actor_context(trace_id=trace_id),
        source="agent.react",
        backup_event_source="agent.react",
        default_execute=True,
    )


def _run_takeout(self, payload, trace_id=None):
    tool_name = "takeout"

    def _call_takeout():
        return _call_batch_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=_write_adapter.takeout,
            include_target=False,
        )

    return self._safe_call(tool_name, _call_takeout, include_expected_schema=True)


def _run_move(self, payload, trace_id=None):
    tool_name = "move"

    def _call_move():
        return _call_batch_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=_write_adapter.move,
            include_target=True,
        )

    return self._safe_call(tool_name, _call_move, include_expected_schema=True)


def _run_rollback(self, payload, trace_id=None):
    tool_name = "rollback"

    def _call_rollback():
        issue = _validate_rollback_backup_candidate(
            self._yaml_path,
            payload.get("backup_path"),
        )
        if issue:
            return issue
        return _write_adapter.rollback(
            yaml_path=self._yaml_path,
            backup_path=payload.get("backup_path"),
            dry_run=self._as_bool(payload.get("dry_run", False), default=False),
            request_backup_path=payload.get("request_backup_path"),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            backup_event_source="agent.react",
            default_execute=True,
        )

    return self._safe_call(tool_name, _call_rollback)
