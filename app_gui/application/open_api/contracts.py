"""Explicit route contracts for the local loopback API."""

from copy import deepcopy

from lib.tool_registry import TOOL_CONTRACTS

LOCAL_OPEN_API_DEFAULT_PORT = 37666
LOCAL_OPEN_API_VALIDATION_MODES = (
    "auto",
    "current_inventory",
    "document",
    "meta_only",
)

LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS = frozenset({"add", "edit", "takeout", "move"})
LOCAL_OPEN_API_SEARCH_MODES = tuple(
    (
        TOOL_CONTRACTS.get("search_records", {})
        .get("parameters", {})
        .get("properties", {})
        .get("mode", {})
        .get("enum")
    )
    or ("fuzzy", "exact")
)

# Self-describing per-action payload schema for ``POST /api/v1/gui/stage-plan``.
# This MIRRORS the runtime validators in ``lib/plan_gate.py``
# (``_validate_item_payload_schema``); keep the two in sync. A unit test asserts
# that every key marked ``required`` here is actually enforced by plan_gate.
LOCAL_OPEN_API_STAGE_PLAN_PAYLOAD_SCHEMA = {
    "notes": [
        "Each item has top-level routing keys (action/record_id/box/position/...) "
        "plus an inner 'payload' object consumed by the GUI plan executor.",
        "Structural keys that also exist at the item level "
        "(record_id, box, position, positions, to_position, to_box) may be omitted "
        "from payload; the API backfills them from the item. Caller-only data "
        "(fields, stored_at, date_str) is never inferred and must be supplied.",
        "Payload shapes intentionally differ per action: 'edit' wraps changes under "
        "'fields'; 'takeout'/'move' use flat keys.",
    ],
    "actions": {
        "add": {
            "item_keys": {"action": "add", "box": "int>0", "position": "int>0"},
            "payload": {
                "box": {"type": "int>0", "required": False, "inherits": "item.box"},
                "positions": {
                    "type": "list[int>0]",
                    "required": True,
                    "default": "[item.position]",
                    "note": "must include item.position",
                },
                "stored_at": {
                    "type": "date-string YYYY-MM-DD",
                    "required": True,
                    "alias": "frozen_at",
                },
                "fields": {"type": "object", "required": True, "note": "may be empty"},
            },
            "example": {
                "action": "add",
                "box": 1,
                "position": 2,
                "source": "api",
                "payload": {
                    "positions": [2],
                    "stored_at": "2024-01-02",
                    "fields": {"short_name": "clone-a"},
                },
            },
        },
        "edit": {
            "item_keys": {"action": "edit", "record_id": "int>0"},
            "payload": {
                "record_id": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.record_id",
                },
                "fields": {
                    "type": "object",
                    "required": True,
                    "note": "non-empty; the fields to change",
                },
            },
            "example": {
                "action": "edit",
                "record_id": 7,
                "source": "api",
                "payload": {"fields": {"note": "edited"}},
            },
        },
        "takeout": {
            "item_keys": {"action": "takeout", "record_id": "int>0", "position": "int>0"},
            "payload": {
                "record_id": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.record_id",
                },
                "position": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.position",
                },
                "date_str": {"type": "date-string YYYY-MM-DD", "required": True},
            },
            "example": {
                "action": "takeout",
                "record_id": 7,
                "box": 1,
                "position": 5,
                "source": "api",
                "payload": {"date_str": "2026-02-10"},
            },
        },
        "move": {
            "item_keys": {
                "action": "move",
                "record_id": "int>0",
                "position": "int>0",
                "to_position": "int>0",
                "to_box": "int>0 (optional)",
            },
            "payload": {
                "record_id": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.record_id",
                },
                "position": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.position",
                },
                "date_str": {"type": "date-string YYYY-MM-DD", "required": True},
                "to_position": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.to_position",
                    "note": "must differ from position when target box is unchanged",
                },
                "to_box": {
                    "type": "int>0",
                    "required": False,
                    "inherits": "item.to_box",
                },
            },
            "example": {
                "action": "move",
                "record_id": 7,
                "box": 1,
                "position": 5,
                "to_position": 10,
                "source": "api",
                "payload": {"date_str": "2026-02-10"},
            },
        },
    },
}

