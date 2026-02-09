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

    def run(self, tool_name, tool_input, trace_id=None):
        payload = dict(tool_input or {})

        if tool_name == "query_inventory":
            return tool_query_inventory(yaml_path=self._yaml_path, **payload)

        if tool_name == "list_empty_positions":
            return tool_list_empty_positions(yaml_path=self._yaml_path, box=payload.get("box"))

        if tool_name == "search_records":
            return tool_search_records(
                yaml_path=self._yaml_path,
                query=payload.get("query", ""),
                mode=payload.get("mode", "fuzzy"),
                max_results=payload.get("max_results"),
                case_sensitive=bool(payload.get("case_sensitive", False)),
            )

        if tool_name == "recent_frozen":
            return tool_recent_frozen(
                yaml_path=self._yaml_path,
                days=payload.get("days"),
                count=payload.get("count"),
            )

        if tool_name == "query_thaw_events":
            return tool_query_thaw_events(
                yaml_path=self._yaml_path,
                date=payload.get("date"),
                days=payload.get("days"),
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
                action=payload.get("action"),
                max_records=payload.get("max_records", 0),
            )

        if tool_name == "collect_timeline":
            return tool_collect_timeline(
                yaml_path=self._yaml_path,
                days=payload.get("days", 30),
                all_history=bool(payload.get("all_history", False)),
            )

        if tool_name == "recommend_positions":
            return tool_recommend_positions(
                yaml_path=self._yaml_path,
                count=int(payload.get("count", 2)),
                box_preference=payload.get("box_preference"),
                strategy=payload.get("strategy", "consecutive"),
            )

        if tool_name == "generate_stats":
            return tool_generate_stats(yaml_path=self._yaml_path)

        if tool_name == "get_raw_entries":
            return tool_get_raw_entries(
                yaml_path=self._yaml_path,
                ids=payload.get("ids", []),
            )

        if tool_name == "add_entry":
            try:
                positions = payload.get("positions")
                if isinstance(positions, str):
                    positions = parse_positions(positions)
                return tool_add_entry(
                    yaml_path=self._yaml_path,
                    parent_cell_line=payload.get("parent_cell_line"),
                    short_name=payload.get("short_name"),
                    box=self._required_int(payload, "box"),
                    positions=positions,
                    frozen_at=payload.get("frozen_at"),
                    plasmid_name=payload.get("plasmid_name"),
                    plasmid_id=payload.get("plasmid_id"),
                    note=payload.get("note"),
                    dry_run=bool(payload.get("dry_run", False)),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                }

        if tool_name == "record_thaw":
            try:
                return tool_record_thaw(
                    yaml_path=self._yaml_path,
                    record_id=self._required_int(payload, "record_id"),
                    position=self._required_int(payload, "position"),
                    date_str=payload.get("date"),
                    action=payload.get("action", "取出"),
                    note=payload.get("note"),
                    dry_run=bool(payload.get("dry_run", False)),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
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
                    dry_run=bool(payload.get("dry_run", False)),
                    actor_context=self._actor_context(trace_id=trace_id),
                    source="agent.react",
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": str(exc),
                }

        if tool_name == "rollback":
            return tool_rollback(
                yaml_path=self._yaml_path,
                backup_path=payload.get("backup_path"),
                no_html=bool(payload.get("no_html", True)),
                no_server=bool(payload.get("no_server", True)),
                actor_context=self._actor_context(trace_id=trace_id),
                source="agent.react",
            )

        return {
            "ok": False,
            "error_code": "unknown_tool",
            "message": f"Unknown tool: {tool_name}",
            "available_tools": self.list_tools(),
        }
