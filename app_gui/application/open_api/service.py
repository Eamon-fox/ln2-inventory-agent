"""Loopback-only local HTTP API for inventory reads and GUI handoff."""

from __future__ import annotations

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from app_gui.plan_executor import preflight_plan
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.inventory_paths import list_managed_datasets
from lib.plan_gate import validate_stage_request
from lib.plan_item_factory import normalize_plan_action
from lib.tool_api import (
    coerce_position_value,
    tool_filter_records,
    tool_generate_stats,
    tool_search_records,
)
from lib.validate_service import validate_yaml_file
from lib.yaml_ops import load_yaml

from .contracts import (
    LOCAL_OPEN_API_DEFAULT_PORT,
    LOCAL_OPEN_API_ROUTE_ALLOWLIST,
    LOCAL_OPEN_API_ROUTE_SPECS,
    LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS,
    LOCAL_OPEN_API_VALIDATION_MODES,
    iter_local_open_api_route_descriptions,
)


def _response_envelope(*, ok: bool, message: str = "", result=None, error_code=None, **extra):
    payload = {
        "ok": bool(ok),
        "message": str(message or ""),
        "result": result,
        "error_code": error_code,
    }
    for key, value in dict(extra or {}).items():
        if value is not None:
            payload[key] = value
    return payload


