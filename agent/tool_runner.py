"""Tool dispatcher for agent runtime, built on unified Tool API."""

from copy import deepcopy
import os
import re
import threading
import uuid

from lib.tool_api import (
    build_actor_context,
    parse_batch_entries,
    tool_add_entry,
    tool_adjust_box_count,
    tool_batch_thaw,
    tool_collect_timeline,
    tool_edit_entry,
    tool_generate_stats,
    tool_get_raw_entries,
    tool_list_empty_positions,
    tool_query_thaw_events,
    tool_recent_frozen,
    tool_recommend_positions,
    tool_record_thaw,
    tool_rollback,
    tool_search_records,
)
from app_gui.plan_gate import validate_stage_request
from lib.plan_item_factory import build_add_plan_item, build_edit_plan_item, build_record_plan_item, build_rollback_plan_item
from lib.position_fmt import display_to_pos
from lib.validators import parse_positions
from lib.yaml_ops import load_yaml

_WRITE_TOOLS = {"add_entry", "record_thaw", "batch_thaw", "rollback", "edit_entry"}


_TOOL_CONTRACTS = {
    "list_empty_positions": {
        "description": "List empty positions, optionally within one box.",
        "parameters": {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "search_records": {
        "description": "Search inventory records, or list recently frozen records via recent_* filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text (cell line, short name, notes, etc).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fuzzy", "exact", "keywords"],
                    "description": "Search strategy.",
                },
                "max_results": {"type": "integer", "minimum": 1},
                "case_sensitive": {"type": "boolean"},
                "box": {"type": "integer", "minimum": 1},
                "position": {"type": "integer", "minimum": 1},
                "record_id": {"type": "integer", "minimum": 1},
                "active_only": {"type": "boolean"},
                "recent_days": {"type": "integer", "minimum": 1},
                "recent_count": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "query_thaw_events": {
        "description": "Query thaw/takeout/move events, or timeline summary via view=summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "view": {
                    "type": "string",
                    "enum": ["events", "summary"],
                },
                "date": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "action": {"type": "string"},
                "max_records": {"type": "integer", "minimum": 0},
                "all_history": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "recommend_positions": {
        "description": "Recommend empty positions for new tubes.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1},
                "box_preference": {"type": "integer", "minimum": 1},
                "strategy": {
                    "type": "string",
                    "enum": ["consecutive", "same_row", "any"],
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "generate_stats": {
        "description": "Generate inventory statistics.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "get_raw_entries": {
        "description": "Fetch raw inventory records by ID list.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 1,
                },
            },
            "required": ["ids"],
            "additionalProperties": False,
        },
    },
    "add_entry": {
        "description": "Add new frozen tube records.",
        "notes": "Provide all sample metadata through fields object (e.g. fields.short_name, fields.cell_line).",
        "parameters": {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "positions": {
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1},
                            "minItems": 1,
                        },
                        {"type": "string"},
                    ]
                },
                "frozen_at": {"type": "string"},
                "fields": {"type": "object"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["box", "positions", "frozen_at"],
            "additionalProperties": False,
        },
    },
    "edit_entry": {
        "description": "Edit metadata fields of an existing record.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "fields": {"type": "object", "minProperties": 1},
            },
            "required": ["record_id", "fields"],
            "additionalProperties": False,
        },
    },
    "record_thaw": {
        "description": "Record takeout or move for one tube.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "position": {
                    "oneOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "string"},
                    ]
                },
                "date": {"type": "string"},
                "action": {"type": "string", "enum": ["取出", "移动", "takeout", "move", "Takeout", "Move"]},
                "to_position": {
                    "oneOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "string"},
                    ]
                },
                "to_box": {"type": "integer", "minimum": 1},
                "note": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["record_id", "date"],
            "additionalProperties": False,
        },
    },
    "batch_thaw": {
        "description": "Record takeout or move for multiple tubes.",
        "notes": "entries supports parsed string formats from parse_batch_entries and structured array rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "entries": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "oneOf": [
                                    {
                                        "type": "array",
                                        "items": {
                                            "oneOf": [
                                                {"type": "integer"},
                                                {"type": "string"},
                                            ]
                                        },
                                        "minItems": 1,
                                        "maxItems": 4,
                                    },
                                    {
                                        "type": "object",
                                        "properties": {
                                            "record_id": {"type": "integer", "minimum": 1},
                                            "id": {"type": "integer", "minimum": 1},
                                            "position": {
                                                "oneOf": [
                                                    {"type": "integer", "minimum": 1},
                                                    {"type": "string"},
                                                ]
                                            },
                                            "from_position": {
                                                "oneOf": [
                                                    {"type": "integer", "minimum": 1},
                                                    {"type": "string"},
                                                ]
                                            },
                                            "to_position": {
                                                "oneOf": [
                                                    {"type": "integer", "minimum": 1},
                                                    {"type": "string"},
                                                ]
                                            },
                                            "to_box": {"type": "integer", "minimum": 1},
                                        },
                                        "required": [],
                                        "additionalProperties": False,
                                    },
                                ]
                            },
                        },
                    ]
                },
                "date": {"type": "string"},
                "action": {"type": "string", "enum": ["取出", "移动", "takeout", "move", "Takeout", "Move"]},
                "to_box": {"type": "integer", "minimum": 1},
                "note": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["entries"],
            "additionalProperties": False,
        },
    },
    "rollback": {
        "description": "Rollback inventory YAML to a backup snapshot using explicit backup_path.",
        "notes": "Always provide explicit backup_path.",
        "parameters": {
            "type": "object",
            "properties": {
                "backup_path": {"type": "string"},
            },
            "required": ["backup_path"],
            "additionalProperties": False,
        },
    },
    "manage_boxes": {
        "description": "Safely add or remove inventory boxes.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "remove"]},
                "count": {"type": "integer", "minimum": 1},
                "box": {"type": "integer", "minimum": 1},
                "renumber_mode": {
                    "type": "string",
                    "enum": ["keep_gaps", "renumber_contiguous"],
                },
                "dry_run": {"type": "boolean"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
    "question": {
        "description": "Ask user clarifying questions when required values are unknown.",
        "notes": "question tool is not a write tool and must run alone.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "multiple": {"type": "boolean"},
                        },
                        "required": ["header", "question"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
    "manage_staged": {
        "description": "List, remove, or clear staged plan items.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "remove", "clear"],
                },
                "index": {"type": "integer", "minimum": 0},
                "action": {"type": "string"},
                "record_id": {"type": "integer", "minimum": 1},
                "position": {"type": "integer", "minimum": 1},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
}


class AgentToolRunner:
    """Executes named tools with normalized input payloads."""

    def __init__(self, yaml_path, session_id=None, plan_store=None):
        self._yaml_path = yaml_path
        self._session_id = session_id
        self._plan_store = plan_store
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
            actor_type="agent",
            channel="agent",
            session_id=self._session_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _required_int(payload, key):
        value = payload.get(key)
        if value in (None, ""):
            raise ValueError(f"Missing required integer field: {key}")
        if not AgentToolRunner._is_integer(value):
            raise ValueError(f"{key} must be an integer")
        return int(value)

    @staticmethod
    def _optional_int(payload, key, default=None):
        value = payload.get(key)
        if value in (None, ""):
            return default
        if not AgentToolRunner._is_integer(value):
            raise ValueError(f"{key} must be an integer")
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
                    try:
                        ids.add(int(raw))
                    except Exception:
                        pass
        return sorted(ids)

    def _load_layout(self):
        try:
            data = load_yaml(self._yaml_path)
        except Exception:
            return {}
        return (data or {}).get("meta", {}).get("box_layout", {})

    @staticmethod
    def _parse_position(value, layout=None, field_name="position"):
        if value in (None, ""):
            return None
        try:
            return int(display_to_pos(value, layout))
        except Exception as exc:
            raise ValueError(f"{field_name} is invalid: {value}") from exc

    def _normalize_positions(self, value, layout=None):
        if value in (None, ""):
            return None
        if isinstance(value, list):
            return [self._parse_position(item, layout=layout) for item in value]
        if isinstance(value, tuple):
            return [self._parse_position(item, layout=layout) for item in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            return parse_positions(value, layout=layout)
        return value

    @staticmethod
    def _normalize_search_mode(value):
        if value in (None, ""):
            return "fuzzy"

        text = str(value).strip().lower()
        if text in {"fuzzy", "exact", "keywords"}:
            return text
        raise ValueError("mode must be one of: fuzzy, exact, keywords")

    def list_tools(self):
        return list(_TOOL_CONTRACTS.keys())

    def tool_specs(self):
        """Compact tool schemas for runtime grounding (single source of truth)."""
        specs = {}
        for name, contract in _TOOL_CONTRACTS.items():
            schema = deepcopy(contract.get("parameters") or {})
            properties = dict(schema.get("properties") or {})
            required = list(schema.get("required") or [])
            optional = [key for key in properties.keys() if key not in required]
            item = {
                "required": required,
                "optional": optional,
                "params": properties,
                "description": contract.get("description") or f"LN2 inventory tool: {name}",
            }
            notes = contract.get("notes")
            if notes:
                item["notes"] = notes
            specs[name] = item
        return specs

    def tool_schemas(self):
        """OpenAI-compatible function tool schemas for native tool calling."""
        schemas = []

        for name, contract in _TOOL_CONTRACTS.items():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": contract.get("description") or f"LN2 inventory tool: {name}",
                        "parameters": deepcopy(contract.get("parameters") or {}),
                    },
                }
            )

        return schemas

    @staticmethod
    def _is_integer(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def _validate_schema_value(self, value, schema, path):
        if not isinstance(schema, dict):
            return None

        if "oneOf" in schema:
            options = schema.get("oneOf") or []
            for option in options:
                if self._validate_schema_value(value, option, path) is None:
                    return None
            label = path or "value"
            return f"{label} does not match any allowed schema"

        expected_type = schema.get("type")

        if expected_type == "object":
            if not isinstance(value, dict):
                label = path or "payload"
                return f"{label} must be an object"

            properties = schema.get("properties") or {}
            required = schema.get("required") or []

            for field in required:
                if field not in value:
                    return f"Missing required field: {field}"

            if schema.get("additionalProperties") is False:
                extras = sorted(set(value.keys()) - set(properties.keys()))
                if extras:
                    return f"Unexpected field(s): {', '.join(extras)}"

            min_props = schema.get("minProperties")
            if isinstance(min_props, int) and len(value) < min_props:
                label = path or "payload"
                return f"{label} must contain at least {min_props} field(s)"

            for key, val in value.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, dict):
                    child_path = f"{path}.{key}" if path else key
                    err = self._validate_schema_value(val, child_schema, child_path)
                    if err:
                        return err

            return None

        if expected_type == "array":
            if not isinstance(value, list):
                label = path or "value"
                return f"{label} must be an array"

            min_items = schema.get("minItems")
            if isinstance(min_items, int) and len(value) < min_items:
                label = path or "value"
                return f"{label} must contain at least {min_items} item(s)"

            max_items = schema.get("maxItems")
            if isinstance(max_items, int) and len(value) > max_items:
                label = path or "value"
                return f"{label} must contain at most {max_items} item(s)"

            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for idx, item in enumerate(value):
                    item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                    err = self._validate_schema_value(item, item_schema, item_path)
                    if err:
                        return err
            return None

        if expected_type == "integer":
            if not self._is_integer(value):
                label = path or "value"
                return f"{label} must be an integer"
            minimum = schema.get("minimum")
            if isinstance(minimum, int) and value < minimum:
                label = path or "value"
                return f"{label} must be >= {minimum}"

        elif expected_type == "boolean":
            if not isinstance(value, bool):
                label = path or "value"
                return f"{label} must be a boolean"

        elif expected_type == "string":
            if not isinstance(value, str):
                label = path or "value"
                return f"{label} must be a string"

        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
            label = path or "value"
            return f"{label} must be one of: {', '.join(str(v) for v in enum_values)}"

        return None

    def _validate_tool_input(self, tool_name, payload):
        contract = _TOOL_CONTRACTS.get(tool_name)
        if not contract:
            return None
        schema = contract.get("parameters") or {}
        schema_error = self._validate_schema_value(payload, schema, "")
        if schema_error:
            return schema_error

        if tool_name == "manage_boxes":
            operation = payload.get("operation")
            if operation == "add":
                if "count" not in payload:
                    return "count is required when operation=add"
                if "box" in payload:
                    return "box is not allowed when operation=add"
                if "renumber_mode" in payload:
                    return "renumber_mode is only valid when operation=remove"
            elif operation == "remove":
                if "box" not in payload:
                    return "box is required when operation=remove"
                if "count" in payload:
                    return "count is not allowed when operation=remove"

        if tool_name == "search_records":
            has_recent = any(k in payload for k in ("recent_days", "recent_count"))
            if has_recent:
                if "recent_days" in payload and "recent_count" in payload:
                    return "Use either recent_days or recent_count, not both"
                mixed_fields = [
                    k for k in ("query", "mode", "max_results", "case_sensitive", "box", "position", "record_id", "active_only")
                    if k in payload
                ]
                if mixed_fields:
                    return "recent_* filters cannot be mixed with text/structured search fields"

        if tool_name == "query_thaw_events":
            view = payload.get("view", "events")
            if view == "summary":
                forbidden = [k for k in ("date", "start_date", "end_date", "action", "max_records") if k in payload]
                if forbidden:
                    return "view=summary only supports: view, days, all_history"
            elif "all_history" in payload:
                return "all_history is only valid when view=summary"

        if tool_name == "manage_staged":
            operation = payload.get("operation")
            has_index = "index" in payload
            has_key_fields = any(k in payload for k in ("action", "record_id", "position"))

            if operation in {"list", "clear"}:
                if has_index or has_key_fields:
                    return "index/action/record_id/position are only valid when operation=remove"
            elif operation == "remove":
                if has_index and has_key_fields:
                    return "Provide either index OR action+record_id+position, not both"
                if not has_index and not has_key_fields:
                    return "Provide either index OR action+record_id+position"
                if has_key_fields and not all(k in payload for k in ("action", "record_id", "position")):
                    return "action, record_id, and position are required when removing by key"

        if tool_name == "record_thaw":
            action = str(payload.get("action") or "取出").lower()
            if action in {"move", "移动"}:
                if "to_position" not in payload:
                    return "to_position is required when action=move"

        if tool_name == "rollback":
            backup_path = str(payload.get("backup_path") or "").strip()
            if not backup_path:
                return "backup_path must be a non-empty string"

        return None

    def _hint_for_error(self, tool_name, payload):
        error_code = str(payload.get("error_code") or "").strip()
        spec = self.tool_specs().get(tool_name, {})

        if error_code == "invalid_tool_input":
            required = spec.get("required") or []
            optional = spec.get("optional") or []
            required_text = ", ".join(required) if required else "(none)"
            optional_text = ", ".join(optional) if optional else "(none)"
            return (
                f"Check `{tool_name}` input fields. Required: {required_text}. "
                f"Optional: {optional_text}."
            )

        if error_code == "unknown_tool":
            available = payload.get("available_tools") or self.list_tools()
            available_text = ", ".join(str(name) for name in available)
            return f"Use one of available tools: {available_text}."

        if error_code == "invalid_mode":
            return "For `search_records`, use mode: fuzzy / exact / keywords."

        if error_code in {"load_failed", "write_failed", "rollback_failed", "backup_load_failed"}:
            return "Verify yaml_path exists and file permissions are correct, then retry."

        if error_code == "write_requires_execute_mode":
            return (
                "Write tools are execute-gated. Stage operations first, then let a human run Execute in GUI Plan tab. "
                "Use dry_run for preview-only checks."
            )

        if error_code == "record_not_found":
            return "Call `search_records` first and use a valid `record_id` from results."

        if error_code == "position_not_found":
            return "Use a position that belongs to the target record."

        if error_code == "position_conflict":
            return "Choose free slots via `list_empty_positions` or `recommend_positions`, then retry."

        if error_code == "box_not_empty":
            return "Remove all active tubes from that box first, then retry remove operation."

        if error_code in {"renumber_mode_required", "invalid_renumber_mode"}:
            return "When removing a middle box, choose renumber_mode: keep_gaps or renumber_contiguous."

        if error_code == "min_box_count":
            return "At least one box must remain; do not remove the last box."

        if error_code == "user_cancelled":
            return "User cancelled the confirmation dialog."

        if error_code == "invalid_move_target":
            return "For move operations, provide a valid `to_position` different from source position."

        if error_code in {"invalid_date"}:
            return "Use date format `YYYY-MM-DD` (for example: 2026-02-10)."

        if error_code in {"invalid_box", "invalid_position", "invalid_record_id"}:
            return "Provide valid box IDs and valid positions in the current layout (e.g. 12 or A1)."

        if error_code == "invalid_action":
            return "Use a supported action value: 取出 / 移动 (or takeout / move)."

        if error_code in {"empty_positions", "empty_entries"}:
            return "Provide at least one target position or entry before retrying."

        if error_code == "no_backups":
            return (
                "No backups exist yet; investigate write history first and confirm rollback intent with `question` tool "
                "before choosing a backup_path."
            )

        if error_code in {"validation_failed", "integrity_validation_failed", "rollback_backup_invalid"}:
            return (
                "Rollback target is invalid for current file state. Re-check backup_path against audit/timeline and "
                "ask user confirmation with `question` if needed before retrying."
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
                return (
                    "Preflight failed due to baseline integrity issues. "
                    f"Fetch affected records with `get_raw_entries` ids=[{ids_text}], then repair invalid fields via `edit_entry` "
                    "(for example, normalize `cell_line` to configured options), and retry staging."
                )
            return (
                "One or more write operations are invalid against current inventory state. "
                "Review blocked details, then retry only corrected operations."
            )

        if spec:
            return f"Adjust `{tool_name}` inputs according to `tool_specs`, then retry."
        return "Retry with corrected tool input."

    def _with_hint(self, tool_name, response):
        if not isinstance(response, dict):
            response = {
                "ok": False,
                "error_code": "invalid_tool_response",
                "message": f"Tool `{tool_name}` returned non-dict response.",
            }

        if response.get("ok") is False and "_hint" not in response:
            response = dict(response)
            response["_hint"] = self._hint_for_error(tool_name, response)
        return response

    def _run_question_tool(self, payload):
        """Validate question payload and return a waiting_for_user marker.

        The actual blocking (threading.Event.wait) happens in
        ReactAgent._run_tool_call, which emits the question event first
        and then waits for the GUI to call _set_answer / _cancel_answer.
        """
        questions = payload.get("questions", [])
        if not questions:
            return {
                "ok": False,
                "error_code": "no_questions",
                "message": "At least one question is required.",
            }

        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return {
                    "ok": False,
                    "error_code": "invalid_question_format",
                    "message": f"Question {i} must be a dict.",
                }
            if "header" not in q or "question" not in q:
                return {
                    "ok": False,
                    "error_code": "missing_required_field",
                    "message": f"Question {i} missing 'header' or 'question'.",
                }

        question_id = str(uuid.uuid4())

        # Reset synchronization state for this question round
        self._answer_event.clear()
        self._pending_answer = None
        self._answer_cancelled = False

        return {
            "ok": True,
            "waiting_for_user": True,
            "question_id": question_id,
            "questions": questions,
        }

    def _safe_call(self, tool_name, fn, include_expected=False):
        try:
            response = fn()
        except Exception as exc:
            payload = {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": str(exc),
            }
            if include_expected:
                payload["expected"] = self.tool_specs().get(tool_name)
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
                    return box, position
        except Exception:
            pass
        return 0, None

    @staticmethod
    def _item_desc(item):
        action = str(item.get("action") or "?")
        if action == "rollback":
            payload = item.get("payload") or {}
            backup_path = str(payload.get("backup_path") or "").strip()
            if backup_path:
                name = os.path.basename(backup_path)
                return f"rollback {name} ({backup_path})"
            return "rollback latest-backup"

        label = str(item.get("label") or item.get("record_id") or "-")
        box = item.get("box", "?")
        pos = item.get("position", "?")
        target = ""
        if action == "move":
            to_box = item.get("to_box")
            to_pos = item.get("to_position")
            if to_pos is not None:
                if to_box is not None:
                    target = f" -> Box {to_box}:{to_pos}"
                else:
                    target = f" -> {to_pos}"
        return f"{action} {label} @ Box {box}:{pos}{target}"

    def _stage_to_plan(self, tool_name, payload, trace_id=None):
        """Intercept write ops and stage as PlanItems for human approval."""

        input_error = self._validate_tool_input(tool_name, payload)
        if input_error:
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": input_error,
                },
            )

        items = []
        layout = self._load_layout()

        if tool_name == "add_entry":
            box_raw = payload.get("box")
            positions_raw = payload.get("positions")
            try:
                positions = self._normalize_positions(positions_raw, layout=layout) or []
                box = int(box_raw) if box_raw is not None else 0
            except (ValueError, TypeError) as exc:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": str(exc),
                })

            fields = dict(payload.get("fields") or {})

            items.append(
                build_add_plan_item(
                    box=box,
                    positions=positions,
                    frozen_at=payload.get("frozen_at"),
                    fields=fields,
                    source="ai",
                )
            )

        elif tool_name == "record_thaw":
            rid_raw = payload.get("record_id")
            if rid_raw in (None, ""):
                return self._with_hint(
                    tool_name,
                    {
                        "ok": False,
                        "error_code": "invalid_tool_input",
                        "message": "record_id is required",
                    },
                )

            try:
                rid = int(rid_raw)
            except (ValueError, TypeError) as exc:
                return self._with_hint(
                    tool_name,
                    {
                        "ok": False,
                        "error_code": "invalid_tool_input",
                        "message": f"record_id must be an integer: {exc}",
                    },
                )

            pos_raw = payload.get("position")
            pos = None
            if pos_raw not in (None, ""):
                try:
                    pos = self._parse_position(pos_raw, layout=layout, field_name="position")
                except (ValueError, TypeError) as exc:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "invalid_tool_input",
                            "message": str(exc),
                        },
                    )

            action_raw = payload.get("action", "取出")
            to_pos_raw = payload.get("to_position")
            to_pos = None
            if to_pos_raw not in (None, ""):
                try:
                    to_pos = self._parse_position(to_pos_raw, layout=layout, field_name="to_position")
                except ValueError as exc:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "invalid_tool_input",
                            "message": str(exc),
                        },
                    )

            to_box_raw = payload.get("to_box")
            to_box = int(to_box_raw) if to_box_raw not in (None, "") else None

            box, position = self._lookup_record_info(rid)
            if pos is None:
                if position is not None:
                    pos = int(position)
                else:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "invalid_tool_input",
                            "message": (
                                f"position is missing and cannot be inferred for record_id={rid}. "
                                f"record has no position (may be consumed)."
                            ),
                        },
                    )

            items.append(
                build_record_plan_item(
                    action=action_raw,
                    record_id=rid,
                    position=pos,
                    box=box,
                    date_str=payload.get("date"),
                    note=payload.get("note"),
                    to_position=to_pos,
                    to_box=to_box,
                    source="ai",
                    payload_action=str(action_raw).strip(),
                )
            )

        elif tool_name == "batch_thaw":
            entries = payload.get("entries")
            if isinstance(entries, str):
                try:
                    entries = parse_batch_entries(entries, layout=layout)
                except ValueError as exc:
                    return self._with_hint(tool_name, {
                        "ok": False, "error_code": "invalid_tool_input",
                        "message": str(exc),
                    })

            if not entries:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": "entries is required and cannot be empty",
                })

            action_raw = payload.get("action", "取出")

            # batch-level to_box (applies to all entries unless overridden)
            batch_to_box_raw = payload.get("to_box")
            batch_to_box = int(batch_to_box_raw) if batch_to_box_raw not in (None, "") else None

            for entry in entries:
                rid = None
                pos = None
                to_pos = None
                to_box = batch_to_box

                if isinstance(entry, (list, tuple)):
                    if len(entry) >= 4:
                        rid = int(entry[0])
                        pos = self._parse_position(entry[1], layout=layout, field_name="from_position")
                        to_pos = self._parse_position(entry[2], layout=layout, field_name="to_position")
                        to_box = int(entry[3])
                    elif len(entry) == 3:
                        rid = int(entry[0])
                        pos = self._parse_position(entry[1], layout=layout, field_name="from_position")
                        to_pos = self._parse_position(entry[2], layout=layout, field_name="to_position")
                    elif len(entry) == 2:
                        rid = int(entry[0])
                        pos = self._parse_position(entry[1], layout=layout, field_name="position")
                    elif len(entry) == 1:
                        rid = int(entry[0])
                    else:
                        continue
                elif isinstance(entry, dict):
                    rid = int(entry.get("record_id", entry.get("id", 0)) or 0)
                    raw_pos = entry.get("position")
                    if raw_pos is None:
                        raw_pos = entry.get("from_position")
                    if raw_pos not in (None, ""):
                        pos = self._parse_position(raw_pos, layout=layout, field_name="position")
                    raw_to_pos = entry.get("to_position")
                    if raw_to_pos not in (None, ""):
                        to_pos = self._parse_position(raw_to_pos, layout=layout, field_name="to_position")
                    raw_to_box = entry.get("to_box")
                    if raw_to_box not in (None, ""):
                        to_box = int(raw_to_box)
                else:
                    continue

                if not rid:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "invalid_tool_input",
                            "message": f"Invalid batch entry (missing record_id): {entry}",
                        },
                    )

                box, position = self._lookup_record_info(rid)
                if pos is None:
                    if position is not None:
                        pos = int(position)
                    else:
                        # Keep staging atomic: let plan validation reject schema-invalid rows.
                        pos = 0

                items.append(
                    build_record_plan_item(
                        action=action_raw,
                        record_id=rid,
                        position=pos,
                        box=box,
                        date_str=payload.get("date"),
                        note=payload.get("note"),
                        to_position=to_pos,
                        to_box=to_box,
                        source="ai",
                        payload_action=str(action_raw).strip(),
                    )
                )

        elif tool_name == "edit_entry":
            rid_raw = payload.get("record_id")
            if rid_raw in (None, ""):
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": "record_id is required",
                })
            try:
                rid = int(rid_raw)
            except (ValueError, TypeError) as exc:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": f"record_id must be an integer: {exc}",
                })
            fields = payload.get("fields")
            if not fields or not isinstance(fields, dict):
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": "fields must be a non-empty object",
                })
            box, position = self._lookup_record_info(rid)
            pos = int(position) if position is not None else 1
            items.append(
                build_edit_plan_item(
                    record_id=rid,
                    fields=fields,
                    box=box,
                    position=pos,
                    source="ai",
                )
            )

        elif tool_name == "rollback":
            backup_path = payload.get("backup_path")

            items.append(
                build_rollback_plan_item(
                    backup_path=str(backup_path),
                    source="ai",
                )
            )

        gate = validate_stage_request(
            existing_items=self._plan_store.list_items() if self._plan_store else [],
            incoming_items=items,
            yaml_path=self._yaml_path,
            bridge=None,
            run_preflight=True,
        )
        if gate.get("blocked"):
            gate_errors = list(gate.get("errors") or [])
            gate_blocked = list(gate.get("blocked_items") or [])
            has_preflight = any(err.get("kind") == "preflight" for err in gate_errors)
            error_code = "plan_preflight_failed" if has_preflight else "plan_validation_failed"
            repair_ids = self._extract_record_ids_from_payload(gate_errors, gate_blocked)

            detail_lines = []
            for blocked in gate_blocked[:3]:
                desc = self._item_desc(blocked)
                error = blocked.get("message") or blocked.get("error_code") or "Unknown error"
                if isinstance(error, str):
                    error = error.splitlines()[0].strip()
                detail_lines.append(f"{desc}: {error}")
            detail = "; ".join(detail_lines)
            if len(gate_blocked) > 3:
                detail += f"; ... and {len(gate_blocked) - 3} more"

            result_payload = {
                "staged_count": 0,
                "blocked_count": len(gate_blocked),
                "repair_candidates": {"record_ids": repair_ids} if repair_ids else {},
            }

            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": error_code,
                    "message": f"All operations rejected by validation: {detail}",
                    "staged": False,
                    "result": result_payload,
                    "blocked_items": gate_blocked,
                    "repair_candidates": {"record_ids": repair_ids} if repair_ids else {},
                },
            )

        staged = list(gate.get("accepted_items") or [])
        if not self._plan_store:
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "no_plan_store",
                    "message": "Plan store not available.",
                    "staged": False,
                    "result": {"staged_count": 0, "blocked_count": 0},
                },
            )
        self._plan_store.add(staged)

        summary = [self._item_desc(s) for s in staged]
        return {
            "ok": True,
            "staged": True,
            "message": (
                f"Staged {len(staged)} operation(s) for human approval in Plan tab: "
                + "; ".join(summary)
            ),
            "result": {"staged_count": len(staged)},
        }

    def run(self, tool_name, tool_input, trace_id=None):
        payload = dict(tool_input) if isinstance(tool_input, dict) else {}

        if tool_name not in _TOOL_CONTRACTS:
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "unknown_tool",
                    "message": f"Unknown tool: {tool_name}",
                    "available_tools": self.list_tools(),
                },
            )

        # Question tool keeps its own detailed validation/error codes.
        if tool_name == "question":
            return self._run_question_tool(payload)

        input_error = self._validate_tool_input(tool_name, payload)
        if input_error:
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": input_error,
                },
            )

        # Intercept write operations when plan_store is set
        if tool_name in _WRITE_TOOLS and self._plan_store is not None:
            return self._stage_to_plan(tool_name, payload, trace_id)

        if tool_name == "manage_boxes":
            def _call_manage_boxes():
                op = str(payload.get("operation") or "").strip().lower()
                if op not in {"add", "remove"}:
                    raise ValueError("operation must be add or remove")

                normalized_mode = payload.get("renumber_mode")

                add_count = None
                target_box = None

                if op == "add":
                    if "count" not in payload:
                        raise ValueError("count is required when operation=add")
                    if "box" in payload:
                        raise ValueError("box is not allowed when operation=add")
                    if normalized_mode not in (None, ""):
                        raise ValueError("renumber_mode is only valid when operation=remove")
                    add_count = self._required_int(payload, "count")
                else:
                    if "box" not in payload:
                        raise ValueError("box is required when operation=remove")
                    if "count" in payload:
                        raise ValueError("count is not allowed when operation=remove")
                    target_box = self._required_int(payload, "box")

                request = {
                    "operation": op,
                    "renumber_mode": normalized_mode,
                    "count": add_count if op == "add" else None,
                    "box": target_box if op == "remove" else None,
                }

                dry_run = self._as_bool(payload.get("dry_run", False), default=False)
                if dry_run:
                    call_kwargs = {
                        "yaml_path": self._yaml_path,
                        "operation": op,
                        "dry_run": True,
                        "execution_mode": "preflight",
                        "actor_context": self._actor_context(trace_id=trace_id),
                        "source": "agent.react",
                    }
                    if normalized_mode is not None:
                        call_kwargs["renumber_mode"] = normalized_mode
                    if op == "add":
                        call_kwargs["count"] = add_count
                    else:
                        call_kwargs["box"] = target_box
                    return tool_adjust_box_count(**call_kwargs)

                return {
                    "ok": True,
                    "waiting_for_user_confirmation": True,
                    "request": request,
                    "message": "Awaiting user confirmation in GUI.",
                }

            return self._safe_call(
                tool_name,
                _call_manage_boxes,
                include_expected=True,
            )

        if tool_name == "list_empty_positions":
            return self._safe_call(
                tool_name,
                lambda: tool_list_empty_positions(
                    yaml_path=self._yaml_path,
                    box=self._optional_int(payload, "box"),
                ),
            )

        if tool_name == "search_records":
            recent_days = self._optional_int(payload, "recent_days")
            recent_count = self._optional_int(payload, "recent_count")
            if recent_days is not None or recent_count is not None:
                return self._safe_call(
                    tool_name,
                    lambda: tool_recent_frozen(
                        yaml_path=self._yaml_path,
                        days=recent_days,
                        count=recent_count,
                    ),
                )

            mode = self._normalize_search_mode(payload.get("mode"))
            return self._safe_call(
                tool_name,
                lambda: tool_search_records(
                    yaml_path=self._yaml_path,
                    query=payload.get("query"),
                    mode=mode,
                    max_results=self._optional_int(payload, "max_results"),
                    case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
                    box=payload.get("box"),
                    position=payload.get("position"),
                    record_id=payload.get("record_id"),
                    active_only=(payload.get("active_only") if "active_only" in payload else None),
                ),
            )

        if tool_name == "query_thaw_events":
            view = payload.get("view", "events")
            if view == "summary":
                timeline_days = self._optional_int(payload, "days", default=30)
                timeline_days = 30 if timeline_days is None else int(timeline_days)
                return self._safe_call(
                    tool_name,
                    lambda: tool_collect_timeline(
                        yaml_path=self._yaml_path,
                        days=timeline_days,
                        all_history=self._as_bool(payload.get("all_history", False), default=False),
                    ),
                )

            days_value = self._optional_int(payload, "days")
            if days_value is not None:
                days_value = int(days_value)
            max_records_value = self._optional_int(payload, "max_records", default=0)
            max_records_value = 0 if max_records_value is None else int(max_records_value)

            return self._safe_call(
                tool_name,
                lambda: tool_query_thaw_events(
                    yaml_path=self._yaml_path,
                    date=payload.get("date"),
                    days=days_value,
                    start_date=payload.get("start_date"),
                    end_date=payload.get("end_date"),
                    action=payload.get("action"),
                    max_records=max_records_value,
                ),
            )

        if tool_name == "recommend_positions":
            return self._safe_call(
                tool_name,
                lambda: tool_recommend_positions(
                    yaml_path=self._yaml_path,
                    count=self._optional_int(payload, "count", default=2),
                    box_preference=self._optional_int(payload, "box_preference"),
                    strategy=payload.get("strategy", "consecutive"),
                ),
            )

        if tool_name == "generate_stats":
            return self._safe_call(
                tool_name,
                lambda: tool_generate_stats(yaml_path=self._yaml_path),
            )

        if tool_name == "get_raw_entries":
            def _call_get_raw_entries():
                ids = list(payload.get("ids") or [])
                return tool_get_raw_entries(
                    yaml_path=self._yaml_path,
                    ids=ids,
                )

            return self._safe_call(
                tool_name,
                _call_get_raw_entries,
                include_expected=True,
            )

        if tool_name == "edit_entry":
            def _call_edit_entry():
                rid = self._required_int(payload, "record_id")
                fields = payload.get("fields")
                if not fields or not isinstance(fields, dict):
                    raise ValueError("fields must be a non-empty object")
                return tool_edit_entry(
                    yaml_path=self._yaml_path,
                    record_id=rid,
                    fields=fields,
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )

            return self._safe_call(
                tool_name,
                _call_edit_entry,
                include_expected=True,
            )

        if tool_name == "add_entry":
            def _call_add_entry():
                layout = self._load_layout()
                box_val = self._required_int(payload, "box")
                frozen_at = payload.get("frozen_at")
                positions = self._normalize_positions(payload.get("positions"), layout=layout)
                fields = dict(payload.get("fields") or {})

                return tool_add_entry(
                    yaml_path=self._yaml_path,
                    box=box_val,
                    positions=positions,
                    frozen_at=frozen_at,
                    fields=fields,
                    dry_run=self._as_bool(payload.get("dry_run", False), default=False),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )

            return self._safe_call(
                tool_name,
                _call_add_entry,
                include_expected=True,
            )

        if tool_name == "record_thaw":
            def _call_record_thaw():
                layout = self._load_layout()
                position = None
                if payload.get("position") not in (None, ""):
                    position = self._parse_position(payload.get("position"), layout=layout, field_name="position")

                to_position = None
                if payload.get("to_position") not in (None, ""):
                    to_position = self._parse_position(
                        payload.get("to_position"),
                        layout=layout,
                        field_name="to_position",
                    )

                return tool_record_thaw(
                    yaml_path=self._yaml_path,
                    record_id=self._required_int(payload, "record_id"),
                    position=position,
                    date_str=payload.get("date"),
                    action=payload.get("action", "取出"),
                    to_position=to_position,
                    to_box=(
                        self._optional_int(payload, "to_box")
                        if payload.get("to_box") not in (None, "")
                        else None
                    ),
                    note=payload.get("note"),
                    dry_run=self._as_bool(payload.get("dry_run", False), default=False),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )

            return self._safe_call(
                tool_name,
                _call_record_thaw,
                include_expected=True,
            )

        if tool_name == "batch_thaw":
            def _call_batch_thaw():
                layout = self._load_layout()
                entries = payload.get("entries")
                if isinstance(entries, str):
                    entries = parse_batch_entries(entries, layout=layout)
                to_box_raw = payload.get("to_box")
                to_box = (
                    self._optional_int({"to_box": to_box_raw}, "to_box")
                    if to_box_raw not in (None, "")
                    else None
                )
                if to_box is not None and isinstance(entries, list):
                    expanded = []
                    for e in entries:
                        if isinstance(e, (list, tuple)):
                            if len(e) == 3:
                                expanded.append((*e, to_box))
                            elif len(e) == 2:
                                expanded.append((*e,))
                            else:
                                expanded.append(e)
                        else:
                            expanded.append(e)
                    entries = expanded
                return tool_batch_thaw(
                    yaml_path=self._yaml_path,
                    entries=entries,
                    date_str=payload.get("date"),
                    action=payload.get("action", "取出"),
                    note=payload.get("note"),
                    dry_run=self._as_bool(payload.get("dry_run", False), default=False),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )

            return self._safe_call(
                tool_name,
                _call_batch_thaw,
                include_expected=True,
            )

        if tool_name == "rollback":
            return self._safe_call(
                tool_name,
                lambda: tool_rollback(
                    yaml_path=self._yaml_path,
                    backup_path=payload.get("backup_path"),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                ),
            )

        # --- Plan staging management (read/modify staging area, not YAML) ---

        if tool_name == "manage_staged":
            operation = payload.get("operation")

            if operation == "list":
                if not self._plan_store:
                    return {
                        "ok": True,
                        "result": {"items": [], "count": 0},
                        "message": "No plan store available.",
                    }
                items = self._plan_store.list_items()
                summary = []
                for i, item in enumerate(items):
                    entry = {
                        "index": i,
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

            if not self._plan_store:
                return {
                    "ok": False,
                    "error_code": "no_plan_store",
                    "message": "Plan store not available.",
                }

            if operation == "remove":
                idx = self._optional_int(payload, "index")
                if idx is not None:
                    removed = self._plan_store.remove_by_index(idx)
                    if removed is None:
                        max_idx = self._plan_store.count() - 1
                        return self._with_hint(tool_name, {
                            "ok": False,
                            "error_code": "invalid_index",
                            "message": f"Index {idx} out of range (0..{max_idx}).",
                        })
                    return {
                        "ok": True,
                        "message": f"Removed item at index {idx}: {self._item_desc(removed)}",
                        "result": {"removed": 1},
                    }

                action = payload.get("action")
                rid = self._optional_int(payload, "record_id")
                pos = self._optional_int(payload, "position")
                count = self._plan_store.remove_by_key(action, rid, pos)
                if count == 0:
                    return self._with_hint(tool_name, {
                        "ok": False,
                        "error_code": "not_found",
                        "message": "No matching staged item found.",
                    })
                return {
                    "ok": True,
                    "message": f"Removed {count} matching item(s).",
                    "result": {"removed": count},
                }

            if operation == "clear":
                cleared = self._plan_store.clear()
                return {
                    "ok": True,
                    "message": f"Cleared {len(cleared)} staged item(s).",
                    "result": {"cleared_count": len(cleared)},
                }

        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {tool_name}",
                "available_tools": self.list_tools(),
            },
        )
