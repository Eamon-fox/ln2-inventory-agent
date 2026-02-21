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
from lib.position_fmt import display_to_pos
from lib.validators import parse_positions
from lib.yaml_ops import load_yaml
from app_gui.i18n import tr
from . import tool_runner_handlers as _runner_handlers
from . import tool_runner_staging as _runner_staging
from . import tool_runner_validation as _runner_validation
from . import tool_runner_hints as _runner_hints

_WRITE_TOOLS = {"add_entry", "record_takeout", "batch_takeout", "rollback", "edit_entry"}


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
    "query_takeout_events": {
        "description": "Query takeout/move events, or timeline summary via view=summary.",
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
    "record_takeout": {
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
                "action": {"type": "string", "enum": ["takeout", "move", "Takeout", "Move"]},
                "to_position": {
                    "oneOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "string"},
                    ]
                },
                "to_box": {"type": "integer", "minimum": 1},
                "dry_run": {"type": "boolean"},
            },
            "required": ["record_id", "date"],
            "additionalProperties": False,
        },
    },
    "batch_takeout": {
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
                "action": {"type": "string", "enum": ["takeout", "move", "Takeout", "Move"]},
                "to_box": {"type": "integer", "minimum": 1},
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

    @staticmethod
    def _parse_position(value, layout=None, field_name="position"):
        if value in (None, ""):
            return None
        try:
            return int(display_to_pos(value, layout))
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
        if isinstance(value, list):
            return [self._parse_position(item, layout=layout) for item in value]
        if isinstance(value, tuple):
            return [self._parse_position(item, layout=layout) for item in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            return parse_positions(value, layout=layout)
        return value

    _normalize_search_mode = staticmethod(_runner_validation._normalize_search_mode)

    def list_tools(self):
        return list(_TOOL_CONTRACTS.keys())

    tool_specs = _runner_validation.tool_specs
    tool_schemas = _runner_validation.tool_schemas
    _is_integer = staticmethod(_runner_validation._is_integer)
    _validate_schema_value = _runner_validation._validate_schema_value
    _validate_tool_input = _runner_validation._validate_tool_input

    _hint_for_error = _runner_hints._hint_for_error
    _with_hint = _runner_hints._with_hint

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
                "message": self._msg(
                    "question.atLeastOneRequired",
                    "At least one question is required.",
                ),
            }

        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return {
                    "ok": False,
                    "error_code": "invalid_question_format",
                    "message": self._msg(
                        "question.mustBeDict",
                        "Question {index} must be a dict.",
                        index=i,
                    ),
                }
            if "header" not in q or "question" not in q:
                return {
                    "ok": False,
                    "error_code": "missing_required_field",
                    "message": self._msg(
                        "question.missingHeaderOrQuestion",
                        "Question {index} missing 'header' or 'question'.",
                        index=i,
                    ),
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
    _stage_items_record_takeout = _runner_staging._stage_items_record_takeout
    _stage_items_batch_takeout = _runner_staging._stage_items_batch_takeout
    _stage_items_edit_entry = _runner_staging._stage_items_edit_entry
    _stage_items_rollback = _runner_staging._stage_items_rollback
    _build_stage_blocked_response = _runner_staging._build_stage_blocked_response

    def run(self, tool_name, tool_input, trace_id=None):
        payload = dict(tool_input) if isinstance(tool_input, dict) else {}
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
    _run_list_empty_positions = _runner_handlers._run_list_empty_positions
    _run_search_records = _runner_handlers._run_search_records
    _run_query_takeout_events = _runner_handlers._run_query_takeout_events
    _run_recommend_positions = _runner_handlers._run_recommend_positions
    _run_generate_stats = _runner_handlers._run_generate_stats
    _run_get_raw_entries = _runner_handlers._run_get_raw_entries
    _run_edit_entry = _runner_handlers._run_edit_entry
    _run_add_entry = _runner_handlers._run_add_entry
    _run_record_takeout = _runner_handlers._run_record_takeout
    _run_batch_takeout = _runner_handlers._run_batch_takeout
    _run_rollback = _runner_handlers._run_rollback
    _run_manage_staged = _runner_handlers._run_manage_staged

    def _run_dispatch(self, tool_name, payload, trace_id=None):
        if tool_name not in _TOOL_CONTRACTS:
            return self._unknown_tool_response(tool_name)

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

        # Intercept write operations when plan_store is set.
        if tool_name in _WRITE_TOOLS and self._plan_store is not None:
            return self._stage_to_plan(tool_name, payload, trace_id)

        handlers = {
            "manage_boxes": self._run_manage_boxes,
            "list_empty_positions": self._run_list_empty_positions,
            "search_records": self._run_search_records,
            "query_takeout_events": self._run_query_takeout_events,
            "recommend_positions": self._run_recommend_positions,
            "generate_stats": self._run_generate_stats,
            "get_raw_entries": self._run_get_raw_entries,
            "edit_entry": self._run_edit_entry,
            "add_entry": self._run_add_entry,
            "record_takeout": self._run_record_takeout,
            "batch_takeout": self._run_batch_takeout,
            "rollback": self._run_rollback,
            "manage_staged": self._run_manage_staged,
        }
        handler = handlers.get(tool_name)
        if callable(handler):
            return handler(payload, trace_id)
        return self._unknown_tool_response(tool_name)



