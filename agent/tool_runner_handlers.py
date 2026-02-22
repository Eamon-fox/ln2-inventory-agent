"""Dispatch handlers for AgentToolRunner."""

import os

from lib.tool_api import (
    tool_add_entry,
    tool_adjust_box_count,
    tool_collect_timeline,
    tool_edit_entry,
    tool_generate_stats,
    tool_get_raw_entries,
    tool_list_audit_timeline,
    tool_list_empty_positions,
    tool_move,
    tool_query_takeout_events,
    tool_recent_frozen,
    tool_recommend_positions,
    tool_rollback,
    tool_search_records,
    tool_takeout,
)
from lib.position_fmt import pos_to_display
from lib.tool_api_write_validation import resolve_request_backup_path
from .terminal_tool import run_terminal_command


def _resolve_write_execution_kwargs(self, payload):
    dry_run = self._as_bool(payload.get("dry_run", False), default=False)
    execution_mode = "preflight" if dry_run else "execute"
    kwargs = {
        "dry_run": dry_run,
        "execution_mode": execution_mode,
    }
    if dry_run:
        return kwargs
    kwargs["request_backup_path"] = resolve_request_backup_path(
        yaml_path=self._yaml_path,
        execution_mode=execution_mode,
        dry_run=dry_run,
        request_backup_path=payload.get("request_backup_path"),
        backup_event_source="agent.react",
    )
    kwargs["auto_backup"] = False
    return kwargs


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
    target_abs = os.path.abspath(target_path)

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
        if os.path.abspath(candidate_path) != target_abs:
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


def _to_tool_position(value, layout, *, field_name="position"):
    """Convert normalized internal position to tool-facing display value."""
    if value in (None, "") or isinstance(value, bool):
        raise ValueError(f"{field_name} is required")
    try:
        return pos_to_display(int(value), layout)
    except Exception as exc:
        raise ValueError(f"{field_name} is invalid: {value}") from exc


def _to_tool_positions(values, layout, *, field_name="positions"):
    """Convert normalized one-or-many positions for tool calls."""
    if values in (None, ""):
        raise ValueError(f"{field_name} is required")
    if isinstance(values, bool):
        raise ValueError(f"{field_name} is invalid: {values}")
    if isinstance(values, (list, tuple, set)):
        converted = []
        for idx, value in enumerate(values):
            converted.append(_to_tool_position(value, layout, field_name=f"{field_name}[{idx}]"))
        return converted
    return [_to_tool_position(values, layout, field_name=field_name)]


def _run_manage_boxes(self, payload, trace_id=None):
    tool_name = "manage_boxes"

    def _call_manage_boxes():
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"add", "remove"}:
            raise ValueError(
                self._msg(
                    "validation.mustBeOneOf",
                    "{label} must be one of: {values}",
                    label="action",
                    values="add, remove",
                )
            )

        dry_run = self._as_bool(payload.get("dry_run", False), default=False)

        if action == "add":
            count = self._required_int(payload, "count")
            request = {
                "operation": "add",
                "count": count,
                "box": None,
                "renumber_mode": None,
            }
            if dry_run:
                return tool_adjust_box_count(
                    yaml_path=self._yaml_path,
                    operation="add",
                    count=count,
                    dry_run=True,
                    execution_mode="preflight",
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )
        else:
            box = self._required_int(payload, "box")
            renumber_mode = payload.get("renumber_mode")
            request = {
                "operation": "remove",
                "count": None,
                "box": box,
                "renumber_mode": renumber_mode,
            }
            if dry_run:
                call_kwargs = {
                    "yaml_path": self._yaml_path,
                    "operation": "remove",
                    "box": box,
                    "dry_run": True,
                    "execution_mode": "preflight",
                    "actor_context": self._actor_context(trace_id=trace_id),
                    "source": "agent.react",
                }
                if renumber_mode not in (None, ""):
                    call_kwargs["renumber_mode"] = renumber_mode
                return tool_adjust_box_count(**call_kwargs)

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


def _run_list_empty_positions(self, payload, _trace_id=None):
    tool_name = "list_empty_positions"
    return self._safe_call(
        tool_name,
        lambda: tool_list_empty_positions(
            yaml_path=self._yaml_path,
            box=self._optional_int(payload, "box"),
        ),
    )


