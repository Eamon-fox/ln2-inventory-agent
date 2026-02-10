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
                "optional": ["backup_path", "no_html", "no_server"],
            },
        }

    def run(self, tool_name, tool_input, trace_id=None):
        payload = dict(tool_input or {})

        if tool_name == "query_inventory":
            try:
                return tool_query_inventory(
                    yaml_path=self._yaml_path,
                    cell=self._first_value(payload, "cell", "cell_line", "parent_cell_line"),
                    short=self._first_value(payload, "short", "short_name"),
                    plasmid=self._first_value(payload, "plasmid", "plasmid_name"),
                    plasmid_id=self._first_value(payload, "plasmid_id"),
                    box=self._optional_int(payload, "box"),
                    position=self._optional_int(payload, "position"),
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                }

        if tool_name == "list_empty_positions":
            try:
                return tool_list_empty_positions(
                    yaml_path=self._yaml_path,
                    box=self._optional_int(payload, "box"),
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                }

        if tool_name == "search_records":
            return tool_search_records(
                yaml_path=self._yaml_path,
                query=payload.get("query", ""),
                mode=payload.get("mode", "fuzzy"),
                max_results=self._optional_int(payload, "max_results"),
                case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
            )

        if tool_name == "recent_frozen":
            return tool_recent_frozen(
                yaml_path=self._yaml_path,
                days=self._optional_int(payload, "days"),
                count=self._optional_int(payload, "count"),
            )

        if tool_name == "query_thaw_events":
            return tool_query_thaw_events(
                yaml_path=self._yaml_path,
                date=payload.get("date"),
                days=self._optional_int(payload, "days"),
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
                action=payload.get("action"),
                max_records=self._optional_int(payload, "max_records", default=0),
            )

        if tool_name == "collect_timeline":
            return tool_collect_timeline(
                yaml_path=self._yaml_path,
                days=self._optional_int(payload, "days", default=30),
                all_history=self._as_bool(payload.get("all_history", False), default=False),
            )

        if tool_name == "recommend_positions":
            return tool_recommend_positions(
                yaml_path=self._yaml_path,
                count=self._optional_int(payload, "count", default=2),
                box_preference=self._optional_int(payload, "box_preference"),
                strategy=payload.get("strategy", "consecutive"),
            )

        if tool_name == "generate_stats":
            return tool_generate_stats(yaml_path=self._yaml_path)

        if tool_name == "get_raw_entries":
            ids = payload.get("ids", [])
            if isinstance(ids, str):
                ids = [part.strip() for part in ids.split(",") if part.strip()]
            try:
                ids = [int(item) for item in ids]
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": f"Invalid ids field: {exc}",
                }
            return tool_get_raw_entries(
                yaml_path=self._yaml_path,
                ids=ids,
            )

        if tool_name == "add_entry":
            try:
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
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                    "expected": self.tool_specs().get("add_entry"),
                }

        if tool_name == "record_thaw":
            try:
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
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                    "expected": self.tool_specs().get("record_thaw"),
                }

        if tool_name == "batch_thaw":
            try:
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
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                    "expected": self.tool_specs().get("batch_thaw"),
                }

        if tool_name == "rollback":
            return tool_rollback(
                yaml_path=self._yaml_path,
                backup_path=payload.get("backup_path"),
                no_html=self._as_bool(payload.get("no_html", True), default=True),
                no_server=self._as_bool(payload.get("no_server", True), default=True),
                actor_context=self._actor_context(trace_id=trace_id),
                source="agent.react",
            )

        return {
            "ok": False,
            "error_code": "unknown_tool",
            "message": f"Unknown tool: {tool_name}",
            "available_tools": self.list_tools(),
        }
