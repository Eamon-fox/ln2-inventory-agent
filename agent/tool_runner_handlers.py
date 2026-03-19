"""Dispatch handlers for AgentToolRunner."""

from contextlib import suppress
import os
import re

from lib.import_acceptance import import_validated_yaml, validate_candidate_yaml
from lib import tool_api_write_adapter as _write_adapter
from lib.inventory_paths import (
    create_managed_dataset_yaml_path,
)
from lib.builtin_skills import BuiltinSkillError, load_builtin_skill
from lib.path_policy import PathPolicyError, resolve_dataset_backup_read_path, resolve_repo_read_path
from lib.tool_api import (
    tool_collect_timeline,
    tool_filter_records,
    tool_generate_stats,
    tool_get_raw_entries,
    tool_list_audit_timeline,
    tool_list_empty_positions,
    tool_query_takeout_events,
    tool_recent_frozen,
    tool_recent_stored,
    tool_recommend_positions,
    tool_search_records,
)
from lib.schema_aliases import coalesce_stored_at_value, present_record_sort_field
from lib.validate_service import validate_yaml_file
from .file_ops_client import run_file_tool
from .tool_runtime_paths import derive_repo_root_from_yaml


_IMPORT_CONFIRMATION_TOKEN = "CONFIRM_IMPORT"
_TARGET_DATASET_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _run_use_skill(self, payload, _trace_id=None):
    tool_name = "use_skill"

    def _call_use_skill():
        skill_name = str(payload.get("skill_name") or "").strip()
        try:
            loaded = load_builtin_skill(skill_name)
        except BuiltinSkillError as exc:
            response = {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
            }
            available = list((exc.details or {}).get("available_skills") or [])
            if available:
                response["available_skills"] = available
            return response

        return {
            "ok": True,
            "skill_name": str(loaded.get("name") or skill_name),
            "description": str(loaded.get("description") or ""),
            "instructions_markdown": str(loaded.get("instructions_markdown") or ""),
            "references": list(loaded.get("references") or []),
            "shared_references": list(loaded.get("shared_references") or []),
            "scripts": list(loaded.get("scripts") or []),
            "assets": list(loaded.get("assets") or []),
        }

    return self._safe_call(tool_name, _call_use_skill, include_expected_schema=True)

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

def _extract_staged_item_positions(item):
    """Extract one-or-many source positions from a staged plan item."""
    if not isinstance(item, dict):
        return []

    candidates = []
    top_positions = item.get("positions")
    if isinstance(top_positions, (list, tuple, set)):
        candidates.append(top_positions)

    payload = item.get("payload")
    payload_positions = payload.get("positions") if isinstance(payload, dict) else None
    if isinstance(payload_positions, (list, tuple, set)):
        candidates.append(payload_positions)

    for raw_values in candidates:
        values = [value for value in list(raw_values) if value not in (None, "")]
        if values:
            return values

    fallback_pos = item.get("position")
    if fallback_pos not in (None, ""):
        return [fallback_pos]
    return []


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
                return _write_adapter.adjust_box_count(
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
                return _write_adapter.adjust_box_count(
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
        position = _write_adapter.to_tool_position(
            self._parse_position(
                payload.get("position"),
                layout=layout,
                field_name="position",
            ),
            layout,
            field_name="position",
        )

    response = self._safe_call(
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
            status=payload.get("status"),
            sort_by=payload.get("sort_by"),
            sort_order=payload.get("sort_order"),
        ),
    )
    applied_filters = (
        (response.get("result") or {}).get("applied_filters")
        if isinstance(response, dict)
        else None
    )
    if isinstance(applied_filters, dict):
        applied_filters["sort_by"] = present_record_sort_field(
            applied_filters.get("sort_by"),
            requested=payload.get("sort_by"),
            default_legacy=False,
    )
    return response


def _run_filter_records(self, payload, _trace_id=None):
    tool_name = "filter_records"
    return self._safe_call(
        tool_name,
        lambda: tool_filter_records(
            yaml_path=self._yaml_path,
            keyword=payload.get("keyword"),
            box=self._optional_int(payload, "box"),
            color_value=payload.get("color_value"),
            include_inactive=self._as_bool(payload.get("include_inactive", False), default=False),
            column_filters=payload.get("column_filters"),
            sort_by=payload.get("sort_by") or "location",
            sort_order=payload.get("sort_order") or "asc",
            limit=self._optional_int(payload, "limit"),
            offset=self._optional_int(payload, "offset", default=0),
        ),
    )


def _run_recent_stored(self, payload, _trace_id=None):
    tool_name = "recent_stored"

    def _call_recent():
        basis = str(payload.get("basis") or "").strip().lower()
        value = self._required_int(payload, "value")
        if basis == "days":
            return tool_recent_stored(yaml_path=self._yaml_path, days=value, count=None)
        if basis == "count":
            return tool_recent_stored(yaml_path=self._yaml_path, days=None, count=value)
        raise ValueError(
            self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="basis",
                values="days, count",
            )
        )

    return self._safe_call(tool_name, _call_recent, include_expected_schema=True)


