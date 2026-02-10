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
from lib.validators import parse_positions


class AgentToolRunner:
    """Executes named tools with normalized input payloads."""

    def __init__(self, yaml_path, actor_id="react-agent", session_id=None):
        self._yaml_path = yaml_path
        self._actor_id = actor_id
        self._session_id = session_id

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
                "optional": ["action", "note", "dry_run"],
                "aliases": {
                    "record_id": ["id"],
                    "position": ["pos", "slot"],
                    "note": ["notes", "memo"],
                },
            },
            "batch_thaw": {
                "required": ["entries"],
                "optional": ["date", "action", "note", "dry_run"],
                "notes": "entries can be list[[record_id, position], ...] or '182:23,183:41'.",
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

        if error_code in {"invalid_date"}:
            return "Use date format `YYYY-MM-DD` (for example: 2026-02-10)."

        if error_code in {"invalid_box", "invalid_position"}:
            return "Provide integer values in the configured inventory range."

        if error_code == "invalid_action":
            return "Use a supported action value such as 取出 / 复苏 / 扔掉."

        if error_code in {"empty_positions", "empty_entries"}:
            return "Provide at least one target position or entry before retrying."

        if error_code == "no_backups":
            return "No backups exist yet; provide `backup_path` or create backups before rollback."

        if error_code in {"validation_failed", "integrity_validation_failed", "rollback_backup_invalid"}:
            return "Fix validation errors from response details and retry."

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

    def run(self, tool_name, tool_input, trace_id=None):
        payload = dict(tool_input or {})

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
                normalized["note"] = self._first_value(payload, "note", "notes", "memo")
                return tool_record_thaw(
                    yaml_path=self._yaml_path,
                    record_id=self._required_int(normalized, "record_id"),
                    position=self._required_int(normalized, "position"),
                    date_str=normalized.get("date"),
                    action=payload.get("action", "取出"),
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
