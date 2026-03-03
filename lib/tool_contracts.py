"""Canonical tool contracts shared by AI and GUI layers.

This module is the single source of truth for tool names, request schemas,
and write-tool identification.
"""

from __future__ import annotations

from copy import deepcopy


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

TOOL_CONTRACTS = {
    "list_empty_positions": {
        "description": "List empty positions, optionally within one box.",
        "parameters": {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "search_records": {
        "description": "Search inventory records via text and structured filters. Use status=all|active|inactive and optional sort_by/sort_order.",
        "parameters": {
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
                    "enum": ["box", "position", "frozen_at", "id"],
                    "description": "Sort field. Defaults to frozen_at.",
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
    },
    "recent_frozen": {
        "description": "List recently frozen records by a basis/value selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "basis": {"type": "string", "enum": ["days", "count"]},
                "value": {"type": "integer", "minimum": 1},
            },
            "required": ["basis", "value"],
            "additionalProperties": False,
        },
    },
    "query_takeout_events": {
        "description": "Query takeout/move events, or request aggregated summary by range.",
        "parameters": {
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
    },
    "list_audit_timeline": {
        "description": "List persisted audit-table timeline rows sorted by audit_seq desc. Use action=backup rows as the source of truth for rollback backup_path selection.",
        "parameters": {
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
    },
    "recommend_positions": {
        "description": "Recommend empty positions for new tubes.",
        "parameters": {
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
    },
    "generate_stats": {
        "description": "Generate inventory statistics. With box set, returns box-only statistics.",
        "parameters": {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "include_inactive": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "get_raw_entries": {
        "description": "Fetch raw inventory records by ID list.",
        "parameters": {
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
    },
    "bash": {
        "description": "仅用于 Linux/WSL 环境。检测到 Windows 路径（如 D:\\）时不得使用，必须改用 powershell。",
        "parameters": {
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
                    "description": "Optional repository-relative working directory under migrate/ (defaults to migrate/).",
                },
            },
            "required": ["command", "description"],
            "additionalProperties": False,
        },
    },
    "powershell": {
        "description": "Windows 首选执行器。当仓库/路径在 Windows（如 D:\\...）时必须使用本工具。",
        "parameters": {
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
                    "description": "Optional repository-relative working directory under migrate/ (defaults to migrate/).",
                },
            },
            "required": ["command", "description"],
            "additionalProperties": False,
        },
    },
    "fs_list": {
        "description": "List files/directories under repository-relative path.",
        "parameters": {
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
    },
    "fs_read": {
        "description": "Read one text file under repository-relative path.",
        "parameters": {
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
    },
    "fs_write": {
        "description": "Write one text file under repository-relative path (migrate/ only).",
        "parameters": {
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
    },
    "fs_edit": {
        "description": "Replace text in one file under migrate/ by old/new string matching.",
        "parameters": {
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
    },
    "validate_migration_output": {
        "description": "Run strict validation on migrate/output/ln2_inventory.yaml (warnings are blocking) and write migrate/output/validation_report.json.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "import_migration_output": {
        "description": "Import migrate/output/ln2_inventory.yaml as a new managed dataset after explicit human confirmation.",
        "notes": "confirmation_token must be exactly CONFIRM_IMPORT. Always ask user for target_dataset_name via question before importing.",
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_token": {"type": "string"},
                "target_dataset_name": {"type": "string"},
            },
            "required": ["confirmation_token", "target_dataset_name"],
            "additionalProperties": False,
        },
    },
    "add_entry": {
        "description": "Add new frozen tube records in one box; `positions` can be batched, while one shared `fields` object applies to every created tube in that call.",
        "notes": "Provide sample metadata through `fields` using declared keys (e.g. fields.cell_line, fields.note, fields.<custom_field>). Per-position metadata is not supported; split into multiple add_entry calls (or staged items) when cell_line/note differs.",
        "parameters": {
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
                "frozen_at": {"type": "string"},
                "fields": {"type": "object"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["box", "positions", "frozen_at"],
            "additionalProperties": False,
        },
    },
    "edit_entry": {
        "description": "Edit metadata fields of an existing record.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "fields": {"type": "object", "minProperties": 1},
            },
            "required": ["record_id", "fields"],
            "additionalProperties": False,
        },
    },
    "takeout": {
        "description": "Record takeout for one or more tubes using explicit source box/position.",
        "parameters": {
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
    },
    "move": {
        "description": "Record move for one or more tubes using explicit source/target box+position.",
        "parameters": {
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
    },
    "rollback": {
        "description": "Rollback inventory YAML to a backup snapshot using explicit backup_path from list_audit_timeline.",
        "notes": "Always provide explicit backup_path selected from action=backup rows in list_audit_timeline.",
        "parameters": {
            "type": "object",
            "properties": {
                "backup_path": {"type": "string"},
            },
            "required": ["backup_path"],
            "additionalProperties": False,
        },
    },
    "manage_boxes": {
        "description": "Safely add/remove inventory boxes (human confirmation required).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove"]},
                "count": {"type": "integer", "minimum": 1},
                "box": {"type": "integer", "minimum": 1},
                "renumber_mode": {
                    "type": "string",
                    "enum": ["keep_gaps", "renumber_contiguous"],
                },
                "dry_run": {"type": "boolean"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    "question": {
        "description": "Ask one clarifying question with explicit options.",
        "notes": "question tool is not a write tool and must run alone.",
        "parameters": {
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
    },
    "staged_plan": {
        "description": "List/remove/clear staged plan items.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "remove", "clear"]},
                "index": {"type": "integer", "minimum": 0},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


WRITE_TOOLS = {
    "add_entry",
    "edit_entry",
    "takeout",
    "move",
    "rollback",
}


def get_tool_contracts():
    """Return a defensive copy of canonical contracts."""
    return deepcopy(TOOL_CONTRACTS)
