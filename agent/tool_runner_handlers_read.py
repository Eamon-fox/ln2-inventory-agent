"""Read-only dispatch handlers for AgentToolRunner."""

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
from lib import tool_api_write_adapter as _write_adapter


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
            status=payload.get("status") or "active",
            sort_by=payload.get("sort_by"),
            sort_order=payload.get("sort_order"),
        ),
    )


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
