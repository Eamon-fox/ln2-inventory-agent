"""Tool dispatcher for agent runtime, built on unified Tool API."""

from contextlib import suppress
import os
import re
import threading
import uuid

from lib.tool_api import (
    build_actor_context,
    tool_get_raw_entries,
)
from lib.tool_contracts import TOOL_CONTRACTS, WRITE_TOOLS
from lib.tool_registry import iter_agent_dispatch_descriptors
from lib import tool_api_parsers as _tool_parsers
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.yaml_ops import load_yaml
from app_gui.i18n import tr
from . import tool_runner_handlers as _runner_handlers
from . import tool_runner_staging as _runner_staging
from . import tool_runner_validation as _runner_validation
from . import tool_runner_guidance as _runner_guidance
from . import tool_hooks as _tool_hooks
from . import tool_runtime_paths as _tool_runtime_paths

_TOOL_CONTRACTS = TOOL_CONTRACTS
_WRITE_TOOLS = WRITE_TOOLS
_QUESTION_OTHER_OPTION = "\u5176\u4ed6\uff1a\u8bf7\u8f93\u5165"

class AgentToolRunner:
    """Executes named tools with normalized input payloads."""

    @staticmethod
    def _msg(msg_key, default, **kwargs):
        full_key = f"agentToolRunner.{msg_key}"
        try:
            text = tr(full_key, default=default, **kwargs)
            if kwargs:
                try:
                    return str(text).format(**kwargs)
                except Exception:
                    return str(text)
            return str(text)
        except Exception:
            if kwargs:
                try:
                    return str(default).format(**kwargs)
                except Exception:
                    return str(default)
            return str(default)

    def __init__(
        self,
        yaml_path,
        session_id=None,
        plan_store=None,
    ):
        self._yaml_path = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
        self._session_id = session_id
        self._plan_store = plan_store
        self._hook_manager = _tool_hooks.build_default_tool_hook_manager()
        # Question tool synchronization
        self._answer_event = threading.Event()
        self._pending_answer = None
        self._answer_cancelled = False

    def _set_answer(self, answers):
        """Called from GUI main thread to provide user answers."""
        self._pending_answer = answers
        self._answer_cancelled = False
        self._answer_event.set()

    def _cancel_answer(self):
        """Called from GUI main thread when user cancels."""
        self._pending_answer = None
        self._answer_cancelled = True
        self._answer_event.set()

    def _actor_context(self, trace_id=None):
        return build_actor_context(
            session_id=self._session_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _required_int(payload, key):
        value = payload.get(key)
        if value in (None, ""):
            raise ValueError(
                AgentToolRunner._msg(
                    "errors.missingRequiredIntegerField",
                    "Missing required integer field: {key}",
                    key=key,
                )
            )
        if not AgentToolRunner._is_integer(value):
            raise ValueError(
                AgentToolRunner._msg(
                    "errors.fieldMustBeInteger",
                    "{key} must be an integer",
                    key=key,
                )
            )
        return int(value)

    @staticmethod
    def _optional_int(payload, key, default=None):
        value = payload.get(key)
        if value in (None, ""):
            return default
        if not AgentToolRunner._is_integer(value):
            raise ValueError(
                AgentToolRunner._msg(
                    "errors.fieldMustBeInteger",
                    "{key} must be an integer",
                    key=key,
                )
            )
        return int(value)

    @staticmethod
    def _as_bool(value, default=False):
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", ""}:
            return False
        return bool(default)

    @staticmethod
    def _iter_text_chunks(value):
        """Yield nested text fragments from mixed dict/list payloads."""
        if value is None:
            return
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, dict):
            for nested in value.values():
                yield from AgentToolRunner._iter_text_chunks(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                yield from AgentToolRunner._iter_text_chunks(nested)
            return
        yield str(value)

    @staticmethod
    def _extract_record_ids_from_payload(*values):
        """Extract candidate record IDs from error payload text."""
        ids = set()
        for value in values:
            for text in AgentToolRunner._iter_text_chunks(value):
                for raw in re.findall(r"id\s*=\s*(\d+)", text, flags=re.IGNORECASE):
                    with suppress(Exception):
                        ids.add(int(raw))
        return sorted(ids)

    def _load_layout(self):
        try:
            data = load_yaml(self._yaml_path)
        except Exception:
            return {}
        return (data or {}).get("meta", {}).get("box_layout", {})

    def _load_meta(self):
        try:
            data = load_yaml(self._yaml_path)
        except Exception:
            return {}
        meta = (data or {}).get("meta", {})
        return meta if isinstance(meta, dict) else {}

    def _load_inventory(self):
        try:
            data = load_yaml(self._yaml_path)
        except Exception:
            return []
        inventory = (data or {}).get("inventory", [])
        return inventory if isinstance(inventory, list) else []

    @staticmethod
    def _parse_position(value, layout=None, field_name="position"):
        if value in (None, ""):
            return None
        try:
            return int(_tool_parsers._coerce_position_value(value, layout=layout, field_name=field_name))
        except Exception as exc:
            raise ValueError(
                AgentToolRunner._msg(
                    "errors.invalidPositionField",
                    "{field_name} is invalid: {value}",
                    field_name=field_name,
                    value=value,
                )
            ) from exc

    def _normalize_positions(self, value, layout=None):
        if value in (None, ""):
            return None
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("positions must be an array")
        return _tool_parsers._normalize_positions_input(value, layout=layout)

    def _parse_slot_payload(self, slot_payload, *, layout, field_name):
        try:
            box, position = _tool_parsers._parse_slot_payload(
                slot_payload,
                layout=layout,
                field_name=field_name,
            )
            return {"box": box, "position": position}
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    _normalize_search_mode = staticmethod(_runner_validation._normalize_search_mode)

    def list_tools(self):
        return list(TOOL_CONTRACTS.keys())

    tool_schemas = _runner_validation.tool_schemas
    _tool_input_schema = _runner_validation._tool_input_schema
    _tool_input_field_sets = _runner_validation._tool_input_field_sets
    _sanitize_tool_input_payload = staticmethod(_runner_validation._sanitize_tool_input_payload)
    _is_integer = staticmethod(_runner_validation._is_integer)
    _validate_schema_value = _runner_validation._validate_schema_value
    _validate_tool_input = _runner_validation._validate_tool_input

    _hint_for_error = _runner_guidance._hint_for_error
    _with_hint = _runner_guidance._with_hint

    def _tool_hook_context(self, trace_id=None):
        return _tool_runtime_paths.build_tool_hook_context(
            self._yaml_path,
            trace_id=trace_id,
        )

    def _run_question_tool(self, payload):
        """Validate question payload and return a waiting_for_user marker.

        The actual blocking (threading.Event.wait) happens in
        ReactAgent._run_tool_call, which emits the question event first
        and then waits for the GUI to call _set_answer / _cancel_answer.
        """
        question_text = str(payload.get("question") or "").strip()
        if not question_text:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": self._msg(
                    "question.nonEmptyQuestionRequired",
                    "question must be a non-empty string.",
                ),
            }

        options_raw = payload.get("options")
        if not isinstance(options_raw, list):
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": self._msg(
                    "question.optionsMustBeArray",
                    "options must be an array of non-empty strings.",
                ),
            }
        if len(options_raw) < 2 or len(options_raw) > 5:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": self._msg(
                    "question.optionsCountRange",
                    "options must contain 2 to 5 items.",
                ),
            }

        options = []
        for idx, raw_option in enumerate(options_raw):
            if not isinstance(raw_option, str):
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": self._msg(
                        "question.optionMustBeString",
                        "options[{index}] must be a string.",
                        index=idx,
                    ),
                }
            option = raw_option.strip()
            if not option:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": self._msg(
                        "question.optionMustBeNonEmpty",
                        "options[{index}] must be a non-empty string.",
                        index=idx,
                    ),
                }
            options.append(option)

        if _QUESTION_OTHER_OPTION in options:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": self._msg(
                    "question.reservedOptionForbidden",
                    "options must not contain reserved option `{option}`.",
                    option=_QUESTION_OTHER_OPTION,
                ),
            }

        # Always add a final free-text entry so users can type an answer
        # without requiring tool-schema changes.
        options.append(_QUESTION_OTHER_OPTION)

        question_id = str(uuid.uuid4())

        # Reset synchronization state for this question round
        self._answer_event.clear()
        self._pending_answer = None
        self._answer_cancelled = False

        return {
            "ok": True,
            "waiting_for_user": True,
            "question_id": question_id,
            "question": question_text,
            "options": options,
        }

    def _safe_call(self, tool_name, fn, include_expected_schema=False):
        try:
            response = fn()
        except Exception as exc:
            error_code = str(getattr(exc, "code", "") or "invalid_tool_input")
            message = str(getattr(exc, "message", "") or str(exc))
            payload = {
                "ok": False,
                "error_code": error_code,
                "message": message,
            }
            resolved_path = str(getattr(exc, "resolved_path", "") or "").strip()
            if resolved_path:
                payload["resolved_path"] = resolved_path
            if include_expected_schema:
                payload["expected_schema"] = self._tool_input_schema(tool_name)
            return self._with_hint(tool_name, payload)
        return self._with_hint(tool_name, response)

    # --- Plan staging (human-in-the-loop) ---

    def _lookup_record_info(self, record_id):
        """Quick lookup to get (box, position) for a record ID."""
        try:
            result = tool_get_raw_entries(yaml_path=self._yaml_path, ids=[record_id])
            if result.get("ok"):
                entries = result.get("result", {}).get("entries", [])
                if entries:
                    rec = entries[0]
                    box = int(rec.get("box", 0))
                    position = rec.get("position")
                    if position is not None:
                        try:
                            position = int(
                                _tool_parsers._coerce_position_value(
                                    position,
                                    layout=self._load_layout(),
                                    field_name="position",
                                )
                            )
                        except Exception:
                            position = None
                    return box, position
        except Exception:
            pass
        return 0, None

    def _item_desc(self, item):
        action = str(item.get("action") or "?")
        if action == "rollback":
            payload = item.get("payload") or {}
            backup_path = str(payload.get("backup_path") or "").strip()
            if backup_path:
                name = os.path.basename(backup_path)
                return self._msg(
                    "itemDesc.rollbackWithPath",
                    "rollback {name} ({backup_path})",
                    name=name,
                    backup_path=backup_path,
                )
            return self._msg(
                "itemDesc.rollbackLatest",
                "rollback latest-backup",
            )

        label = str(item.get("label") or item.get("record_id") or "-")
        box = item.get("box", "?")
        pos = item.get("position", "?")
        if action == "add":
            positions = item.get("positions")
            if not isinstance(positions, (list, tuple, set)):
                payload = item.get("payload")
                positions = payload.get("positions") if isinstance(payload, dict) else None
            if isinstance(positions, (list, tuple, set)):
                normalized_positions = [value for value in list(positions) if value not in (None, "")]
                if normalized_positions:
                    pos = ",".join(str(value) for value in normalized_positions)
        target = ""
        if action == "move":
            to_box = item.get("to_box")
            to_pos = item.get("to_position")
            if to_pos is not None:
                if to_box is not None:
                    target = self._msg(
                        "itemDesc.moveTargetWithBox",
                        " -> Box {to_box}:{to_pos}",
                        to_box=to_box,
                        to_pos=to_pos,
                    )
                else:
                    target = self._msg(
                        "itemDesc.moveTarget",
                        " -> {to_pos}",
                        to_pos=to_pos,
                    )
        return self._msg(
            "itemDesc.default",
            "{action} {label} @ Box {box}:{pos}{target}",
            action=action,
            label=label,
            box=box,
            pos=pos,
            target=target,
        )

    _stage_to_plan = _runner_staging._stage_to_plan
    _stage_to_plan_impl = _runner_staging._stage_to_plan_impl
    _build_staged_plan_items = _runner_staging._build_staged_plan_items
    _stage_items_add_entry = _runner_staging._stage_items_add_entry
    _stage_items_takeout = _runner_staging._stage_items_takeout
    _stage_items_move = _runner_staging._stage_items_move
    _stage_items_edit_entry = _runner_staging._stage_items_edit_entry
    _stage_items_rollback = _runner_staging._stage_items_rollback
    _build_stage_blocked_response = _runner_staging._build_stage_blocked_response

    def run(self, tool_name, tool_input, trace_id=None):
        payload = self._sanitize_tool_input_payload(tool_input)
        return self._run_dispatch(tool_name, payload, trace_id)

    def _unknown_tool_response(self, tool_name):
        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "unknown_tool",
                "message": self._msg(
                    "errors.unknownTool",
                    "Unknown tool: {tool_name}",
                    tool_name=tool_name,
                ),
                "available_tools": self.list_tools(),
            },
        )

    _run_manage_boxes = _runner_handlers._run_manage_boxes
    _run_use_skill = _runner_handlers._run_use_skill
    _run_list_empty_positions = _runner_handlers._run_list_empty_positions
    _run_search_records = _runner_handlers._run_search_records
    _run_recent_stored = _runner_handlers._run_recent_stored
    _run_recent_frozen = _runner_handlers._run_recent_frozen
    _run_query_takeout_events = _runner_handlers._run_query_takeout_events
    _run_list_audit_timeline = _runner_handlers._run_list_audit_timeline
    _run_recommend_positions = _runner_handlers._run_recommend_positions
    _run_generate_stats = _runner_handlers._run_generate_stats
    _run_get_raw_entries = _runner_handlers._run_get_raw_entries
    _run_bash = _runner_handlers._run_bash
    _run_powershell = _runner_handlers._run_powershell
    _run_fs_list = _runner_handlers._run_fs_list
    _run_fs_read = _runner_handlers._run_fs_read
    _run_fs_write = _runner_handlers._run_fs_write
    _run_fs_edit = _runner_handlers._run_fs_edit
    _run_validate = _runner_handlers._run_validate
    _run_import_migration_output = _runner_handlers._run_import_migration_output
    _run_edit_entry = _runner_handlers._run_edit_entry
    _run_add_entry = _runner_handlers._run_add_entry
    _run_takeout = _runner_handlers._run_takeout
    _run_move = _runner_handlers._run_move
    _run_rollback = _runner_handlers._run_rollback
    _run_staged_plan = _runner_handlers._run_staged_plan

    def _dispatch_handlers(self):
        handlers = {}
        missing = []
        for descriptor in iter_agent_dispatch_descriptors():
            handler = getattr(self, str(descriptor.agent_handler_attr or ""), None)
            if callable(handler):
                handlers[descriptor.name] = handler
            else:
                missing.append(descriptor.name)
        assert not missing, f"Dispatch handlers missing for tools: {set(missing)}"
        return handlers

    def _run_dispatch(self, tool_name, payload, trace_id=None):
        if tool_name not in TOOL_CONTRACTS:
            return self._unknown_tool_response(tool_name)

        hook_context = self._tool_hook_context(trace_id)
        before_hook = self._hook_manager.run_before(tool_name, payload, hook_context)
        if before_hook.get("blocked"):
            blocked_response = {
                "ok": False,
                "error_code": "tool_hook_blocked",
                "message": str(before_hook.get("message") or "Tool call blocked by hook."),
            }
            response = _tool_hooks.merge_hook_result(blocked_response, before_hook)
            return self._with_hint(tool_name, response)

        payload = _tool_hooks.apply_payload_patch(payload, before_hook)

        # Question tool keeps its own detailed validation/error codes.
        if tool_name == "question":
            response = self._run_question_tool(payload)
            after_hook = self._hook_manager.run_after(tool_name, payload, response, hook_context)
            return _tool_hooks.merge_hook_result(response, after_hook)

        input_error = self._validate_tool_input(tool_name, payload)
        if input_error:
            response = self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": input_error,
                },
            )
            after_hook = self._hook_manager.run_after(tool_name, payload, response, hook_context)
            return _tool_hooks.merge_hook_result(response, after_hook)

        # Intercept write operations when plan_store is set.
        if tool_name in WRITE_TOOLS and self._plan_store is not None:
            response = self._stage_to_plan(tool_name, payload, trace_id)
            after_hook = self._hook_manager.run_after(tool_name, payload, response, hook_context)
            return _tool_hooks.merge_hook_result(response, after_hook)

        handler = self._dispatch_handlers().get(tool_name)
        if callable(handler):
            response = handler(payload, trace_id)
            after_hook = self._hook_manager.run_after(tool_name, payload, response, hook_context)
            return _tool_hooks.merge_hook_result(response, after_hook)
        return self._unknown_tool_response(tool_name)
