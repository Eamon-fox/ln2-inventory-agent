"""Canonical registry for tool contracts, agent dispatch, and GUI exposure.

This module is the actual single source of truth for:
- tool contract metadata
- write-tool / migration-tool classification
- plan action mapping for write tools
- agent dispatch handler binding
- plan-staging handler binding
- GUI bridge exposure policy

`lib.tool_contracts` remains as a compatibility facade that derives its exports
from this registry.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any


DISPATCH_HANDLER = "handler"
DISPATCH_SPECIAL = "special"

GUI_BRIDGE_READ = "read"
GUI_BRIDGE_WRITE = "write"
_TOOL_API_MODULE = "lib.tool_api"


@dataclass(frozen=True)
class GuiBridgeSpec:
    """Descriptor for one GUI-facing bridge method."""

    method_name: str
    strategy: str
    tool_api_attr: str
    positional_payload_args: tuple[str, ...] = ()
    defaults: dict[str, Any] = field(default_factory=dict)
    fixed_kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def required_payload_args(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.positional_payload_args
            if name not in self.defaults
        )


@dataclass(frozen=True)
class ToolDescriptor:
    """Unified metadata for one tool surface."""

    name: str
    description: str
    parameters: dict[str, Any]
    notes: str = ""
    is_write: bool = False
    is_migration: bool = False
    plan_action: str | None = None
    dispatch_style: str = DISPATCH_HANDLER
    agent_handler_attr: str | None = None
    stage_handler_attr: str | None = None
    gui_bridge: GuiBridgeSpec | None = None
    public_contract: bool = True
    agent_enabled: bool = True

    def contract_spec(self) -> dict[str, Any]:
        spec = {
            "description": self.description,
            "parameters": deepcopy(self.parameters),
        }
        if self.notes:
            spec["notes"] = self.notes
        if self.is_write:
            spec["_write"] = True
        if self.is_migration:
            spec["_migration"] = True
        return spec


def _resolve_callable(module_path: str, attr_name: str):
    module = import_module(str(module_path))
    normalized_attr = str(attr_name or "").strip()
    value = getattr(module, normalized_attr, None)
    if callable(value):
        return value
    raise AttributeError(f"{module_path}.{normalized_attr} is not callable")


def resolve_tool_api_callable(tool_api_attr: str):
    """Resolve one canonical Tool API callable from registry metadata."""

    return _resolve_callable(_TOOL_API_MODULE, tool_api_attr)


def _read_bridge(
    name: str,
    tool_api_attr: str,
    *,
    positional_payload_args: tuple[str, ...] = (),
    defaults: dict[str, Any] | None = None,
    fixed_kwargs: dict[str, Any] | None = None,
) -> GuiBridgeSpec:
    return GuiBridgeSpec(
        method_name=name,
        strategy=GUI_BRIDGE_READ,
        tool_api_attr=tool_api_attr,
        positional_payload_args=positional_payload_args,
        defaults=dict(defaults or {}),
        fixed_kwargs=dict(fixed_kwargs or {}),
    )


def _write_bridge(
    name: str,
    tool_api_attr: str,
    *,
    positional_payload_args: tuple[str, ...] = (),
    defaults: dict[str, Any] | None = None,
    fixed_kwargs: dict[str, Any] | None = None,
) -> GuiBridgeSpec:
    return GuiBridgeSpec(
        method_name=name,
        strategy=GUI_BRIDGE_WRITE,
        tool_api_attr=tool_api_attr,
        positional_payload_args=positional_payload_args,
        defaults=dict(defaults or {}),
        fixed_kwargs=dict(fixed_kwargs or {}),
    )


def _tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    notes: str = "",
    is_write: bool = False,
    is_migration: bool = False,
    plan_action: str | None = None,
    dispatch_style: str = DISPATCH_HANDLER,
    agent_handler_attr: str | None = None,
    stage_handler_attr: str | None = None,
    gui_bridge: GuiBridgeSpec | None = None,
    public_contract: bool = True,
    agent_enabled: bool = True,
) -> ToolDescriptor:
    if agent_enabled and dispatch_style == DISPATCH_HANDLER and agent_handler_attr is None:
        agent_handler_attr = f"_run_{name}"
    if is_write and stage_handler_attr is None:
        stage_handler_attr = f"_stage_items_{name}"
    return ToolDescriptor(
        name=name,
        description=description,
        parameters=deepcopy(parameters),
        notes=notes,
        is_write=is_write,
        is_migration=is_migration,
        plan_action=plan_action,
        dispatch_style=dispatch_style,
        agent_handler_attr=agent_handler_attr,
        stage_handler_attr=stage_handler_attr,
        gui_bridge=gui_bridge,
        public_contract=public_contract,
        agent_enabled=agent_enabled,
    )


_POSITION_VALUE_SCHEMA = {
    "oneOf": [
        {"type": "integer", "minimum": 1},
        {"type": "string"},
    ]
}

_TAKEOUT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "integer", "minimum": 1},
        "from_box": {"type": "integer", "minimum": 1},
        "from_position": _POSITION_VALUE_SCHEMA,
    },
    "required": ["record_id", "from_box", "from_position"],
    "additionalProperties": False,
}

_MOVE_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "integer", "minimum": 1},
        "from_box": {"type": "integer", "minimum": 1},
        "from_position": _POSITION_VALUE_SCHEMA,
        "to_box": {"type": "integer", "minimum": 1},
        "to_position": _POSITION_VALUE_SCHEMA,
    },
    "required": [
        "record_id",
        "from_box",
        "from_position",
        "to_box",
        "to_position",
    ],
    "additionalProperties": False,
}


_TOOL_DESCRIPTOR_LIST = (
    _tool(
        "list_empty_positions",
        "List empty positions, optionally within one box.",
        {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "list_empty_positions",
            "tool_list_empty_positions",
            positional_payload_args=("box",),
            defaults={"box": None},
        ),
    ),
    _tool(
        "export_inventory_csv",
        "Export the full inventory snapshot as CSV for GUI workflows.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "export_inventory_csv",
            "tool_export_inventory_csv",
            positional_payload_args=("output_path",),
        ),
        public_contract=False,
        agent_enabled=False,
    ),
    _tool(
        "collect_timeline",
        "Collect aggregated takeout/move timeline statistics for GUI dashboards.",
        {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1},
                "all_history": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "collect_timeline",
            "tool_collect_timeline",
            positional_payload_args=("days", "all_history"),
            defaults={
                "days": 7,
                "all_history": False,
            },
        ),
        public_contract=False,
        agent_enabled=False,
    ),
    _tool(
        "search_records",
        "Search inventory records via text and structured filters. Use status=all|active|inactive and optional sort_by/sort_order.",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search text (cell line, short name, notes, etc); empty or '*' skips text filtering.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fuzzy", "exact", "keywords"],
                    "description": "Search strategy.",
                },
                "max_results": {"type": "integer", "minimum": 1},
                "case_sensitive": {"type": "boolean"},
                "box": {"type": "integer", "minimum": 1},
                "position": _POSITION_VALUE_SCHEMA,
                "record_id": {"type": "integer", "minimum": 1},
                "status": {
                    "type": "string",
                    "enum": ["all", "active", "inactive"],
                    "description": "Record status scope: all records, active only, or inactive only.",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["box", "position", "stored_at", "id"],
                    "description": "Sort field. Defaults to stored_at.",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort direction. Defaults to desc.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    _tool(
        "filter_records",
        "Filter inventory records using Overview table semantics: keyword, box, color_key value, include_inactive, column filters, and table sorting.",
        {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Optional table keyword search applied to the rendered row text.",
                },
                "box": {"type": "integer", "minimum": 1},
                "color_value": {
                    "type": "string",
                    "description": "Optional value of the current dataset color_key field.",
                },
                "include_inactive": {"type": "boolean"},
                "column_filters": {
                    "type": "object",
                    "description": "Optional per-column filter map. Each value must be one of list/text/number/date filter configs.",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Optional table column name to sort by. Defaults to location.",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort direction. Defaults to asc.",
                },
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
            },
            "required": [],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "filter_records",
            "tool_filter_records",
            positional_payload_args=(
                "keyword",
                "box",
                "color_value",
                "include_inactive",
                "column_filters",
                "sort_by",
                "sort_order",
                "limit",
                "offset",
            ),
            defaults={
                "keyword": "",
                "box": None,
                "color_value": None,
                "include_inactive": False,
                "column_filters": None,
                "sort_by": "location",
                "sort_order": "asc",
                "limit": None,
                "offset": 0,
            },
        ),
    ),
    _tool(
        "recent_stored",
        "List recently stored records by a basis/value selector.",
        {
            "type": "object",
            "properties": {
                "basis": {"type": "string", "enum": ["days", "count"]},
                "value": {"type": "integer", "minimum": 1},
            },
            "required": ["basis", "value"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "recent_frozen",
        "Deprecated alias for recent_stored.",
        {
            "type": "object",
            "properties": {
                "basis": {"type": "string", "enum": ["days", "count"]},
                "value": {"type": "integer", "minimum": 1},
            },
            "required": ["basis", "value"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "query_takeout_events",
        "Query takeout/move events, or request aggregated summary by range.",
        {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "action": {"type": "string"},
                "max_records": {"type": "integer", "minimum": 0},
                "view": {"type": "string", "enum": ["events", "summary"]},
                "range": {"type": "string", "enum": ["7d", "30d", "90d", "all"]},
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    _tool(
        "list_audit_timeline",
        "List persisted audit-table timeline rows sorted by audit_seq desc. Use action=backup rows as the source of truth for rollback backup_path selection.",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
                "action_filter": {"type": "string"},
                "status_filter": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "list_audit_timeline",
            "tool_list_audit_timeline",
            positional_payload_args=(
                "limit",
                "offset",
                "action_filter",
                "status_filter",
                "start_date",
                "end_date",
            ),
            defaults={
                "limit": 50,
                "offset": 0,
                "action_filter": None,
                "status_filter": None,
                "start_date": None,
                "end_date": None,
            },
        ),
    ),
    _tool(
        "recommend_positions",
        "Recommend empty positions for new tubes.",
        {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1},
                "box_preference": {"type": "integer", "minimum": 1},
                "strategy": {
                    "type": "string",
                    "enum": ["consecutive", "same_row", "any"],
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    _tool(
        "generate_stats",
        "Generate inventory statistics. With box set, returns box-only statistics.",
        {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "include_inactive": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        },
        gui_bridge=_read_bridge(
            "generate_stats",
            "tool_generate_stats",
            positional_payload_args=("box", "include_inactive"),
            defaults={
                "box": None,
                "include_inactive": False,
            },
            fixed_kwargs={"full_records_for_gui": True},
        ),
    ),
    _tool(
        "get_raw_entries",
        "Fetch raw inventory records by ID list.",
        {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 1,
                },
            },
            "required": ["ids"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "bash",
        "Run a bash command in Linux/WSL environments. Do not use it for Windows-only paths such as D:\\...",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Terminal command text to execute exactly as provided.",
                },
                "description": {
                    "type": "string",
                    "description": "Clear and concise command purpose (recommended 5-10 words).",
                },
                "timeout": {
                    "type": "number",
                    "description": "Optional timeout in milliseconds.",
                },
                "workdir": {
                    "type": "string",
                    "description": "Optional repository-relative working directory under repo root (defaults to repo root).",
                },
            },
            "required": ["command", "description"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "powershell",
        "Run a PowerShell command in Windows environments. Prefer this tool when the repository path is on Windows.",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Terminal command text to execute exactly as provided.",
                },
                "description": {
                    "type": "string",
                    "description": "Clear and concise command purpose (recommended 5-10 words).",
                },
                "timeout": {
                    "type": "number",
                    "description": "Optional timeout in milliseconds.",
                },
                "workdir": {
                    "type": "string",
                    "description": "Optional repository-relative working directory under repo root (defaults to repo root).",
                },
            },
            "required": ["command", "description"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "fs_list",
        "List files/directories under repository-relative path.",
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path (defaults to '.').",
                },
                "max_entries": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "fs_read",
        "Read one text file under repository-relative path.",
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path.",
                },
                "encoding": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "fs_write",
        "Write one text file under repository-relative path (migrate/ only).",
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path under migrate/.",
                },
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "fs_edit",
        "Replace text in one file under migrate/ by old/new string matching.",
        {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "Repository-relative file path under migrate/.",
                },
                "oldString": {
                    "type": "string",
                    "description": "The text to replace.",
                },
                "newString": {
                    "type": "string",
                    "description": "Replacement text; must differ from oldString.",
                },
                "replaceAll": {
                    "type": "boolean",
                    "description": "Replace all occurrences of oldString (default false).",
                },
            },
            "required": ["filePath", "oldString", "newString"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "validate",
        "Validate a repository-relative YAML file. Managed inventory paths use current inventory semantics; other YAML paths use document validation semantics. Returns errors and warnings only and does not write side-effect files.",
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path to a .yaml/.yml file.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        is_migration=True,
    ),
    _tool(
        "import_migration_output",
        "Import migrate/output/ln2_inventory.yaml as a new managed dataset after explicit human confirmation.",
        {
            "type": "object",
            "properties": {
                "confirmation_token": {"type": "string"},
                "target_dataset_name": {"type": "string"},
            },
            "required": ["confirmation_token", "target_dataset_name"],
            "additionalProperties": False,
        },
        notes="confirmation_token must be exactly CONFIRM_IMPORT. Always ask user for target_dataset_name via question before importing.",
        is_migration=True,
    ),
    _tool(
        "add_entry",
        "Add new stored sample records in one box; `positions` can be batched, while one shared `fields` object applies to every created tube in that call.",
        {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "positions": {
                    "oneOf": [
                        {
                            "type": "array",
                            "items": _POSITION_VALUE_SCHEMA,
                            "minItems": 1,
                        },
                        {"type": "string"},
                    ]
                },
                "stored_at": {"type": "string"},
                "fields": {"type": "object"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["box", "positions", "stored_at"],
            "additionalProperties": False,
        },
        notes="Provide sample metadata through `fields` using declared keys (e.g. fields.cell_line, fields.note, fields.<custom_field>). Per-position metadata is not supported; split into multiple add_entry calls (or staged items) when cell_line/note differs.",
        is_write=True,
        plan_action="add",
        gui_bridge=_write_bridge(
            "add_entry",
            "tool_add_entry",
        ),
    ),
    _tool(
        "edit_entry",
        "Edit metadata fields of an existing record.",
        {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "fields": {"type": "object", "minProperties": 1},
            },
            "required": ["record_id", "fields"],
            "additionalProperties": False,
        },
        is_write=True,
        plan_action="edit",
        gui_bridge=_write_bridge(
            "edit_entry",
            "tool_edit_entry",
            positional_payload_args=(
                "record_id",
                "fields",
                "execution_mode",
                "auto_backup",
                "request_backup_path",
            ),
            defaults={
                "execution_mode": None,
                "auto_backup": True,
                "request_backup_path": None,
            },
        ),
    ),
    _tool(
        "takeout",
        "Record takeout for one or more tubes using explicit source box/position.",
        {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "items": _TAKEOUT_ENTRY_SCHEMA,
                },
                "date": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["entries", "date"],
            "additionalProperties": False,
        },
        is_write=True,
        plan_action="takeout",
        gui_bridge=_write_bridge(
            "takeout",
            "tool_takeout",
        ),
    ),
    _tool(
        "move",
        "Record move for one or more tubes using explicit source/target box+position.",
        {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "items": _MOVE_ENTRY_SCHEMA,
                },
                "date": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["entries", "date"],
            "additionalProperties": False,
        },
        is_write=True,
        plan_action="move",
        gui_bridge=_write_bridge(
            "move",
            "tool_move",
        ),
    ),
    _tool(
        "batch_add_entries",
        "Internal helper that batches multiple add_entry payloads into one write cycle.",
        {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "object"},
                },
            },
            "required": ["entries"],
            "additionalProperties": False,
        },
        public_contract=False,
        agent_enabled=False,
    ),
    _tool(
        "rollback",
        "Rollback inventory YAML to a backup snapshot using explicit backup_path from list_audit_timeline.",
        {
            "type": "object",
            "properties": {
                "backup_path": {"type": "string"},
            },
            "required": ["backup_path"],
            "additionalProperties": False,
        },
        notes="Always provide explicit backup_path selected from action=backup rows in list_audit_timeline.",
        is_write=True,
        plan_action="rollback",
        gui_bridge=_write_bridge(
            "rollback",
            "tool_rollback",
            positional_payload_args=(
                "backup_path",
                "source_event",
                "execution_mode",
                "request_backup_path",
            ),
            defaults={
                "backup_path": None,
                "source_event": None,
                "execution_mode": None,
                "request_backup_path": None,
            },
        ),
    ),
    _tool(
        "set_box_tag",
        "Set or clear one box tag through the GUI bridge.",
        {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "tag": {"type": "string"},
                "execution_mode": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "auto_backup": {"type": "boolean"},
                "request_backup_path": {"type": "string"},
            },
            "required": ["box"],
            "additionalProperties": False,
        },
        gui_bridge=_write_bridge(
            "set_box_tag",
            "tool_set_box_tag",
            positional_payload_args=(
                "box",
                "tag",
                "execution_mode",
                "dry_run",
                "auto_backup",
                "request_backup_path",
            ),
            defaults={
                "tag": "",
                "execution_mode": None,
                "dry_run": False,
                "auto_backup": True,
                "request_backup_path": None,
            },
        ),
        public_contract=False,
        agent_enabled=False,
    ),
    _tool(
        "manage_boxes",
        "Safely add/remove inventory boxes (human confirmation required).",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "add_boxes", "increase", "remove_box", "delete"],
                },
                "count": {"type": "integer", "minimum": 1},
                "box": {"type": "integer", "minimum": 1},
                "renumber_mode": {
                    "type": "string",
                    "enum": [
                        "keep_gaps",
                        "renumber_contiguous",
                        "keep",
                        "gaps",
                        "renumber",
                        "compact",
                        "reindex",
                    ],
                },
                "dry_run": {"type": "boolean"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        gui_bridge=_write_bridge(
            "manage_boxes",
            "tool_manage_boxes",
        ),
    ),
    _tool(
        "use_skill",
        "Load one built-in skill by exact skill name and return its instructions plus bundled resource lists.",
        {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
            },
            "required": ["skill_name"],
            "additionalProperties": False,
        },
        notes="Use this when a request matches an advertised built-in skill. Call it explicitly instead of silently reading skill files.",
        is_migration=True,
    ),
    _tool(
        "question",
        "Ask one clarifying question with explicit options.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
            },
            "required": ["question", "options"],
            "additionalProperties": False,
        },
        notes="question tool is not a write tool and must run alone.",
        is_migration=True,
        dispatch_style=DISPATCH_SPECIAL,
        agent_handler_attr=None,
    ),
    _tool(
        "staged_plan",
        "List/remove/clear staged plan items.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "remove", "clear"]},
                "index": {"type": "integer", "minimum": 0},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    ),
)


def _validate_registry(entries: tuple[ToolDescriptor, ...]) -> None:
    seen_names: set[str] = set()
    seen_bridge_methods: set[str] = set()

    for descriptor in entries:
        if descriptor.name in seen_names:
            raise ValueError(f"Duplicate tool descriptor: {descriptor.name}")
        seen_names.add(descriptor.name)

        if descriptor.agent_enabled:
            if descriptor.dispatch_style not in {DISPATCH_HANDLER, DISPATCH_SPECIAL}:
                raise ValueError(
                    f"Unsupported dispatch_style for {descriptor.name}: {descriptor.dispatch_style}"
                )
            if descriptor.dispatch_style == DISPATCH_HANDLER and not descriptor.agent_handler_attr:
                raise ValueError(f"Missing agent_handler_attr for {descriptor.name}")
        elif descriptor.agent_handler_attr:
            raise ValueError(
                f"Non-agent tool {descriptor.name} must not define agent_handler_attr"
            )

        if descriptor.is_write:
            if not descriptor.plan_action:
                raise ValueError(f"Missing plan_action for write tool {descriptor.name}")
            if not descriptor.stage_handler_attr:
                raise ValueError(f"Missing stage_handler_attr for write tool {descriptor.name}")
        elif descriptor.stage_handler_attr:
            raise ValueError(
                f"Non-write tool {descriptor.name} must not define stage_handler_attr"
            )

        bridge = descriptor.gui_bridge
        if bridge is None:
            continue
        if bridge.strategy not in {GUI_BRIDGE_READ, GUI_BRIDGE_WRITE}:
            raise ValueError(
                f"Unsupported GUI bridge strategy for {descriptor.name}: {bridge.strategy}"
            )
        if not bridge.method_name:
            raise ValueError(f"Missing GUI bridge method_name for {descriptor.name}")
        if not bridge.tool_api_attr:
            raise ValueError(f"Missing GUI bridge tool_api_attr for {descriptor.name}")
        try:
            resolve_tool_api_callable(str(bridge.tool_api_attr))
        except Exception as exc:
            raise ValueError(
                f"Invalid GUI bridge tool_api_attr for {descriptor.name}: {bridge.tool_api_attr}"
            ) from exc
        if bridge.method_name in seen_bridge_methods:
            raise ValueError(
                f"Duplicate GUI bridge method_name: {bridge.method_name}"
            )
        seen_bridge_methods.add(bridge.method_name)


_validate_registry(_TOOL_DESCRIPTOR_LIST)

TOOL_REGISTRY: dict[str, ToolDescriptor] = {
    descriptor.name: descriptor for descriptor in _TOOL_DESCRIPTOR_LIST
}


def _contract_descriptors() -> tuple[ToolDescriptor, ...]:
    return tuple(
        descriptor
        for descriptor in _TOOL_DESCRIPTOR_LIST
        if descriptor.public_contract
    )


def iter_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return _contract_descriptors()


def iter_agent_dispatch_descriptors() -> tuple[ToolDescriptor, ...]:
    return tuple(
        descriptor
        for descriptor in _TOOL_DESCRIPTOR_LIST
        if descriptor.agent_enabled and descriptor.dispatch_style == DISPATCH_HANDLER
    )


def iter_write_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return tuple(
        descriptor
        for descriptor in _contract_descriptors()
        if descriptor.is_write
    )


def iter_gui_bridge_descriptors() -> tuple[ToolDescriptor, ...]:
    return tuple(
        descriptor
        for descriptor in _TOOL_DESCRIPTOR_LIST
        if descriptor.gui_bridge is not None
    )


def get_tool_descriptor(tool_name: str) -> ToolDescriptor | None:
    return TOOL_REGISTRY.get(tool_name)


def build_tool_contracts() -> dict[str, dict[str, Any]]:
    return {
        descriptor.name: descriptor.contract_spec()
        for descriptor in _contract_descriptors()
    }


def build_write_tools() -> frozenset[str]:
    return frozenset(
        descriptor.name
        for descriptor in _contract_descriptors()
        if descriptor.is_write
    )


def build_migration_tool_names() -> frozenset[str]:
    return frozenset(
        descriptor.name
        for descriptor in _contract_descriptors()
        if descriptor.is_migration
    )


def build_write_tool_to_plan_action() -> dict[str, str]:
    return {
        descriptor.name: str(descriptor.plan_action)
        for descriptor in _contract_descriptors()
        if descriptor.is_write and descriptor.plan_action
    }
