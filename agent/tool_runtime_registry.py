"""Canonical per-tool runtime metadata for AgentToolRunner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from lib.tool_registry import TOOL_CONTRACTS, iter_agent_dispatch_descriptors

from . import tool_hooks as _hooks
from . import tool_runner_guidance as _guidance
from . import tool_runner_handlers as _handlers
from . import tool_runner_validation as _validation
from . import tool_status_formatter as _status


@dataclass(frozen=True)
class ToolRuntimeSpec:
    """Agent-runtime-only metadata for one tool."""

    name: str
    handler: Callable[..., Any]
    stage_builder: Callable[..., Any] | None = None
    stage_guard: Callable[..., dict | None] | None = None
    layout_array_fields: tuple[str, ...] = ()
    schema_enricher: Callable[..., dict] | None = None
    validation_payload_adapter: Callable[..., dict] | None = None
    input_guard: Callable[..., str | None] | None = None
    error_hint: Callable[..., str | None] | None = None
    status_formatter: Callable[..., str] | None = None
    before_hook: Callable[..., dict] | None = None
    after_hook: Callable[..., dict] | None = None


_LAYOUT_ARRAY_FIELDS: dict[str, tuple[str, ...]] = {
    "add_entry": ("positions",),
}

_SCHEMA_ENRICHERS = {
    "add_entry": _validation._enrich_add_entry_schema,
    "edit_entry": _validation._enrich_edit_entry_schema,
}

_VALIDATION_PAYLOAD_ADAPTERS = {
    "add_entry": _validation._adapt_add_entry_schema_validation_payload,
    "edit_entry": _validation._adapt_edit_entry_schema_validation_payload,
}

_INPUT_GUARDS = {
    "fs_read": _validation._guard_fs_read_write,
    "fs_write": _validation._guard_fs_read_write,
    "fs_list": _validation._guard_fs_list,
    "fs_edit": _validation._guard_fs_edit,
    "bash": _validation._guard_shell_workdir,
    "powershell": _validation._guard_shell_workdir,
    "recent_frozen": _validation._guard_recent_basis,
    "recent_stored": _validation._guard_recent_basis,
    "rollback": _validation._guard_rollback_backup_path,
}

_ERROR_HINTS = {
    "validate": _guidance._hint_validate_error,
    "add_entry": _guidance._hint_add_entry_error,
}

_STATUS_FORMATTERS = {
    "bash": _status._format_bash,
    "powershell": _status._format_powershell,
    "fs_list": _status._format_fs_list,
    "fs_read": _status._format_fs_read,
    "fs_write": _status._format_fs_write,
    "fs_edit": _status._format_fs_edit,
    "search_records": _status._format_search_records,
    "filter_records": _status._format_filter_records,
    "generate_stats": _status._format_generate_stats,
    "add_entry": _status._format_add_entry,
    "takeout": _status._format_takeout,
    "move": _status._format_move,
    "edit_entry": _status._format_edit_entry,
}

_BEFORE_HOOKS = {
    "fs_list": _hooks._before_fs_list,
    "fs_write": _hooks._before_fs_write,
    "fs_edit": _hooks._before_fs_edit,
}

_AFTER_HOOKS = {
    "use_skill": _hooks._after_use_skill,
    "validate": _hooks._after_validate,
    "search_records": _hooks._after_search_records,
    "filter_records": _hooks._after_filter_records,
    "fs_list": _hooks._after_fs_list,
    "fs_read": _hooks._after_fs_read,
    "fs_write": _hooks._after_fs_write,
    "fs_edit": _hooks._after_fs_edit,
    "bash": _hooks._after_shell,
    "powershell": _hooks._after_shell,
    "import_migration_output": _hooks._after_import_migration_output,
}


def _guard_stage_rollback(runner, payload):
    return _handlers._validate_rollback_backup_candidate(
        runner._yaml_path,
        payload.get("backup_path"),
    )


_STAGE_GUARDS = {
    "rollback": _guard_stage_rollback,
}


def _validate_named_map(label: str, mapping: dict[str, Any]) -> None:
    invalid = sorted(name for name in mapping if name not in TOOL_CONTRACTS)
    if invalid:
        raise ValueError(f"{label} reference unknown tools: {invalid}")


for _label, _mapping in (
    ("layout array fields", _LAYOUT_ARRAY_FIELDS),
    ("schema enrichers", _SCHEMA_ENRICHERS),
    ("validation payload adapters", _VALIDATION_PAYLOAD_ADAPTERS),
    ("input guards", _INPUT_GUARDS),
    ("error hints", _ERROR_HINTS),
    ("status formatters", _STATUS_FORMATTERS),
    ("before hooks", _BEFORE_HOOKS),
    ("after hooks", _AFTER_HOOKS),
    ("stage guards", _STAGE_GUARDS),
):
    _validate_named_map(_label, _mapping)


def expected_runtime_tool_names() -> frozenset[str]:
    return frozenset(descriptor.name for descriptor in iter_agent_dispatch_descriptors())


def build_tool_runtime_specs(runner) -> dict[str, ToolRuntimeSpec]:
    """Build bound runtime specs for all handler-dispatched tools."""

    runtime_specs: dict[str, ToolRuntimeSpec] = {}
    missing_handlers: list[str] = []
    missing_stage_builders: list[str] = []

    for descriptor in iter_agent_dispatch_descriptors():
        handler = getattr(runner, str(descriptor.agent_handler_attr or ""), None)
        if not callable(handler):
            missing_handlers.append(descriptor.name)
            continue

        stage_builder = None
        if descriptor.is_write:
            stage_builder = getattr(runner, str(descriptor.stage_handler_attr or ""), None)
            if not callable(stage_builder):
                missing_stage_builders.append(descriptor.name)
                continue

        runtime_specs[descriptor.name] = ToolRuntimeSpec(
            name=descriptor.name,
            handler=handler,
            stage_builder=stage_builder,
            stage_guard=_STAGE_GUARDS.get(descriptor.name),
            layout_array_fields=tuple(_LAYOUT_ARRAY_FIELDS.get(descriptor.name, ())),
            schema_enricher=_SCHEMA_ENRICHERS.get(descriptor.name),
            validation_payload_adapter=_VALIDATION_PAYLOAD_ADAPTERS.get(descriptor.name),
            input_guard=_INPUT_GUARDS.get(descriptor.name),
            error_hint=_ERROR_HINTS.get(descriptor.name),
            status_formatter=_STATUS_FORMATTERS.get(descriptor.name),
            before_hook=_BEFORE_HOOKS.get(descriptor.name),
            after_hook=_AFTER_HOOKS.get(descriptor.name),
        )

    if missing_handlers:
        raise ValueError(f"Runtime handlers missing for tools: {sorted(set(missing_handlers))}")
    if missing_stage_builders:
        raise ValueError(
            f"Runtime stage builders missing for write tools: {sorted(set(missing_stage_builders))}"
        )
    expected = expected_runtime_tool_names()
    actual = frozenset(runtime_specs.keys())
    if actual != expected:
        raise ValueError(f"Runtime spec coverage mismatch: expected {sorted(expected)}, got {sorted(actual)}")
    return runtime_specs