def _run_search_records(self, payload, _trace_id=None):
    tool_name = "search_records"
    mode = self._normalize_search_mode(payload.get("mode"))
    layout = self._load_layout()

    position = None
    if payload.get("position") not in (None, ""):
        position = _to_tool_position(
            self._parse_position(
                payload.get("position"),
                layout=layout,
                field_name="position",
            ),
            layout,
            field_name="position",
        )

    return self._safe_call(
        tool_name,
        lambda: tool_search_records(
            yaml_path=self._yaml_path,
            query=payload.get("query"),
            mode=mode,
            max_results=self._optional_int(payload, "max_results"),
            case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
            box=self._optional_int(payload, "box"),
            position=position,
            record_id=self._optional_int(payload, "record_id"),
            active_only=(payload.get("active_only") if "active_only" in payload else None),
        ),
    )


def _run_recent_frozen(self, payload, _trace_id=None):
    tool_name = "recent_frozen"

    def _call_recent_frozen():
        basis = str(payload.get("basis") or "").strip().lower()
        value = self._required_int(payload, "value")
        if basis == "days":
            return tool_recent_frozen(yaml_path=self._yaml_path, days=value, count=None)
        if basis == "count":
            return tool_recent_frozen(yaml_path=self._yaml_path, days=None, count=value)
        raise ValueError(
            self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="basis",
                values="days, count",
            )
        )

    return self._safe_call(tool_name, _call_recent_frozen, include_expected_schema=True)


def _run_query_takeout_events(self, payload, _trace_id=None):
    tool_name = "query_takeout_events"

    def _call_query_takeout_events():
        view = str(payload.get("view") or "events").strip().lower()
        selector = str(payload.get("range") or "").strip().lower()
        summary_requested = bool(selector) or view == "summary"

        if summary_requested:
            if any(
                payload.get(name) not in (None, "")
                for name in ("date", "days", "start_date", "end_date", "action", "max_records")
            ):
                raise ValueError(
                    "When requesting summary, do not mix with date/days/start_date/end_date/action/max_records."
                )

            if not selector:
                selector = "30d"
            if selector == "all":
                return tool_collect_timeline(
                    yaml_path=self._yaml_path,
                    days=30,
                    all_history=True,
                )

            days_map = {"7d": 7, "30d": 30, "90d": 90}
            days = days_map.get(selector)
            if days is None:
                raise ValueError(
                    self._msg(
                        "validation.mustBeOneOf",
                        "{label} must be one of: {values}",
                        label="range",
                        values="7d, 30d, 90d, all",
                    )
                )
            return tool_collect_timeline(
                yaml_path=self._yaml_path,
                days=days,
                all_history=False,
            )

        days_value = self._optional_int(payload, "days")
        if days_value is not None:
            days_value = int(days_value)
        max_records_value = self._optional_int(payload, "max_records", default=0)
        max_records_value = 0 if max_records_value is None else int(max_records_value)

        return tool_query_takeout_events(
            yaml_path=self._yaml_path,
            date=payload.get("date"),
            days=days_value,
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            action=payload.get("action"),
            max_records=max_records_value,
        )

    return self._safe_call(tool_name, _call_query_takeout_events, include_expected_schema=True)


