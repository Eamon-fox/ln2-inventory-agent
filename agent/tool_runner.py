"""Tool dispatcher for agent runtime, built on unified Tool API."""

from lib.tool_api import (
    build_actor_context,
    parse_batch_entries,
    tool_add_entry,
    tool_batch_thaw,
    tool_collect_timeline,
    tool_generate_stats,
    tool_get_raw_entries,
    tool_list_empty_positions,
    tool_query_inventory,
    tool_query_thaw_events,
    tool_recent_frozen,
    tool_recommend_positions,
    tool_record_thaw,
    tool_rollback,
    tool_search_records,
)
from app_gui.plan_gate import validate_plan_batch
from lib.plan_item_factory import build_add_plan_item, build_record_plan_item, iter_batch_entries
from lib.validators import parse_positions

_WRITE_TOOLS = {"add_entry", "record_thaw", "batch_thaw"}


class AgentToolRunner:
    """Executes named tools with normalized input payloads."""

    def __init__(self, yaml_path, actor_id="react-agent", session_id=None, plan_sink=None):
        self._yaml_path = yaml_path
        self._actor_id = actor_id
        self._session_id = session_id
        self._plan_sink = plan_sink

    def _actor_context(self, trace_id=None):
        return build_actor_context(
            actor_type="agent",
            channel="agent",
            actor_id=self._actor_id,
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
            "record_thaw",
            "batch_thaw",
            "rollback",
        ]

    def tool_specs(self):
        """Compact tool schemas for LLM prompt grounding."""
        return {
            "query_inventory": {
                "required": [],
                "optional": ["cell", "short", "plasmid", "plasmid_id", "box", "position"],
                "aliases": {
                    "cell": ["cell_line", "parent_cell_line"],
                    "short": ["short_name"],
                    "plasmid": ["plasmid_name"],
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
            "add_entry": {
                "required": ["parent_cell_line", "short_name", "box", "positions", "frozen_at"],
                "optional": ["plasmid_name", "plasmid_id", "note", "dry_run"],
                "aliases": {
                    "parent_cell_line": ["cell", "cell_line"],
                    "short_name": ["short", "name"],
                    "positions": ["position", "slot"],
                    "frozen_at": ["date"],
                    "note": ["notes", "memo"],
                },
                "notes": "positions accepts list[int] or comma string like '1,2,3'.",
            },
            "record_thaw": {
                "required": ["record_id", "position", "date"],
                "optional": ["action", "to_position", "to_box", "note", "dry_run"],
                "aliases": {
                    "record_id": ["id"],
                    "position": ["pos", "slot"],
                    "to_position": ["to_pos", "target_position"],
                    "to_box": ["target_box", "new_box", "dest_box"],
                    "note": ["notes", "memo"],
                },
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
                "notes": "entries can be list[[record_id, position], ...] or '182:23,183:41'; for move use '182:23->31,183:41->42'; for cross-box move use '4:5->4:1' (id:from->to:target_box) or set to_box for all entries.",
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
            return "No backups exist yet; provide `backup_path` or create backups before rollback."

        if error_code in {"validation_failed", "integrity_validation_failed", "rollback_backup_invalid"}:
            return "Fix validation errors from response details and retry."

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
        """Quick lookup to get (box, label) for a record ID."""
        try:
            result = tool_get_raw_entries(yaml_path=self._yaml_path, ids=[record_id])
            if result.get("ok"):
                entries = result.get("result", {}).get("entries", [])
                if entries:
                    rec = entries[0]
                    box = int(rec.get("box", 0))
                    label = rec.get("short_name") or rec.get("parent_cell_line") or "-"
                    return box, label
        except Exception:
            pass
        return 0, "-"

    @staticmethod
    def _item_desc(item):
        action = str(item.get("action") or "?")
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
            parent_cell_line = self._first_value(payload, "parent_cell_line", "cell", "cell_line") or ""
            short_name = self._first_value(payload, "short_name", "short", "name") or ""
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

            items.append(
                build_add_plan_item(
                    parent_cell_line=parent_cell_line,
                    short_name=short_name,
                    box=box,
                    positions=positions,
                    frozen_at=self._first_value(payload, "frozen_at", "date"),
                    plasmid_name=self._first_value(payload, "plasmid_name", "plasmid"),
                    plasmid_id=payload.get("plasmid_id"),
                    note=self._first_value(payload, "note", "notes", "memo"),
                    source="ai",
                )
            )

        elif tool_name == "record_thaw":
            try:
                rid = int(self._first_value(payload, "record_id", "id"))
                pos = int(self._first_value(payload, "position", "pos", "slot"))
            except (ValueError, TypeError) as exc:
                return self._with_hint(tool_name, {
                    "ok": False, "error_code": "invalid_tool_input",
                    "message": f"record_id and position are required integers: {exc}",
                })

            action_raw = payload.get("action", "Takeout")
            to_pos_raw = self._first_value(payload, "to_position", "to_pos", "target_position")
            to_pos = None
            if to_pos_raw not in (None, ""):
                to_pos = int(to_pos_raw)

            to_box_raw = self._first_value(payload, "to_box", "target_box", "new_box", "dest_box")
            to_box = int(to_box_raw) if to_box_raw not in (None, "") else None

            box, label = self._lookup_record_info(rid)

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

            for normalized in iter_batch_entries(entries, default_to_box=batch_to_box):
                rid = int(normalized.get("record_id", 0) or 0)
                pos = int(normalized.get("position", 0) or 0)
                to_pos = normalized.get("to_position")
                to_box = normalized.get("to_box")
                box, label = self._lookup_record_info(rid)
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

        staged = []
        for item in validated_items:
            self._plan_sink(item)
            staged.append(item)

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

        # Intercept write operations when plan_sink is set
        if tool_name in _WRITE_TOOLS and self._plan_sink is not None:
            return self._stage_to_plan(tool_name, payload, trace_id)

        if tool_name == "query_inventory":
            return self._safe_call(
                tool_name,
                lambda: tool_query_inventory(
                    yaml_path=self._yaml_path,
                    cell=self._first_value(payload, "cell", "cell_line", "parent_cell_line"),
                    short=self._first_value(payload, "short", "short_name"),
                    plasmid=self._first_value(payload, "plasmid", "plasmid_name"),
                    plasmid_id=self._first_value(payload, "plasmid_id"),
                    box=self._optional_int(payload, "box"),
                    position=self._optional_int(payload, "position"),
                ),
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

        if tool_name == "add_entry":
            def _call_add_entry():
                normalized = dict(payload)
                normalized["parent_cell_line"] = self._first_value(
                    payload, "parent_cell_line", "cell", "cell_line"
                )
                normalized["short_name"] = self._first_value(payload, "short_name", "short", "name")
                normalized["box"] = self._first_value(payload, "box", "box_num")
                normalized["frozen_at"] = self._first_value(payload, "frozen_at", "date")
                normalized["note"] = self._first_value(payload, "note", "notes", "memo")

                positions_raw = payload.get("positions")
                if positions_raw in (None, ""):
                    positions_raw = self._first_value(payload, "position", "slot")
                positions = self._normalize_positions(positions_raw)

                return tool_add_entry(
                    yaml_path=self._yaml_path,
                    parent_cell_line=normalized.get("parent_cell_line"),
                    short_name=normalized.get("short_name"),
                    box=self._required_int(normalized, "box"),
                    positions=positions,
                    frozen_at=normalized.get("frozen_at"),
                    plasmid_name=self._first_value(payload, "plasmid_name", "plasmid"),
                    plasmid_id=payload.get("plasmid_id"),
                    note=normalized.get("note"),
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
                    position=self._required_int(normalized, "position"),
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

        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {tool_name}",
                "available_tools": self.list_tools(),
            },
        )