def _run_recent_frozen(self, payload, _trace_id=None):
    tool_name = "recent_frozen"

    def _call_recent():
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

    return self._safe_call(tool_name, _call_recent, include_expected_schema=True)


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
    if "full_records_for_gui" in payload:
        return self._with_hint(
            "generate_stats",
            {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": "full_records_for_gui is reserved for GUI runtime and is not allowed in agent tool calls.",
            },
        )
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


def _run_bash(self, payload, _trace_id=None):
    tool_name = "bash"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_powershell(self, payload, _trace_id=None):
    tool_name = "powershell"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_fs_list(self, payload, _trace_id=None):
    tool_name = "fs_list"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_fs_read(self, payload, _trace_id=None):
    tool_name = "fs_read"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_fs_write(self, payload, _trace_id=None):
    tool_name = "fs_write"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _run_fs_edit(self, payload, _trace_id=None):
    tool_name = "fs_edit"
    return self._safe_call(
        tool_name,
        lambda: run_file_tool(tool_name, payload, yaml_path=self._yaml_path),
        include_expected_schema=True,
    )


def _migration_output_yaml_path():
    from lib import inventory_paths as _inventory_paths

    root = os.path.abspath(_inventory_paths.get_install_dir())
    return os.path.join(root, "migrate", "output", "ln2_inventory.yaml")


def _build_import_target_path(dataset_name):
    return create_managed_dataset_yaml_path(dataset_name)


def _run_validate(self, payload, _trace_id=None):
    tool_name = "validate"

    def _call_validate():
        repo_root = str(derive_repo_root_from_yaml(self._yaml_path))
        resolved = resolve_repo_read_path(repo_root, payload.get("path"), default_rel=".")
        if os.path.isdir(resolved):
            return {
                "ok": False,
                "error_code": "path_is_directory",
                "message": f"Path is a directory: {resolved}",
                "effective_root": repo_root,
                "resolved_path": str(resolved),
            }
        result = dict(validate_yaml_file(str(resolved)) or {})
        result["effective_root"] = repo_root
        result["resolved_path"] = str(resolved)
        return result

    return self._safe_call(
        tool_name,
        _call_validate,
        include_expected_schema=True,
    )


def _run_import_migration_output(self, payload, _trace_id=None):
    tool_name = "import_migration_output"

    def _call_import_migration_output():
        token = str(payload.get("confirmation_token") or "").strip()
        if token != _IMPORT_CONFIRMATION_TOKEN:
            return {
                "ok": False,
                "error_code": "invalid_confirmation_token",
                "message": f"confirmation_token must be exactly {_IMPORT_CONFIRMATION_TOKEN}.",
            }

        dataset_name = str(payload.get("target_dataset_name") or "").strip()
        if not dataset_name:
            return {
                "ok": False,
                "error_code": "invalid_target_dataset_name",
                "message": "target_dataset_name must be a non-empty string.",
            }
        if not _TARGET_DATASET_NAME_RE.fullmatch(dataset_name):
            return {
                "ok": False,
                "error_code": "invalid_target_dataset_name",
                "message": "target_dataset_name must match ^[A-Za-z0-9_-]+$.",
                "details": {"target_dataset_name": dataset_name},
            }

        candidate = _migration_output_yaml_path()
        validation = validate_candidate_yaml(candidate, fail_on_warnings=True)
        if not validation.get("ok"):
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": str(validation.get("message") or "Candidate YAML failed validation."),
                "report": validation.get("report") or {},
            }

        target_path = _build_import_target_path(dataset_name)
        result = import_validated_yaml(
            candidate,
            target_path,
            mode="create_new",
            overwrite=False,
        )
        if result.get("ok"):
            return result

        # Best-effort cleanup when import fails before writing inventory.yaml.
        with suppress(Exception):
            dataset_dir = os.path.dirname(target_path)
            if dataset_dir and os.path.isdir(dataset_dir) and not os.path.exists(target_path):
                os.rmdir(dataset_dir)
        return result

    return self._safe_call(tool_name, _call_import_migration_output, include_expected_schema=True)


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
            positions = _extract_staged_item_positions(item)
            entry = {
                "index": index,
                "action": item.get("action"),
                "record_id": item.get("record_id"),
                "box": item.get("box"),
                "positions": positions,
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
