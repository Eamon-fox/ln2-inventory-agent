"""Tool-access profiles for different agent runtime modes."""

from lib.tool_contracts import MIGRATION_TOOL_NAMES, TOOL_CONTRACTS


DEFAULT_AGENT_MODE = "default"
MIGRATION_AGENT_MODE = "migration"

# Migration mode is intentionally narrow: no inventory read/write tools,
# only migration workflow controls plus scoped file/shell operations.
# Derived from ``_migration: True`` flags in TOOL_CONTRACTS.
MIGRATION_ALLOWED_TOOLS = MIGRATION_TOOL_NAMES


def normalize_agent_mode(mode):
    text = str(mode or "").strip().lower()
    if text == MIGRATION_AGENT_MODE:
        return MIGRATION_AGENT_MODE
    return DEFAULT_AGENT_MODE


def resolve_allowed_tools(mode):
    normalized = normalize_agent_mode(mode)
    if normalized != MIGRATION_AGENT_MODE:
        return frozenset(TOOL_CONTRACTS.keys())
    return frozenset(
        name for name in TOOL_CONTRACTS.keys() if name in MIGRATION_ALLOWED_TOOLS
    )


def should_expose_inventory_context(mode):
    return normalize_agent_mode(mode) != MIGRATION_AGENT_MODE