def _run_list_audit_timeline(self, payload, _trace_id=None):
    tool_name = "list_audit_timeline"
    limit = self._optional_int(payload, "limit", default=50)
    offset = self._optional_int(payload, "offset", default=0)

    return self._safe_call(
        tool_name,
        lambda: tool_list_audit_timeline(
            yaml_path=self._yaml_path,
            limit=50 if limit is None else int(limit),
            offset=0 if offset is None else int(offset),
            action_filter=payload.get("action_filter"),
            status_filter=payload.get("status_filter"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        ),
    )


def _run_recommend_positions(self, payload, _trace_id=None):
    tool_name = "recommend_positions"
    return self._safe_call(
        tool_name,
        lambda: tool_recommend_positions(
            yaml_path=self._yaml_path,
            count=self._optional_int(payload, "count", default=2),
            box_preference=self._optional_int(payload, "box_preference"),
            strategy=payload.get("strategy", "consecutive"),
        ),
    )


def _run_generate_stats(self, payload, _trace_id=None):
    return self._safe_call(
        "generate_stats",
        lambda: tool_generate_stats(
            yaml_path=self._yaml_path,
            box=self._optional_int(payload, "box"),
            include_inactive=self._as_bool(payload.get("include_inactive", False), default=False),
        ),
    )


def _run_get_raw_entries(self, payload, _trace_id=None):
    tool_name = "get_raw_entries"

    def _call_get_raw_entries():
        ids = list(payload.get("ids") or [])
        return tool_get_raw_entries(
            yaml_path=self._yaml_path,
            ids=ids,
        )

    return self._safe_call(tool_name, _call_get_raw_entries, include_expected_schema=True)


def _run_run_terminal(self, payload, _trace_id=None):
    tool_name = "run_terminal"

    def _call_run_terminal():
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(
                self._msg(
                    "terminal.commandMustBeNonEmpty",
                    "command must be a non-empty string.",
                )
            )
        return run_terminal_command(command)

    return self._safe_call(tool_name, _call_run_terminal, include_expected_schema=True)


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
        write_kwargs = _resolve_write_execution_kwargs(self, payload)
        return tool_edit_entry(
            yaml_path=self._yaml_path,
            record_id=rid,
            fields=fields,
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            **write_kwargs,
        )

    return self._safe_call(tool_name, _call_edit_entry, include_expected_schema=True)


def _run_add_entry(self, payload, trace_id=None):
    tool_name = "add_entry"

    def _call_add_entry():
        layout = self._load_layout()
        box_val = self._required_int(payload, "box")
        frozen_at = payload.get("frozen_at")
        positions = self._normalize_positions(payload.get("positions"), layout=layout)
        tool_positions = _to_tool_positions(positions, layout, field_name="positions")
        fields = dict(payload.get("fields") or {})

        write_kwargs = _resolve_write_execution_kwargs(self, payload)
        return tool_add_entry(
            yaml_path=self._yaml_path,
            box=box_val,
            positions=tool_positions,
            frozen_at=frozen_at,
            fields=fields,
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            **write_kwargs,
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
                "position": _to_tool_position(
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
                "position": _to_tool_position(
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
    write_kwargs = _resolve_write_execution_kwargs(self, payload)
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
        actor_context=self._actor_context(trace_id=trace_id),
        source="agent.react",
        **write_kwargs,
    )


def _run_takeout(self, payload, trace_id=None):
    tool_name = "takeout"

    def _call_takeout():
        return _call_batch_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=tool_takeout,
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
            tool_fn=tool_move,
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
        write_kwargs = _resolve_write_execution_kwargs(self, payload)
        return tool_rollback(
            yaml_path=self._yaml_path,
            backup_path=payload.get("backup_path"),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
            **write_kwargs,
        )

    return self._safe_call(tool_name, _call_rollback)


def _run_staged_plan(self, payload, _trace_id=None):
    tool_name = "staged_plan"

    def _list_items():
        if not self._plan_store:
            return {
                "ok": True,
                "result": {"items": [], "count": 0},
                "message": self._msg(
                    "manageStaged.noPlanStoreAvailableList",
                    "No plan store available.",
                ),
            }

        items = self._plan_store.list_items()
        summary = []
        for index, item in enumerate(items):
            entry = {
                "index": index,
                "action": item.get("action"),
                "record_id": item.get("record_id"),
                "box": item.get("box"),
                "position": item.get("position"),
                "label": item.get("label"),
                "source": item.get("source"),
            }
            if item.get("to_position") is not None:
                entry["to_position"] = item["to_position"]
            if item.get("to_box") is not None:
                entry["to_box"] = item["to_box"]
            summary.append(entry)
        return {"ok": True, "result": {"items": summary, "count": len(summary)}}

    def _remove_item():
        idx = self._required_int(payload, "index")

        if not self._plan_store:
            return {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "manageStaged.planStoreNotAvailable",
                    "Plan store not available.",
                ),
            }

        removed = self._plan_store.remove_by_index(idx)
        if removed is None:
            max_idx = self._plan_store.count() - 1
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "invalid_index",
                    "message": self._msg(
                        "manageStaged.indexOutOfRange",
                        "Index {idx} out of range (0..{max_idx}).",
                        idx=idx,
                        max_idx=max_idx,
                    ),
                },
            )

        return {
            "ok": True,
            "message": self._msg(
                "manageStaged.removedByIndex",
                "Removed item at index {idx}: {desc}",
                idx=idx,
                desc=self._item_desc(removed),
            ),
            "result": {"removed": 1},
        }

    def _clear_items():
        if not self._plan_store:
            return {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "manageStaged.planStoreNotAvailable",
                    "Plan store not available.",
                ),
            }

        cleared = self._plan_store.clear()
        return {
            "ok": True,
            "message": self._msg(
                "manageStaged.clearedCount",
                "Cleared {count} staged item(s).",
                count=len(cleared),
            ),
            "result": {"cleared_count": len(cleared)},
        }

    def _call_staged_plan():
        action = str(payload.get("action") or "").strip().lower()
        if action == "list":
            return _list_items()
        if action == "remove":
            return _remove_item()
        if action == "clear":
            return _clear_items()
        raise ValueError(
            self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="action",
                values="list, remove, clear",
            )
        )

    return self._safe_call(tool_name, _call_staged_plan, include_expected_schema=True)
