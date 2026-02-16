"""Tool dispatcher for agent runtime, built on unified Tool API."""

import os
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
    tool_list_backups,
    tool_query_inventory,
    tool_query_thaw_events,
    tool_recent_frozen,
    tool_recommend_positions,
    tool_record_thaw,
    tool_rollback,
    tool_search_records,
)
from app_gui.plan_gate import validate_plan_batch
from lib.plan_item_factory import build_add_plan_item, build_edit_plan_item, build_record_plan_item, build_rollback_plan_item
from lib.validators import parse_positions
from lib.yaml_ops import load_yaml

_WRITE_TOOLS = {"add_entry", "record_thaw", "batch_thaw", "rollback", "edit_entry"}


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
        return int(value)

    @staticmethod
    def _optional_int(payload, key, default=None):
        value = payload.get(key)
        if value in (None, ""):
            return default
        return int(value)

    @staticmethod
    def _first_value(payload, *keys):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return None

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
    def _normalize_positions(value):
        if value in (None, ""):
            return None
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, tuple):
            return [int(item) for item in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            return parse_positions(value)
        return value

    @staticmethod
    def _normalize_search_mode(value):
        if value in (None, ""):
            return "fuzzy"

        text = str(value).strip().lower()
        if text in {"fuzzy", "exact", "keywords"}:
            return text

        aliases = {
            "keyword": "keywords",
            "kw": "keywords",
            "contains": "fuzzy",
            "substring": "fuzzy",
            "strict": "exact",
        }
        return aliases.get(text, "fuzzy")

    @staticmethod
    def _default_param_schema(field_name):
        integer_fields = {
            "box",
            "position",
            "days",
            "count",
            "max_results",
            "max_records",
            "record_id",
            "box_preference",
            "to_position",
        }
        boolean_fields = {
            "case_sensitive",
            "all_history",
            "dry_run",
        }
        if field_name in integer_fields:
            return {"type": "integer"}
        if field_name in boolean_fields:
            return {"type": "boolean"}
        if field_name == "positions":
            return {
                "oneOf": [
                    {"type": "array", "items": {"type": "integer"}},
                    {"type": "string"},
                ]
            }
        if field_name in {"entries", "ids"}:
            return {
                "oneOf": [
                    {"type": "array"},
                    {"type": "string"},
                ]
            }
        return {"type": "string"}

    def list_tools(self):
        return [
            "query_inventory",
            "list_empty_positions",
            "search_records",
            "recent_frozen",
            "query_thaw_events",
            "collect_timeline",
            "recommend_positions",
            "generate_stats",
            "get_raw_entries",
            "add_entry",
            "edit_entry",
            "record_thaw",
            "batch_thaw",
            "rollback",
            "manage_boxes",
            "question",
            "list_staged",
            "remove_staged",
            "clear_staged",
        ]

    def tool_specs(self):
        """Compact tool schemas for LLM prompt grounding."""
        return {
            "query_inventory": {
                "required": [],
                "optional": ["box", "position", "cell_line"],
                "description": "Query inventory records. Pass any user field key as a filter (e.g. cell_line, short_name).",
                "aliases": {
                    "cell_line": ["cell", "cell_line"],
                    "short_name": ["short"],
                },
            },
            "list_empty_positions": {
                "required": [],
                "optional": ["box"],
            },
            "search_records": {
                "required": ["query"],
                "optional": ["mode", "max_results", "case_sensitive"],
                "description": "Search inventory records by text.",
                "params": {
                    "query": {
                        "type": "string",
                        "description": "Search text (cell line, short name, notes, etc).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["fuzzy", "exact", "keywords"],
                        "default": "fuzzy",
                        "description": "Search strategy: fuzzy substring, exact substring, or keywords AND search.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional max number of records to return.",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether matching is case-sensitive.",
                    },
                },
            },
            "recent_frozen": {
                "required": [],
                "optional": ["days", "count"],
            },
            "query_thaw_events": {
                "required": [],
                "optional": ["date", "days", "start_date", "end_date", "action", "max_records"],
                "params": {
                    "action": {
                        "type": "string",
                        "description": "Action filter. Use one of: 取出/复苏/扔掉/移动 or takeout/thaw/discard/move.",
                    },
                },
            },
            "collect_timeline": {
                "required": [],
                "optional": ["days", "all_history"],
            },
            "recommend_positions": {
                "required": [],
                "optional": ["count", "box_preference", "strategy"],
            },
            "generate_stats": {
                "required": [],
                "optional": [],
            },
            "get_raw_entries": {
                "required": ["ids"],
                "optional": [],
            },
            "edit_entry": {
                "required": ["record_id", "fields"],
                "optional": [],
                "description": "Edit metadata fields of an existing record. "
                               "Allowed fields: frozen_at plus any user-defined fields from meta.custom_fields. "
                               "Structural fields (id, box, positions) cannot be changed.",
                "params": {
                    "record_id": {
                        "type": "integer",
                        "description": "ID of the record to edit.",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Key-value pairs of fields to update.",
                    },
                },
            },
            "add_entry": {
                "required": ["box", "positions", "frozen_at"],
                "optional": ["fields", "cell_line", "dry_run"],
                "aliases": {
                    "positions": ["position", "slot"],
                    "frozen_at": ["date"],
                    "cell_line": ["cell", "cell_line"],
                },
                "description": "Add a new frozen entry. Pass cell_line as a top-level param (value from cell_line_options). Pass other user fields in the 'fields' dict (e.g. short_name).",
                "notes": "positions accepts list[int] or comma string like '1,2,3'. fields is a dict of user field values.",
            },
            "record_thaw": {
                "required": ["record_id", "date"],
                "optional": ["position", "action", "to_position", "to_box", "note", "dry_run"],
                "aliases": {
                    "record_id": ["id"],
                    "position": ["pos", "slot"],
                    "to_position": ["to_pos", "target_position"],
                    "to_box": ["target_box", "new_box", "dest_box"],
                    "note": ["notes", "memo"],
                },
                "notes": "If position is omitted, the tool will infer the tube's current active position by record_id (tube-level model).",
                "params": {
                    "action": {
                        "type": "string",
                        "description": "Use one of: 取出/复苏/扔掉/移动 or takeout/thaw/discard/move.",
                    },
                    "to_position": {
                        "type": "integer",
                        "description": "Target position for move action. Required when action is 移动/move.",
                    },
                    "to_box": {
                        "type": "integer",
                        "description": "Target box for cross-box move. If provided, the record's box field is updated.",
                    },
                },
            },
            "batch_thaw": {
                "required": ["entries"],
                "optional": ["date", "action", "to_box", "note", "dry_run"],
                "notes": "entries can be list[[record_id, position], ...] or '182,183' or '182:23,183:41'; for move use '182:23->31,183:41->42'; for cross-box move use '4:5->4:1' (id:from->to:target_box) or set to_box for all entries.",
                "params": {
                    "action": {
                        "type": "string",
                        "description": "Use one of: 取出/复苏/扔掉/移动 or takeout/thaw/discard/move.",
                    },
                    "to_box": {
                        "type": "integer",
                        "description": "Target box for ALL entries in this batch (cross-box move). Each entry moves to this box.",
                    },
                },
            },
            "rollback": {
                "required": [],
                "optional": ["backup_path"],
                "description": "Rollback inventory YAML to a backup snapshot. Prefer explicit backup_path after audit/timeline checks.",
                "notes": "If backup selection is ambiguous, ask the user with question tool first, then stage rollback and wait for human Execute confirmation.",
            },
            "manage_boxes": {
                "required": ["operation"],
                "optional": ["count", "box", "renumber_mode", "dry_run"],
                "description": "Safely add/remove inventory boxes. Removing a middle box requires choosing keep_gaps or renumber_contiguous.",
                "params": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "remove"],
                        "description": "add = append new box IDs; remove = delete a box ID when empty.",
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "How many boxes to add when operation=add.",
                    },
                    "box": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Target box ID to remove when operation=remove.",
                    },
                    "renumber_mode": {
                        "type": "string",
                        "enum": ["keep_gaps", "renumber_contiguous"],
                        "description": "Required when removing a middle box.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate and preview only; do not write YAML.",
                    },
                },
            },
            "question": {
                "required": ["questions"],
                "optional": [],
                "description": "Ask the user clarifying questions before proceeding. "
                               "Use ONLY when you cannot infer the answer from inventory data. "
                               "Do NOT use for greetings or when the answer is obvious.",
                "params": {
                    "questions": {
                        "type": "array",
                        "description": "List of question objects.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "header": {
                                    "type": "string",
                                    "description": "Short label (max 30 chars). E.g. 'Cell Line', 'Box Number'.",
                                },
                                "question": {
                                    "type": "string",
                                    "description": "The question text.",
                                },
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "If provided, user picks from these choices.",
                                },
                                "multiple": {
                                    "type": "boolean",
                                    "description": "Allow multiple selections. Default false.",
                                },
                            },
                            "required": ["header", "question"],
                        },
                    }
                },
                "notes": "question tool is NOT a write tool. It blocks the worker thread until user answers. "
                         "Do not call question in parallel with other tools.",
            },
            "list_staged": {
                "required": [],
                "optional": [],
                "description": "List all currently staged plan items awaiting human approval.",
            },
            "remove_staged": {
                "required": [],
                "optional": ["index", "action", "record_id", "position"],
                "description": "Remove a staged plan item by 0-based index OR by key (action + record_id + position). Provide either index OR the key fields.",
                "params": {
                    "index": {"type": "integer", "description": "0-based index of the item to remove."},
                    "action": {"type": "string", "description": "Action of the item to remove (used with record_id + position)."},
                    "record_id": {"type": "integer", "description": "Record ID of the item to remove."},
                    "position": {"type": "integer", "description": "Position of the item to remove."},
                },
            },
            "clear_staged": {
                "required": [],
                "optional": [],
                "description": "Clear all staged plan items.",
            },
        }

    def tool_schemas(self):
        """OpenAI-compatible function tool schemas for native tool calling."""
        specs = self.tool_specs()
        schemas = []

        for name in self.list_tools():
            spec = specs.get(name, {})
            required_fields = list(spec.get("required") or [])
            optional_fields = list(spec.get("optional") or [])
            param_specs = spec.get("params") if isinstance(spec.get("params"), dict) else {}

            properties = {}
            for field_name in required_fields + optional_fields:
                field_schema = param_specs.get(field_name)
                if isinstance(field_schema, dict):
                    properties[field_name] = dict(field_schema)
                else:
                    properties[field_name] = self._default_param_schema(field_name)

            for field_name, field_schema in param_specs.items():
                if field_name not in properties and isinstance(field_schema, dict):
                    properties[field_name] = dict(field_schema)

            parameters = {
                "type": "object",
                "properties": properties,
                "required": required_fields,
                "additionalProperties": False,
            }

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec.get("description") or f"LN2 inventory tool: {name}",
                        "parameters": parameters,
                    },
                }
            )

        return schemas

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

        if error_code == "record_not_found":
            return "Call `query_inventory` first and use a valid `record_id` from results."

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

        if error_code in {"invalid_box", "invalid_position"}:
            return "Provide integer values in the configured inventory range."

        if error_code == "invalid_action":
            return "Use a supported action value such as 取出 / 复苏 / 扔掉 / 移动."

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
        """Quick lookup to get (box, label, position) for a record ID."""
        from lib.custom_fields import get_display_key
        try:
            result = tool_get_raw_entries(yaml_path=self._yaml_path, ids=[record_id])
            if result.get("ok"):
                entries = result.get("result", {}).get("entries", [])
                if entries:
                    rec = entries[0]
                    box = int(rec.get("box", 0))
                    # Use display_key from meta for label
                    try:
                        data = load_yaml(self._yaml_path)
                        dk = get_display_key(data.get("meta", {}))
                    except Exception:
                        dk = "short_name"
                    label = rec.get(dk) or rec.get("short_name") or "-"
                    position = rec.get("position")
                    return box, label, position
        except Exception:
            pass
        return 0, "-", None

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

        items = []

        if tool_name == "add_entry":
            box_raw = self._first_value(payload, "box", "box_num")
            positions_raw = payload.get("positions")
            if positions_raw in (None, ""):
                positions_raw = self._first_value(payload, "position", "slot")
            try:
                positions = self._normalize_positions(positions_raw) or []
                box = int(box_raw) if box_raw is not None else 0
            except (ValueError, TypeError) as exc:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": str(exc),
                })

            # Collect user fields from payload
            fields = payload.get("fields")
            if not isinstance(fields, dict):
                fields = {}
            # Also pick up common aliases at top level for LLM convenience
            for alias_key, canonical in [
                ("cell_line", "cell_line"), ("cell", "cell_line"),
                ("short_name", "short_name"), ("short", "short_name"), ("name", "short_name"),
                ("note", "note"), ("notes", "note"), ("memo", "note"),
                ("plasmid_name", "plasmid_name"), ("plasmid", "plasmid_name"),
                ("plasmid_id", "plasmid_id"),
            ]:
                if alias_key in payload and canonical not in fields:
                    val = payload[alias_key]
                    if val not in (None, ""):
                        fields[canonical] = val

            items.append(
                build_add_plan_item(
                    box=box,
                    positions=positions,
                    frozen_at=self._first_value(payload, "frozen_at", "date"),
                    fields=fields,
                    source="ai",
                )
            )

        elif tool_name == "record_thaw":
            rid_raw = self._first_value(payload, "record_id", "id")
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

            pos_raw = self._first_value(payload, "position", "pos", "slot")
            pos = None
            if pos_raw not in (None, ""):
                try:
                    pos = int(pos_raw)
                except (ValueError, TypeError) as exc:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "invalid_tool_input",
                            "message": f"position must be an integer when provided: {exc}",
                        },
                    )

            action_raw = payload.get("action", "Takeout")
            to_pos_raw = self._first_value(payload, "to_position", "to_pos", "target_position")
            to_pos = None
            if to_pos_raw not in (None, ""):
                to_pos = int(to_pos_raw)

            to_box_raw = self._first_value(payload, "to_box", "target_box", "new_box", "dest_box")
            to_box = int(to_box_raw) if to_box_raw not in (None, "") else None

            box, label, position = self._lookup_record_info(rid)
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
                    label=label,
                    date_str=self._first_value(payload, "date", "thaw_date"),
                    note=self._first_value(payload, "note", "notes", "memo"),
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
                    entries = parse_batch_entries(entries)
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

            action_raw = payload.get("action", "Takeout")

            # batch-level to_box (applies to all entries unless overridden)
            batch_to_box_raw = self._first_value(payload, "to_box", "target_box", "new_box", "dest_box")
            batch_to_box = int(batch_to_box_raw) if batch_to_box_raw not in (None, "") else None

            for entry in entries:
                rid = None
                pos = None
                to_pos = None
                to_box = batch_to_box

                if isinstance(entry, (list, tuple)):
                    if len(entry) >= 4:
                        rid = int(entry[0])
                        pos = int(entry[1])
                        to_pos = int(entry[2])
                        to_box = int(entry[3])
                    elif len(entry) == 3:
                        rid = int(entry[0])
                        pos = int(entry[1])
                        to_pos = int(entry[2])
                    elif len(entry) == 2:
                        rid = int(entry[0])
                        pos = int(entry[1])
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
                        pos = int(raw_pos)
                    raw_to_pos = entry.get("to_position")
                    if raw_to_pos not in (None, ""):
                        to_pos = int(raw_to_pos)
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

                box, label, position = self._lookup_record_info(rid)
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
                        label=label,
                        date_str=payload.get("date"),
                        note=payload.get("note"),
                        to_position=to_pos,
                        to_box=to_box,
                        source="ai",
                        payload_action=str(action_raw).strip(),
                    )
                )

        elif tool_name == "edit_entry":
            rid_raw = self._first_value(payload, "record_id", "id")
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
            box, label, position = self._lookup_record_info(rid)
            pos = int(position) if position is not None else 1
            items.append(
                build_edit_plan_item(
                    record_id=rid,
                    fields=fields,
                    box=box,
                    position=pos,
                    label=label,
                    source="ai",
                )
            )

        elif tool_name == "rollback":
            backup_path = payload.get("backup_path")
            if backup_path in (None, ""):
                backups = tool_list_backups(self._yaml_path)
                if not backups:
                    return self._with_hint(
                        tool_name,
                        {
                            "ok": False,
                            "error_code": "no_backups",
                            "message": "No backups exist yet; provide `backup_path` or create backups before rollback.",
                        },
                    )
                backup_path = backups[0]

            items.append(
                build_rollback_plan_item(
                    backup_path=str(backup_path),
                    source="ai",
                )
            )

        gate_result = validate_plan_batch(
            items=items,
            yaml_path=self._yaml_path,
            bridge=None,
            run_preflight=True,
        )
        validated_items = list(gate_result.get("accepted_items") or [])
        errors = list(gate_result.get("errors") or [])
        blocked_payload = list(gate_result.get("blocked_items") or [])
        blocked_count = len(blocked_payload)
        has_preflight_errors = any(err.get("kind") == "preflight" for err in errors)

        if blocked_count:
            detail_lines = []
            for blocked in blocked_payload[:3]:
                desc = self._item_desc(blocked)
                detail_lines.append(f"{desc}: {blocked.get('message')}")
            detail = "; ".join(detail_lines)
            if blocked_count > 3:
                detail += f"; ... and {blocked_count - 3} more"

            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "plan_preflight_failed" if has_preflight_errors else "plan_validation_failed",
                    "message": f"All operations rejected by validation: {detail}",
                    "staged": False,
                    "result": {"staged_count": 0, "blocked_count": blocked_count},
                    "blocked_items": blocked_payload,
                },
            )

        staged = list(validated_items)
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
        payload = dict(tool_input or {})

        # Question tool — returns marker for _run_tool_call to handle blocking
        if tool_name == "question":
            return self._run_question_tool(payload)

        # Intercept write operations when plan_store is set
        if tool_name in _WRITE_TOOLS and self._plan_store is not None:
            return self._stage_to_plan(tool_name, payload, trace_id)

        if tool_name == "manage_boxes":
            def _call_manage_boxes():
                op_raw = self._first_value(payload, "operation", "action")
                if op_raw in (None, ""):
                    raise ValueError("operation is required")

                op_text = str(op_raw).strip().lower()
                op_alias = {
                    "add": "add",
                    "add_boxes": "add",
                    "increase": "add",
                    "remove": "remove",
                    "remove_box": "remove",
                    "delete": "remove",
                    "删除": "remove",
                    "增加": "add",
                }
                op = op_alias.get(op_text)
                if op not in {"add", "remove"}:
                    raise ValueError("operation must be add or remove")

                normalized_mode = None
                mode_raw = self._first_value(
                    payload,
                    "renumber_mode",
                    "remove_mode",
                    "remove_strategy",
                )
                if mode_raw not in (None, ""):
                    mode_text = str(mode_raw).strip().lower()
                    mode_alias = {
                        "keep_gaps": "keep_gaps",
                        "keep": "keep_gaps",
                        "gaps": "keep_gaps",
                        "renumber_contiguous": "renumber_contiguous",
                        "renumber": "renumber_contiguous",
                        "compact": "renumber_contiguous",
                    }
                    normalized_mode = mode_alias.get(mode_text, mode_text)

                add_count = None
                target_box = None

                if op == "add":
                    add_count = self._optional_int(payload, "count", default=1) or 1
                else:
                    box_raw = self._first_value(payload, "box", "target_box", "remove_box", "box_id")
                    if box_raw in (None, ""):
                        raise ValueError("box is required when operation=remove")
                    target_box = int(box_raw)

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

        if tool_name == "query_inventory":
            def _call_query():
                filters = {}
                # Known structural filters
                box_val = self._optional_int(payload, "box")
                if box_val is not None:
                    filters["box"] = box_val
                pos_val = self._optional_int(payload, "position")
                if pos_val is not None:
                    filters["position"] = pos_val
                # Map common aliases to canonical field names
                alias_map = {
                    "cell": "cell_line", "cell_line": "cell_line",
                    "short": "short_name", "short_name": "short_name",
                    "plasmid": "plasmid_name", "plasmid_name": "plasmid_name",
                    "plasmid_id": "plasmid_id",
                    "note": "note",
                }
                for k, v in payload.items():
                    if v in (None, "") or k in ("box", "position", "tool_name"):
                        continue
                    canonical = alias_map.get(k)
                    if canonical and canonical not in filters:
                        filters[canonical] = str(v)
                return tool_query_inventory(
                    yaml_path=self._yaml_path,
                    **filters,
                )
            return self._safe_call(
                tool_name,
                _call_query,
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
            mode = self._normalize_search_mode(payload.get("mode"))
            return self._safe_call(
                tool_name,
                lambda: tool_search_records(
                    yaml_path=self._yaml_path,
                    query=payload.get("query", ""),
                    mode=mode,
                    max_results=self._optional_int(payload, "max_results"),
                    case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
                ),
            )

        if tool_name == "recent_frozen":
            return self._safe_call(
                tool_name,
                lambda: tool_recent_frozen(
                    yaml_path=self._yaml_path,
                    days=self._optional_int(payload, "days"),
                    count=self._optional_int(payload, "count"),
                ),
            )

        if tool_name == "query_thaw_events":
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

        if tool_name == "collect_timeline":
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
                ids = payload.get("ids", [])
                if isinstance(ids, str):
                    ids = [part.strip() for part in ids.split(",") if part.strip()]
                ids = [int(item) for item in ids]
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
                box_raw = self._first_value(payload, "box", "box_num")
                box_val = int(box_raw) if box_raw is not None else 0
                frozen_at = self._first_value(payload, "frozen_at", "date")

                positions_raw = payload.get("positions")
                if positions_raw in (None, ""):
                    positions_raw = self._first_value(payload, "position", "slot")
                positions = self._normalize_positions(positions_raw)

                # Collect user fields
                fields = payload.get("fields")
                if not isinstance(fields, dict):
                    fields = {}
                for alias_key, canonical in [
                    ("cell_line", "cell_line"), ("cell", "cell_line"),
                    ("short_name", "short_name"), ("short", "short_name"), ("name", "short_name"),
                    ("note", "note"), ("notes", "note"), ("memo", "note"),
                    ("plasmid_name", "plasmid_name"), ("plasmid", "plasmid_name"),
                    ("plasmid_id", "plasmid_id"),
                ]:
                    if alias_key in payload and canonical not in fields:
                        val = payload[alias_key]
                        if val not in (None, ""):
                            fields[canonical] = val

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
                normalized = dict(payload)
                normalized["record_id"] = self._first_value(payload, "record_id", "id")
                normalized["position"] = self._first_value(payload, "position", "pos", "slot")
                normalized["date"] = self._first_value(payload, "date", "thaw_date")
                normalized["to_position"] = self._first_value(payload, "to_position", "to_pos", "target_position")
                normalized["to_box"] = self._first_value(payload, "to_box", "target_box", "new_box", "dest_box")
                normalized["note"] = self._first_value(payload, "note", "notes", "memo")
                return tool_record_thaw(
                    yaml_path=self._yaml_path,
                    record_id=self._required_int(normalized, "record_id"),
                    position=self._optional_int(normalized, "position"),
                    date_str=normalized.get("date"),
                    action=payload.get("action", "取出"),
                    to_position=(
                        self._optional_int(normalized, "to_position")
                        if normalized.get("to_position") not in (None, "")
                        else None
                    ),
                    to_box=(
                        self._optional_int(normalized, "to_box")
                        if normalized.get("to_box") not in (None, "")
                        else None
                    ),
                    note=normalized.get("note"),
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
                entries = payload.get("entries")
                if isinstance(entries, str):
                    entries = parse_batch_entries(entries)
                to_box_raw = self._first_value(payload, "to_box", "target_box", "new_box", "dest_box")
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

        # --- Plan staging tools (read/modify staging area, not YAML) ---

        if tool_name == "list_staged":
            if not self._plan_store:
                return {"ok": True, "result": {"items": [], "count": 0},
                        "message": "No plan store available."}
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

        if tool_name == "remove_staged":
            if not self._plan_store:
                return {"ok": False, "error_code": "no_plan_store",
                        "message": "Plan store not available."}
            idx = self._optional_int(payload, "index")
            if idx is not None:
                removed = self._plan_store.remove_by_index(idx)
                if removed is None:
                    max_idx = self._plan_store.count() - 1
                    return self._with_hint(tool_name, {
                        "ok": False, "error_code": "invalid_index",
                        "message": f"Index {idx} out of range (0..{max_idx}).",
                    })
                return {"ok": True,
                        "message": f"Removed item at index {idx}: {self._item_desc(removed)}",
                        "result": {"removed": 1}}
            action = payload.get("action")
            rid = self._optional_int(payload, "record_id")
            pos = self._optional_int(payload, "position")
            if action is None and rid is None and pos is None:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": "Provide either 'index' or 'action'+'record_id'+'position'.",
                })
            count = self._plan_store.remove_by_key(action, rid, pos)
            if count == 0:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "not_found",
                    "message": "No matching staged item found.",
                })
            return {"ok": True, "message": f"Removed {count} matching item(s).",
                    "result": {"removed": count}}

        if tool_name == "clear_staged":
            if not self._plan_store:
                return {"ok": False, "error_code": "no_plan_store",
                        "message": "Plan store not available."}
            cleared = self._plan_store.clear()
            return {"ok": True, "message": f"Cleared {len(cleared)} staged item(s).",
                    "result": {"cleared_count": len(cleared)}}

        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {tool_name}",
                "available_tools": self.list_tools(),
            },
        )