class LocalOpenApiRequestError(ValueError):
    """Structured request error for API responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_code: str = "invalid_request",
        field: str | None = None,
        expected_type: str | None = None,
        accepted_values=None,
        example_request=None,
    ):
        super().__init__(str(message or "Invalid request"))
        self.status_code = int(status_code or 400)
        self.error_code = str(error_code or "invalid_request")
        self.field = str(field or "").strip() or None
        self.expected_type = str(expected_type or "").strip() or None
        self.accepted_values = accepted_values
        self.example_request = example_request

    def to_response(self):
        return self.status_code, _response_envelope(
            ok=False,
            error_code=self.error_code,
            message=str(self),
            field=self.field,
            expected_type=self.expected_type,
            accepted_values=self.accepted_values,
            example_request=self.example_request,
        )


def _error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    field: str | None = None,
    expected_type: str | None = None,
    accepted_values=None,
    example_request=None,
    result=None,
    **extra,
):
    return int(status_code), _response_envelope(
        ok=False,
        error_code=error_code,
        message=message,
        result=result,
        field=field,
        expected_type=expected_type,
        accepted_values=accepted_values,
        example_request=example_request,
        **extra,
    )


def _first(values, default=None):
    if isinstance(values, list) and values:
        return values[0]
    return default


def _coerce_int(value, *, field_name, default=None, minimum=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except Exception as exc:
        raise LocalOpenApiRequestError(
            f"{field_name} must be an integer",
            field=field_name,
            expected_type="integer",
        ) from exc
    if minimum is not None and parsed < int(minimum):
        raise LocalOpenApiRequestError(
            f"{field_name} must be >= {int(minimum)}",
            field=field_name,
            expected_type="integer",
        )
    return parsed


def _coerce_bool(value, *, default=False):
    if value in (None, ""):
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise LocalOpenApiRequestError(
        f"Invalid boolean value: {value}",
        expected_type="boolean",
        accepted_values=["1", "0", "true", "false", "yes", "no", "on", "off"],
    )


def _coerce_json_object(value, *, field_name):
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(str(value))
    except Exception as exc:
        raise LocalOpenApiRequestError(
            f"{field_name} must be valid JSON",
            field=field_name,
            expected_type="json-object",
        ) from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise LocalOpenApiRequestError(
            f"{field_name} must be a JSON object",
            field=field_name,
            expected_type="json-object",
        )
    return parsed


def _normalize_route_path(path: str) -> str:
    text = str(path or "").strip() or "/"
    if text != "/" and text.endswith("/"):
        return text.rstrip("/")
    return text


def _build_stats_summary(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result or {})
    if "box" in payload:
        return {
            "summary_only": True,
            "box": payload.get("box"),
            "box_total_slots": payload.get("box_total_slots"),
            "box_occupied": payload.get("box_occupied"),
            "box_empty": payload.get("box_empty"),
            "box_occupancy_rate": payload.get("box_occupancy_rate"),
            "box_record_count": payload.get("box_record_count"),
            "record_count": payload.get("record_count"),
            "include_inactive": payload.get("include_inactive"),
        }

    boxes = payload.get("boxes")
    box_count = len(boxes) if isinstance(boxes, dict) else None
    return {
        "summary_only": True,
        "total_slots": payload.get("total_slots"),
        "slots_per_box": payload.get("slots_per_box"),
        "total_occupied": payload.get("total_occupied"),
        "total_empty": payload.get("total_empty"),
        "total_capacity": payload.get("total_capacity"),
        "occupancy_rate": payload.get("occupancy_rate"),
        "record_count": payload.get("record_count"),
        "include_inactive": payload.get("include_inactive"),
        "box_count": box_count,
    }


class LocalOpenApiController:
    """Business/controller layer behind the loopback HTTP surface."""

    def __init__(
        self,
        *,
        yaml_path_getter: Callable[[], str],
        bridge,
        plan_store,
        gui_dispatcher=None,
        list_datasets_fn: Callable[[], list] | None = None,
        switch_dataset_fn: Callable[[str, str], str] | None = None,
        focus_window_fn: Callable[[], object] | None = None,
        prefill_takeout_fn: Callable[[dict], object] | None = None,
        prefill_add_fn: Callable[[dict], object] | None = None,
        prefill_ai_prompt_fn: Callable[[str, bool], object] | None = None,
        preflight_fn: Callable = preflight_plan,
    ):
        self._yaml_path_getter = yaml_path_getter
        self._bridge = bridge
        self._plan_store = plan_store
        self._gui_dispatcher = gui_dispatcher
        self._list_datasets_fn = list_datasets_fn or list_managed_datasets
        self._switch_dataset_fn = switch_dataset_fn
        self._focus_window_fn = focus_window_fn
        self._prefill_takeout_fn = prefill_takeout_fn
        self._prefill_add_fn = prefill_add_fn
        self._prefill_ai_prompt_fn = prefill_ai_prompt_fn
        self._preflight_fn = preflight_fn

    def handle_request(self, method: str, path: str, query_params: dict[str, list[str]], payload=None):
        normalized_method = str(method or "").upper().strip()
        normalized_path = _normalize_route_path(path)
        route_key = (normalized_method, normalized_path)
        if route_key not in LOCAL_OPEN_API_ROUTE_ALLOWLIST:
            return 404, _response_envelope(
                ok=False,
                error_code="route_not_found",
                message="Route not found",
            )
        route_spec = dict(LOCAL_OPEN_API_ROUTE_SPECS.get(route_key) or {})
        handler_name = str(route_spec.get("handler") or "").strip()
        handler = getattr(self, handler_name, None)
        if not callable(handler):
            raise RuntimeError(f"Local Open API handler is unavailable: {handler_name}")

        request_arg = route_spec.get("request_arg")
        if request_arg == "query_params":
            response = handler(query_params)
        elif request_arg == "payload":
            response = handler(payload)
        else:
            response = handler()

        if isinstance(response, tuple) and len(response) == 2:
            return response
        return int(route_spec.get("status_code", 200) or 200), response

    def _current_yaml_path(self, *, must_exist=True):
        raw = str(self._yaml_path_getter() or "").strip()
        return assert_allowed_inventory_yaml_path(raw, must_exist=must_exist)

    def _current_layout(self):
        yaml_path = self._current_yaml_path(must_exist=True)
        data = load_yaml(yaml_path)
        meta = (data or {}).get("meta") if isinstance(data, dict) else {}
        layout = (meta or {}).get("box_layout") if isinstance(meta, dict) else {}
        return yaml_path, layout if isinstance(layout, dict) else {}

    def _call_gui(self, fn: Callable[[], object]):
        dispatcher = self._gui_dispatcher
        if dispatcher is None or not hasattr(dispatcher, "call"):
            return fn()
        return dispatcher.call(fn)

    def _focus_window(self):
        focus_fn = self._focus_window_fn
        if not callable(focus_fn):
            raise RuntimeError("GUI focus handler is unavailable")
        return self._call_gui(focus_fn)

    def _handle_health(self):
        current_yaml = str(self._yaml_path_getter() or "").strip()
        return _response_envelope(
            ok=True,
            message="ok",
            result={
                "service": "local_open_api",
                "dataset_path": current_yaml,
                "dataset_exists": bool(current_yaml and os.path.isfile(current_yaml)),
            },
        )

    def _handle_capabilities(self):
        return _response_envelope(
            ok=True,
            message="Local API capabilities",
            result={
                "service": "local_open_api",
                "boundary": {
                    "bind_host": "127.0.0.1",
                    "requires_running_gui_instance": True,
                    "dataset_source": "current_gui_session",
                    "explicit_route_allowlist": True,
                    "inventory_write_enabled": False,
                    "notes": [
                        "This API is loopback-only.",
                        "It does not execute inventory write tools.",
                        "GUI handoff routes prepare or stage work for human review.",
                    ],
                },
                "validation_modes": list(LOCAL_OPEN_API_VALIDATION_MODES),
                "stage_allowed_actions": sorted(LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS),
                "routes": list(iter_local_open_api_route_descriptions(sort_routes=True)),
            },
        )

    def _handle_session(self):
        current_yaml = str(self._yaml_path_getter() or "").strip()
        dataset_name = os.path.basename(os.path.dirname(current_yaml)) or os.path.basename(current_yaml) or ""
        return _response_envelope(
            ok=True,
            message="Current GUI session",
            result={
                "dataset_path": current_yaml,
                "dataset_name": dataset_name,
                "dataset_exists": bool(current_yaml and os.path.isfile(current_yaml)),
            },
        )

    def _managed_datasets(self):
        rows = self._list_datasets_fn() if callable(self._list_datasets_fn) else []
        current_yaml = os.path.abspath(str(self._yaml_path_getter() or "").strip()) if str(self._yaml_path_getter() or "").strip() else ""
        items = []
        for row in list(rows or []):
            if not isinstance(row, dict):
                continue
            yaml_path = str(row.get("yaml_path") or "").strip()
            if not yaml_path:
                continue
            normalized_yaml = os.path.abspath(yaml_path)
            dataset_name = str(row.get("name") or "").strip() or os.path.basename(os.path.dirname(normalized_yaml)) or normalized_yaml
            items.append(
                {
                    "dataset_name": dataset_name,
                    "dataset_path": normalized_yaml,
                    "is_current": bool(current_yaml and normalized_yaml == current_yaml),
                }
            )
        return items

    def _handle_datasets(self):
        items = self._managed_datasets()
        return _response_envelope(
            ok=True,
            message="Managed datasets",
            result={
                "datasets": items,
                "count": len(items),
            },
        )

    def _handle_inventory_search(self, query_params):
        yaml_path = self._current_yaml_path(must_exist=True)
        position = _first(query_params.get("position"))
        record_id = _coerce_int(_first(query_params.get("record_id")), field_name="record_id", minimum=1)
        box = _coerce_int(_first(query_params.get("box")), field_name="box", minimum=1)
        max_results = _coerce_int(_first(query_params.get("max_results")), field_name="max_results", minimum=1)
        response = tool_search_records(
            yaml_path=yaml_path,
            query=_first(query_params.get("query")),
            mode=_first(query_params.get("mode"), "fuzzy"),
            max_results=max_results,
            case_sensitive=_coerce_bool(_first(query_params.get("case_sensitive")), default=False),
            box=box,
            position=position,
            record_id=record_id,
            status=_first(query_params.get("status"), "all"),
            sort_by=_first(query_params.get("sort_by")),
            sort_order=_first(query_params.get("sort_order"), "desc"),
        )
        return response

    def _handle_inventory_filter(self, query_params):
        yaml_path = self._current_yaml_path(must_exist=True)
        response = tool_filter_records(
            yaml_path=yaml_path,
            keyword=_first(query_params.get("keyword")),
            box=_coerce_int(_first(query_params.get("box")), field_name="box", minimum=1),
            color_value=_first(query_params.get("color_value")),
            include_inactive=_coerce_bool(_first(query_params.get("include_inactive")), default=False),
            column_filters=_coerce_json_object(_first(query_params.get("column_filters")), field_name="column_filters"),
            sort_by=_first(query_params.get("sort_by"), "location"),
            sort_order=_first(query_params.get("sort_order"), "asc"),
            limit=_coerce_int(_first(query_params.get("limit")), field_name="limit", minimum=1),
            offset=_coerce_int(_first(query_params.get("offset")), field_name="offset", minimum=0, default=0),
        )
        return response

    def _handle_inventory_stats(self, query_params):
        yaml_path = self._current_yaml_path(must_exist=True)
        summary_only = _coerce_bool(_first(query_params.get("summary_only")), default=False)
        response = tool_generate_stats(
            yaml_path=yaml_path,
            box=_coerce_int(_first(query_params.get("box")), field_name="box", minimum=1),
            include_inactive=_coerce_bool(_first(query_params.get("include_inactive")), default=False),
        )
        if summary_only and isinstance(response, dict) and bool(response.get("ok")):
            result = response.get("result")
            if isinstance(result, dict):
                response = dict(response)
                response["result"] = _build_stats_summary(result)
        return response

    def _handle_inventory_validate(self, query_params):
        yaml_path = self._current_yaml_path(must_exist=True)
        requested_mode = _first(query_params.get("mode"))
        if requested_mode not in (None, ""):
            normalized_mode = str(requested_mode).strip().lower()
            if normalized_mode not in LOCAL_OPEN_API_VALIDATION_MODES:
                raise LocalOpenApiRequestError(
                    f"Invalid validation mode: {requested_mode}",
                    field="mode",
                    expected_type="string",
                    accepted_values=list(LOCAL_OPEN_API_VALIDATION_MODES),
                    example_request={"mode": "current_inventory", "fail_on_warnings": False},
                )
        return validate_yaml_file(
            yaml_path,
            mode=requested_mode,
            fail_on_warnings=_coerce_bool(_first(query_params.get("fail_on_warnings")), default=False),
        )

    def _resolve_switch_target_yaml(self, body):
        dataset_name = str((body or {}).get("dataset_name") or "").strip()
        yaml_path = str((body or {}).get("yaml_path") or "").strip()
        if yaml_path:
            raise LocalOpenApiRequestError(
                "yaml_path is not supported; use dataset_name.",
                field="yaml_path",
                expected_type="managed dataset name",
                example_request={"dataset_name": "inventory-fan", "focus": True},
            )
        if not dataset_name:
            raise LocalOpenApiRequestError(
                "dataset_name is required.",
                field="dataset_name",
                expected_type="string",
                example_request={"dataset_name": "inventory-fan", "focus": True},
            )

        for item in self._managed_datasets():
            if str(item.get("dataset_name") or "") == dataset_name:
                return str(item.get("dataset_path") or "")
        return ""

    def _handle_session_switch_dataset(self, payload):
        body = dict(payload or {}) if isinstance(payload, dict) else {}
        current_yaml = str(self._yaml_path_getter() or "").strip()
        previous_dataset_name = os.path.basename(os.path.dirname(current_yaml)) or os.path.basename(current_yaml) or ""
        target_yaml = self._resolve_switch_target_yaml(body)
        if not target_yaml:
            return 404, _response_envelope(
                ok=False,
                error_code="dataset_not_found",
                message=f"Managed dataset not found: {body.get('dataset_name')}",
            )

        handler = self._switch_dataset_fn
        if not callable(handler):
            return 500, _response_envelope(
                ok=False,
                error_code="dataset_switch_unavailable",
                message="Dataset switch handler is unavailable.",
            )

        def _apply():
            return handler(target_yaml, "api_switch")

        switched_yaml = str(self._call_gui(_apply) or "").strip() or target_yaml
        focus = _coerce_bool(body.get("focus"), default=False)
        if focus:
            focus_fn = self._focus_window_fn
            if callable(focus_fn):
                self._call_gui(focus_fn)

        dataset_name = os.path.basename(os.path.dirname(switched_yaml)) or os.path.basename(switched_yaml) or ""
        return 200, _response_envelope(
            ok=True,
            message="Switched current dataset",
            effect="managed_dataset_session_switch",
            executed=False,
            staged=False,
            inventory_written=False,
            gui_changed=bool(switched_yaml != current_yaml or focus),
            result={
                "dataset_name": dataset_name,
                "dataset_path": switched_yaml,
                "previous_dataset_name": previous_dataset_name,
                "previous_dataset_path": current_yaml,
                "focused": focus,
            },
        )

    def _handle_focus(self):
        self._focus_window()
        return _response_envelope(
            ok=True,
            message="Focused GUI window",
            result={"focused": True},
        )

    def _normalize_prefill_position(self, raw_value, *, field_name):
        yaml_path, layout = self._current_layout()
        del yaml_path
        return int(
            coerce_position_value(
                raw_value,
                layout=layout,
                field_name=field_name,
            )
        )

    def _handle_prefill_takeout(self, payload):
        body = dict(payload or {}) if isinstance(payload, dict) else {}
        prefill = {}
        record_id = _coerce_int(body.get("record_id"), field_name="record_id", minimum=1)
        box = _coerce_int(body.get("box"), field_name="box", minimum=1)
        raw_position = body.get("position")
        if record_id is not None:
            prefill["record_id"] = record_id
        if box is not None:
            prefill["box"] = box
        if raw_position not in (None, ""):
            prefill["position"] = self._normalize_prefill_position(raw_position, field_name="position")
        if "record_id" not in prefill and not {"box", "position"} <= set(prefill):
            return _error_response(
                status_code=400,
                error_code="invalid_request",
                message="Provide record_id or both box and position.",
                field="record_id",
                expected_type="integer or {box, position}",
                example_request={"record_id": 1, "focus": True},
            )

        focus = _coerce_bool(body.get("focus"), default=True)
        handler = self._prefill_takeout_fn
        if not callable(handler):
            return 500, _response_envelope(
                ok=False,
                error_code="gui_handoff_unavailable",
                message="Takeout prefill handler is unavailable.",
            )

        def _apply():
            handler(prefill)
            if focus:
                focus_fn = self._focus_window_fn
                if callable(focus_fn):
                    focus_fn()
            return True

        self._call_gui(_apply)
        return 200, _response_envelope(
            ok=True,
            message="Prepared takeout context in GUI",
            effect="gui_handoff",
            executed=False,
            staged=False,
            inventory_written=False,
            gui_changed=True,
            result={"prefill": prefill, "focused": focus},
        )

    def _handle_prefill_add(self, payload):
        body = dict(payload or {}) if isinstance(payload, dict) else {}
        box = _coerce_int(body.get("box"), field_name="box", minimum=1)
        if box is None:
            return _error_response(
                status_code=400,
                error_code="invalid_request",
                message="box is required.",
                field="box",
                expected_type="integer",
                example_request={"box": 1, "position": "A1", "focus": True},
            )
        raw_positions = body.get("positions")
        normalized_positions = []
        if isinstance(raw_positions, list):
            for idx, raw_position in enumerate(raw_positions):
                normalized_positions.append(
                    self._normalize_prefill_position(raw_position, field_name=f"positions[{idx}]")
                )
        elif body.get("position") not in (None, ""):
            normalized_positions.append(
                self._normalize_prefill_position(body.get("position"), field_name="position")
            )
        if not normalized_positions:
            return _error_response(
                status_code=400,
                error_code="invalid_request",
                message="Provide position or positions.",
                field="position",
                expected_type="string-or-integer or array",
                example_request={"box": 1, "position": "A1", "focus": True},
            )
        prefill = {
            "box": box,
            "position": normalized_positions[0],
            "positions": normalized_positions,
        }
        focus = _coerce_bool(body.get("focus"), default=True)
        handler = self._prefill_add_fn
        if not callable(handler):
            return 500, _response_envelope(
                ok=False,
                error_code="gui_handoff_unavailable",
                message="Add prefill handler is unavailable.",
            )

        def _apply():
            handler(prefill)
            if focus:
                focus_fn = self._focus_window_fn
                if callable(focus_fn):
                    focus_fn()
            return True

        self._call_gui(_apply)
        return 200, _response_envelope(
            ok=True,
            message="Prepared add-entry context in GUI",
            effect="gui_handoff",
            executed=False,
            staged=False,
            inventory_written=False,
            gui_changed=True,
            result={"prefill": prefill, "focused": focus},
        )

    def _handle_prefill_ai_prompt(self, payload):
        body = dict(payload or {}) if isinstance(payload, dict) else {}
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return _error_response(
                status_code=400,
                error_code="invalid_request",
                message="prompt is required.",
                field="prompt",
                expected_type="string",
                example_request={"prompt": "show the K562 records", "focus": True},
            )
        focus = _coerce_bool(body.get("focus"), default=True)
        handler = self._prefill_ai_prompt_fn
        if not callable(handler):
            return 500, _response_envelope(
                ok=False,
                error_code="gui_handoff_unavailable",
                message="AI prompt prefill handler is unavailable.",
            )

        def _apply():
            handler(prompt, focus)
            return True

        self._call_gui(_apply)
        return 200, _response_envelope(
            ok=True,
            message="Prepared AI prompt in GUI",
            effect="gui_handoff",
            executed=False,
            staged=False,
            inventory_written=False,
            gui_changed=True,
            result={"focused": focus, "prompt_length": len(prompt)},
        )

    def _handle_get_stage_plan(self):
        if self._plan_store is None:
            return 500, _response_envelope(
                ok=False,
                error_code="plan_store_unavailable",
                message="Plan store is unavailable.",
            )
        items = self._plan_store.list_items()
        return 200, _response_envelope(
            ok=True,
            message="Current staged GUI plan",
            effect="gui_stage_state",
            executed=False,
            staged=False,
            inventory_written=False,
            gui_changed=False,
            result={
                "count": len(items),
                "items": items,
            },
        )

    def _handle_stage_plan(self, payload):
        if self._plan_store is None:
            return 500, _response_envelope(
                ok=False,
                error_code="plan_store_unavailable",
                message="Plan store is unavailable.",
            )
        body = dict(payload or {}) if isinstance(payload, dict) else {}
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return _error_response(
                status_code=400,
                error_code="invalid_request",
                message="items must be a non-empty list.",
                field="items",
                expected_type="non-empty array",
                example_request={
                    "items": [
                        {"action": "add", "box": 1, "position": 2, "record_id": None, "source": "api", "payload": {"box": 1, "positions": [2], "stored_at": "2024-01-02", "fields": {}}},
                    ]
                },
            )

        normalized_items = []
        for idx, raw_item in enumerate(items):
            if not isinstance(raw_item, dict):
                return _error_response(
                    status_code=400,
                    error_code="invalid_request",
                    message=f"items[{idx}] must be an object.",
                    field=f"items[{idx}]",
                    expected_type="object",
                )
            item = copy.deepcopy(raw_item)
            action = normalize_plan_action(item.get("action"))
            if action not in LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS:
                return _error_response(
                    status_code=409,
                    error_code="plan_action_not_allowed",
                    message=f"Action is not allowed for local API staging: {item.get('action')}",
                    field=f"items[{idx}].action",
                    expected_type="string",
                    accepted_values=sorted(LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS),
                    example_request={
                        "items": [
                            {"action": "takeout", "record_id": 1, "box": 1, "position": 1, "source": "api", "payload": {"record_id": 1, "position": 1, "date_str": "2024-03-22", "action": "takeout"}}
                        ]
                    },
                    blocked_items=[
                        {
                            "action": item.get("action"),
                            "error_code": "plan_action_not_allowed",
                            "message": "Only add/edit/takeout/move can be staged through local API.",
                        },
                    ],
                )
            item["action"] = action
            item.setdefault("source", "api")
            normalized_items.append(item)

        yaml_path = self._current_yaml_path(must_exist=True)
        gate = validate_stage_request(
            existing_items=self._plan_store.list_items(),
            incoming_items=normalized_items,
            yaml_path=yaml_path,
            bridge=self._bridge,
            run_preflight=True,
            preflight_fn=self._preflight_fn,
        )
        if gate.get("blocked"):
            return 409, _response_envelope(
                ok=False,
                error_code="plan_stage_blocked",
                message="Plan items failed validation.",
                result={
                    "stats": gate.get("stats") if isinstance(gate.get("stats"), dict) else {},
                },
                blocked_items=gate.get("blocked_items") if isinstance(gate.get("blocked_items"), list) else [],
                errors=gate.get("errors") if isinstance(gate.get("errors"), list) else [],
            )

        accepted = list(gate.get("accepted_items") or [])
        noop_items = list(gate.get("noop_items") or [])
        if accepted:
            self._plan_store.add(accepted)

        focus = _coerce_bool(body.get("focus"), default=True)
        if focus and (accepted or noop_items):
            focus_fn = self._focus_window_fn
            if callable(focus_fn):
                self._call_gui(focus_fn)

        return 200, _response_envelope(
            ok=True,
            message="Plan items staged in GUI",
            effect="gui_stage_only",
            executed=False,
            staged=True,
            inventory_written=False,
            gui_changed=bool(accepted or noop_items or focus),
            result={
                "staged_count": len(accepted),
                "already_staged_count": len(noop_items),
                "total_count": self._plan_store.count(),
                "items": accepted,
                "noop_items": noop_items,
                "focused": focus,
                "stats": gate.get("stats") if isinstance(gate.get("stats"), dict) else {},
            },
        )


class _LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class LocalOpenApiService:
    """Lifecycle wrapper around the loopback-only HTTP server."""

    def __init__(self, controller: LocalOpenApiController, *, host="127.0.0.1", port=LOCAL_OPEN_API_DEFAULT_PORT):
        self._controller = controller
        self._host = str(host or "127.0.0.1")
        self._requested_port = int(port or LOCAL_OPEN_API_DEFAULT_PORT)
        self._bound_port = 0
        self._server = None
        self._thread = None
        self._lock = threading.Lock()

    @property
    def requested_port(self) -> int:
        return int(self._requested_port or 0)

    @property
    def bound_port(self) -> int:
        return int(self._bound_port or 0)

    def is_running(self) -> bool:
        with self._lock:
            thread = self._thread
            server = self._server
        return bool(server is not None and thread is not None and thread.is_alive())

    def _build_handler(self):
        controller = self._controller

        class _Handler(BaseHTTPRequestHandler):
            server_version = "SnowFoxLocalAPI/1.0"

            def log_message(self, format, *args):  # noqa: A003 - stdlib signature
                return

            def do_GET(self):
                self._handle_request("GET")

            def do_POST(self):
                self._handle_request("POST")

            def _read_payload(self):
                content_length = _coerce_int(
                    self.headers.get("Content-Length"),
                    field_name="Content-Length",
                    default=0,
                    minimum=0,
                )
                if not content_length:
                    return None
                raw = self.rfile.read(content_length)
                if not raw:
                    return None
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    raise LocalOpenApiRequestError(
                        "Request body must be valid JSON.",
                        expected_type="json-object",
                    ) from exc
                if payload is None:
                    return None
                if not isinstance(payload, dict):
                    raise LocalOpenApiRequestError(
                        "Request body must be a JSON object.",
                        expected_type="json-object",
                    )
                return payload

            def _send_json(self, status_code, payload_dict):
                body = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(int(status_code))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle_request(self, method):
                try:
                    parsed = urlsplit(self.path)
                    payload = self._read_payload() if method == "POST" else None
                    status_code, response_payload = controller.handle_request(
                        method,
                        parsed.path,
                        parse_qs(parsed.query, keep_blank_values=True),
                        payload=payload,
                    )
                except LocalOpenApiRequestError as exc:
                    status_code, response_payload = exc.to_response()
                except ValueError as exc:
                    status_code, response_payload = LocalOpenApiRequestError(str(exc)).to_response()
                except Exception as exc:  # pragma: no cover - defensive server guard
                    status_code = 500
                    response_payload = _response_envelope(
                        ok=False,
                        error_code="internal_error",
                        message=str(exc),
                    )
                self._send_json(status_code, response_payload)

        return _Handler

    def start(self, *, port=None):
        desired_port = int(self._requested_port if port is None else port)
        if self.is_running() and desired_port == self.bound_port:
            return {
                "ok": True,
                "running": True,
                "changed": False,
                "port": self.bound_port,
            }
        if self.is_running():
            self.stop()

        server = _LoopbackThreadingHTTPServer((self._host, desired_port), self._build_handler())
        thread = threading.Thread(target=server.serve_forever, name="snowfox-local-open-api", daemon=True)
        with self._lock:
            self._server = server
            self._thread = thread
            self._requested_port = desired_port
            self._bound_port = int(server.server_address[1])
        thread.start()
        return {
            "ok": True,
            "running": True,
            "changed": True,
            "port": self.bound_port,
        }

    def stop(self):
        with self._lock:
            server = self._server
            thread = self._thread
            was_running = bool(server is not None and thread is not None)
            self._server = None
            self._thread = None
            self._bound_port = 0
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        return {
            "ok": True,
            "running": False,
            "changed": was_running,
            "port": 0,
        }

    def configure(self, *, enabled, port):
        desired_port = int(port or LOCAL_OPEN_API_DEFAULT_PORT)
        if not enabled:
            stopped = self.stop()
            stopped["port"] = desired_port
            return stopped
        try:
            return self.start(port=desired_port)
        except Exception as exc:
            return {
                "ok": False,
                "running": False,
                "changed": False,
                "port": desired_port,
                "message": str(exc),
                "error_code": "local_open_api_start_failed",
            }