LOCAL_OPEN_API_ROUTE_SPECS = {
    ("GET", "/api/v1/capabilities"): {
        "handler": "_handle_capabilities",
        "request_arg": None,
        "status_code": 200,
        "effect": "capability_read",
        "summary": "Describe the local API allowlist, request/response shapes, current dataset schema, and boundary limits.",
        "params": [],
    },
    ("GET", "/api/v1/health"): {
        "handler": "_handle_health",
        "request_arg": None,
        "status_code": 200,
        "effect": "inventory_read",
        "summary": "Return service health and current GUI dataset path.",
        "params": [],
    },
    ("GET", "/api/v1/datasets"): {
        "handler": "_handle_datasets",
        "request_arg": None,
        "status_code": 200,
        "effect": "managed_dataset_session_switch",
        "summary": "List managed datasets visible to the current GUI session.",
        "params": [],
    },
    ("GET", "/api/v1/session"): {
        "handler": "_handle_session",
        "request_arg": None,
        "status_code": 200,
        "effect": "managed_dataset_session_switch",
        "summary": "Return the current GUI dataset session.",
        "params": [],
    },
    ("GET", "/api/v1/inventory/search"): {
        "handler": "_handle_inventory_search",
        "request_arg": "query_params",
        "status_code": 200,
        "effect": "inventory_read",
        "summary": "Search inventory records in the current GUI dataset.",
        "params": [
            {"name": "query", "in": "query", "type": "string", "required": False},
            {
                "name": "mode",
                "in": "query",
                "type": "string",
                "required": False,
                "accepted_values": list(LOCAL_OPEN_API_SEARCH_MODES),
            },
            {"name": "record_id", "in": "query", "type": "integer", "required": False},
            {"name": "box", "in": "query", "type": "integer", "required": False},
            {"name": "position", "in": "query", "type": "string", "required": False},
            {"name": "max_results", "in": "query", "type": "integer", "required": False},
            {"name": "case_sensitive", "in": "query", "type": "boolean", "required": False},
            {"name": "status", "in": "query", "type": "string", "required": False},
            {"name": "sort_by", "in": "query", "type": "string", "required": False},
            {"name": "sort_order", "in": "query", "type": "string", "required": False, "accepted_values": ["asc", "desc"]},
        ],
    },
    ("GET", "/api/v1/inventory/filter"): {
        "handler": "_handle_inventory_filter",
        "request_arg": "query_params",
        "status_code": 200,
        "effect": "inventory_read",
        "summary": "Filter inventory records in the current GUI dataset.",
        "params": [
            {"name": "keyword", "in": "query", "type": "string", "required": False},
            {"name": "box", "in": "query", "type": "integer", "required": False},
            {"name": "color_value", "in": "query", "type": "string", "required": False},
            {"name": "include_inactive", "in": "query", "type": "boolean", "required": False},
            {"name": "column_filters", "in": "query", "type": "json-object", "required": False},
            {"name": "sort_by", "in": "query", "type": "string", "required": False},
            {"name": "sort_order", "in": "query", "type": "string", "required": False, "accepted_values": ["asc", "desc"]},
            {"name": "limit", "in": "query", "type": "integer", "required": False},
            {"name": "offset", "in": "query", "type": "integer", "required": False},
        ],
    },
    ("GET", "/api/v1/inventory/stats"): {
        "handler": "_handle_inventory_stats",
        "request_arg": "query_params",
        "status_code": 200,
        "effect": "inventory_read",
        "summary": "Return inventory statistics for the current GUI dataset.",
        "params": [
            {"name": "box", "in": "query", "type": "integer", "required": False},
            {"name": "include_inactive", "in": "query", "type": "boolean", "required": False},
            {"name": "summary_only", "in": "query", "type": "boolean", "required": False},
        ],
    },
    ("GET", "/api/v1/inventory/validate"): {
        "handler": "_handle_inventory_validate",
        "request_arg": "query_params",
        "status_code": 200,
        "effect": "inventory_read",
        "summary": "Validate the current GUI dataset without executing inventory writes.",
        "params": [
            {
                "name": "mode",
                "in": "query",
                "type": "string",
                "required": False,
                "accepted_values": list(LOCAL_OPEN_API_VALIDATION_MODES),
            },
            {"name": "fail_on_warnings", "in": "query", "type": "boolean", "required": False},
        ],
    },
    ("POST", "/api/v1/gui/focus"): {
        "handler": "_handle_focus",
        "request_arg": None,
        "status_code": 200,
        "effect": "gui_handoff",
        "summary": "Bring the running GUI window to the front.",
        "params": [],
    },
    ("POST", "/api/v1/session/switch-dataset"): {
        "handler": "_handle_session_switch_dataset",
        "request_arg": "payload",
        "effect": "managed_dataset_session_switch",
        "summary": "Switch the current GUI session to another managed dataset by dataset_name.",
        "params": [
            {"name": "dataset_name", "in": "body", "type": "string", "required": True},
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
    },
    ("POST", "/api/v1/gui/prefill-takeout"): {
        "handler": "_handle_prefill_takeout",
        "request_arg": "payload",
        "effect": "gui_handoff",
        "summary": "Prepare Takeout context in GUI without executing an inventory write.",
        "params": [
            {"name": "record_id", "in": "body", "type": "integer", "required": False},
            {"name": "box", "in": "body", "type": "integer", "required": False},
            {"name": "position", "in": "body", "type": "string-or-integer", "required": False},
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
    },
    ("POST", "/api/v1/gui/prefill-add"): {
        "handler": "_handle_prefill_add",
        "request_arg": "payload",
        "effect": "gui_handoff",
        "summary": "Prepare Add Entry context in GUI without executing an inventory write.",
        "params": [
            {"name": "box", "in": "body", "type": "integer", "required": True},
            {"name": "position", "in": "body", "type": "string-or-integer", "required": False},
            {"name": "positions", "in": "body", "type": "array", "required": False},
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
        "constraints": [
            {
                "kind": "at_least_one_of",
                "params": ["position", "positions"],
            }
        ],
    },
    ("POST", "/api/v1/gui/prefill-ai-prompt"): {
        "handler": "_handle_prefill_ai_prompt",
        "request_arg": "payload",
        "effect": "gui_handoff",
        "summary": "Prepare an AI prompt in GUI without executing an inventory write.",
        "params": [
            {"name": "prompt", "in": "body", "type": "string", "required": True},
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
    },
    ("GET", "/api/v1/gui/stage-plan"): {
        "handler": "_handle_get_stage_plan",
        "request_arg": None,
        "status_code": 200,
        "effect": "gui_stage_state",
        "summary": "Read the current staged GUI plan items without mutating them.",
        "params": [],
    },
    ("POST", "/api/v1/gui/stage-plan"): {
        "handler": "_handle_stage_plan",
        "request_arg": "payload",
        "effect": "gui_stage_only",
        "summary": "Stage GUI plan items for human review without executing inventory writes.",
        "params": [
            {
                "name": "items",
                "in": "body",
                "type": "array",
                "required": True,
                "accepted_values": sorted(LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS),
                "item_payload_schema": "see result.stage_plan_schema in /capabilities",
            },
            {
                "name": "mode",
                "in": "body",
                "type": "string",
                "required": False,
                "default": "merge",
                "accepted_values": ["merge", "replace"],
                "description": "merge (default) dedups into existing staged items; "
                "replace discards all currently staged items first.",
            },
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
    },
    ("POST", "/api/v1/gui/stage-plan/clear"): {
        "handler": "_handle_clear_stage_plan",
        "request_arg": "payload",
        "effect": "gui_stage_only",
        "summary": "Clear all currently staged GUI plan items without executing inventory writes.",
        "params": [],
    },
}

LOCAL_OPEN_API_ROUTE_ALLOWLIST = frozenset(LOCAL_OPEN_API_ROUTE_SPECS)


def describe_local_open_api_route(route_key):
    """Return the public route description derived from the explicit route contract."""

    normalized_route_key = tuple(route_key or ())
    spec = dict(LOCAL_OPEN_API_ROUTE_SPECS.get(normalized_route_key) or {})
    if not spec:
        raise KeyError(f"Unknown local open api route: {normalized_route_key!r}")
    method, path = normalized_route_key
    return {
        "method": str(method or "").upper().strip(),
        "path": str(path or "").strip(),
        "effect": str(spec.get("effect") or ""),
        "summary": str(spec.get("summary") or ""),
        "params": deepcopy(list(spec.get("params") or [])),
        "constraints": deepcopy(list(spec.get("constraints") or [])),
    }


def iter_local_open_api_route_descriptions(*, sort_routes=False):
    route_keys = (
        sorted(LOCAL_OPEN_API_ROUTE_ALLOWLIST)
        if sort_routes
        else LOCAL_OPEN_API_ROUTE_SPECS.keys()
    )
    for route_key in route_keys:
        yield describe_local_open_api_route(route_key)
