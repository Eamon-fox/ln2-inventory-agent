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

LOCAL_OPEN_API_ROUTE_SPECS = {
    ("GET", "/api/v1/capabilities"): {
        "handler": "_handle_capabilities",
        "request_arg": None,
        "status_code": 200,
        "effect": "capability_read",
        "summary": "Describe the local API allowlist, request shapes, and boundary limits.",
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
            },
            {"name": "focus", "in": "body", "type": "boolean", "required": False},
        ],
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
