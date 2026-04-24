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


@dataclass(frozen=True)
class ToolRuntimeOverride:
    """Optional runtime-only overrides grouped by tool name."""

    layout_array_fields: tuple[str, ...] = ()
    schema_enricher: Callable[..., dict] | None = None
    validation_payload_adapter: Callable[..., dict] | None = None
    input_guard: Callable[..., str | None] | None = None
    error_hint: Callable[..., str | None] | None = None
    status_formatter: Callable[..., str] | None = None
    before_hook: Callable[..., dict] | None = None
    after_hook: Callable[..., dict] | None = None
    stage_guard: Callable[..., dict | None] | None = None


def _guard_stage_rollback(runner, payload):
    return _handlers._validate_rollback_backup_candidate(
        runner._yaml_path,
        payload.get("backup_path"),
    )


_DEFAULT_RUNTIME_OVERRIDE = ToolRuntimeOverride()

_TOOL_RUNTIME_OVERRIDES: dict[str, ToolRuntimeOverride] = {
    "add_entry": ToolRuntimeOverride(
        layout_array_fields=("positions",),
        schema_enricher=_validation._enrich_add_entry_schema,
        validation_payload_adapter=_validation._adapt_add_entry_schema_validation_payload,
        error_hint=_guidance._hint_add_entry_error,
        status_formatter=_status._format_add_entry,
    ),
    "edit_entry": ToolRuntimeOverride(
        schema_enricher=_validation._enrich_edit_entry_schema,
        validation_payload_adapter=_validation._adapt_edit_entry_schema_validation_payload,
        status_formatter=_status._format_edit_entry,
    ),
    "takeout": ToolRuntimeOverride(status_formatter=_status._format_takeout),
    "move": ToolRuntimeOverride(status_formatter=_status._format_move),
    "search_records": ToolRuntimeOverride(
        status_formatter=_status._format_search_records,
        after_hook=_hooks._after_search_records,
    ),
    "filter_records": ToolRuntimeOverride(
        status_formatter=_status._format_filter_records,
        after_hook=_hooks._after_filter_records,
    ),
    "generate_stats": ToolRuntimeOverride(status_formatter=_status._format_generate_stats),
    "validate": ToolRuntimeOverride(
        error_hint=_guidance._hint_validate_error,
        after_hook=_hooks._after_validate,
    ),
    "use_skill": ToolRuntimeOverride(after_hook=_hooks._after_use_skill),
    "import_migration_output": ToolRuntimeOverride(
        after_hook=_hooks._after_import_migration_output,
    ),
    "shell": ToolRuntimeOverride(
        input_guard=_validation._guard_shell_workdir,
        status_formatter=_status._format_shell,
        after_hook=_hooks._after_shell,
    ),
    "fs_list": ToolRuntimeOverride(
        input_guard=_validation._guard_fs_list,
        status_formatter=_status._format_fs_list,
        before_hook=_hooks._before_fs_list,
        after_hook=_hooks._after_fs_list,
    ),
    "fs_read": ToolRuntimeOverride(
        input_guard=_validation._guard_fs_read_write,
        status_formatter=_status._format_fs_read,
        after_hook=_hooks._after_fs_read,
    ),
    "fs_write": ToolRuntimeOverride(
        input_guard=_validation._guard_fs_read_write,
        status_formatter=_status._format_fs_write,
        before_hook=_hooks._before_fs_write,
        after_hook=_hooks._after_fs_write,
    ),
    "fs_copy": ToolRuntimeOverride(
        input_guard=_validation._guard_fs_copy,
        status_formatter=_status._format_fs_copy,
        before_hook=_hooks._before_fs_copy,
        after_hook=_hooks._after_fs_copy,
    ),
    "fs_edit": ToolRuntimeOverride(
        input_guard=_validation._guard_fs_edit,
        status_formatter=_status._format_fs_edit,
        before_hook=_hooks._before_fs_edit,
        after_hook=_hooks._after_fs_edit,
    ),
    "recent_frozen": ToolRuntimeOverride(
        input_guard=_validation._guard_recent_basis,
    ),
    "recent_stored": ToolRuntimeOverride(
        input_guard=_validation._guard_recent_basis,
    ),
    "rollback": ToolRuntimeOverride(
        input_guard=_validation._guard_rollback_backup_path,
        stage_guard=_guard_stage_rollback,
    ),
}


def _validate_named_map(label: str, mapping: dict[str, Any]) -> None:
    invalid = sorted(name for name in mapping if name not in TOOL_CONTRACTS)
    if invalid:
        raise ValueError(f"{label} reference unknown tools: {invalid}")


_validate_named_map("runtime overrides", _TOOL_RUNTIME_OVERRIDES)


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

        override = _TOOL_RUNTIME_OVERRIDES.get(descriptor.name, _DEFAULT_RUNTIME_OVERRIDE)
        runtime_specs[descriptor.name] = ToolRuntimeSpec(
            name=descriptor.name,
            handler=handler,
            stage_builder=stage_builder,
            stage_guard=override.stage_guard,
            layout_array_fields=override.layout_array_fields,
            schema_enricher=override.schema_enricher,
            validation_payload_adapter=override.validation_payload_adapter,
            input_guard=override.input_guard,
            error_hint=override.error_hint,
            status_formatter=override.status_formatter,
            before_hook=override.before_hook,
            after_hook=override.after_hook,
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
