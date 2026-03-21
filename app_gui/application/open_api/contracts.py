"""Explicit route and action allowlists for the local loopback API."""

LOCAL_OPEN_API_DEFAULT_PORT = 37666

LOCAL_OPEN_API_ROUTE_SPECS = {
    ("GET", "/api/v1/health"): {"handler": "_handle_health", "request_arg": None, "status_code": 200},
    ("GET", "/api/v1/session"): {"handler": "_handle_session", "request_arg": None, "status_code": 200},
    ("GET", "/api/v1/inventory/search"): {
        "handler": "_handle_inventory_search",
        "request_arg": "query_params",
        "status_code": 200,
    },
    ("GET", "/api/v1/inventory/filter"): {
        "handler": "_handle_inventory_filter",
        "request_arg": "query_params",
        "status_code": 200,
    },
    ("GET", "/api/v1/inventory/stats"): {
        "handler": "_handle_inventory_stats",
        "request_arg": "query_params",
        "status_code": 200,
    },
    ("GET", "/api/v1/inventory/validate"): {
        "handler": "_handle_inventory_validate",
        "request_arg": "query_params",
        "status_code": 200,
    },
    ("POST", "/api/v1/gui/focus"): {"handler": "_handle_focus", "request_arg": None, "status_code": 200},
    ("POST", "/api/v1/gui/prefill-takeout"): {
        "handler": "_handle_prefill_takeout",
        "request_arg": "payload",
    },
    ("POST", "/api/v1/gui/prefill-add"): {
        "handler": "_handle_prefill_add",
        "request_arg": "payload",
    },
    ("POST", "/api/v1/gui/prefill-ai-prompt"): {
        "handler": "_handle_prefill_ai_prompt",
        "request_arg": "payload",
    },
    ("POST", "/api/v1/gui/stage-plan"): {
        "handler": "_handle_stage_plan",
        "request_arg": "payload",
    },
}

LOCAL_OPEN_API_ROUTE_ALLOWLIST = frozenset(LOCAL_OPEN_API_ROUTE_SPECS)

LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS = frozenset({"add", "edit", "takeout", "move"})
