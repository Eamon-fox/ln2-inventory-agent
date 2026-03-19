"""Compatibility exports derived from the canonical tool registry.

The actual single source of truth now lives in `lib.tool_registry`.
This module preserves the legacy import surface for callers that still import:
- TOOL_CONTRACTS
- WRITE_TOOLS
- MIGRATION_TOOL_NAMES
- _WRITE_TOOL_TO_PLAN_ACTION
- VALID_PLAN_ACTIONS
- get_tool_contracts()
"""

from __future__ import annotations

from copy import deepcopy

from .tool_registry import (
    build_migration_tool_names,
    build_tool_contracts,
    build_write_tool_to_plan_action,
    build_write_tools,
)


TOOL_CONTRACTS = build_tool_contracts()

WRITE_TOOLS: frozenset[str] = build_write_tools()

MIGRATION_TOOL_NAMES: frozenset[str] = build_migration_tool_names()

_WRITE_TOOL_TO_PLAN_ACTION: dict[str, str] = build_write_tool_to_plan_action()

VALID_PLAN_ACTIONS: frozenset[str] = frozenset(_WRITE_TOOL_TO_PLAN_ACTION.values())

_INTERNAL_KEYS = {"_write", "_migration"}


def get_tool_contracts():
    """Return a defensive copy of canonical contracts without internal flags."""
    contracts = deepcopy(TOOL_CONTRACTS)
    for spec in contracts.values():
        for key in _INTERNAL_KEYS:
            spec.pop(key, None)
    return contracts
