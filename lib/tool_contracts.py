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

_SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "box": {"type": "integer", "minimum": 1},
        "position": _POSITION_VALUE_SCHEMA,
    },
    "required": ["box", "position"],
    "additionalProperties": False,
}

_TAKEOUT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "integer", "minimum": 1},
        "from": _SLOT_SCHEMA,
    },
    "required": ["record_id", "from"],
    "additionalProperties": False,
}

_MOVE_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "integer", "minimum": 1},
        "from": _SLOT_SCHEMA,
        "to": _SLOT_SCHEMA,
    },
    "required": ["record_id", "from", "to"],
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
        "description": "Search inventory records, or list recently frozen records via recent_* filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text (cell line, short name, notes, etc).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fuzzy", "exact", "keywords"],
                    "description": "Search strategy.",
                },
                "max_results": {"type": "integer", "minimum": 1},
                "case_sensitive": {"type": "boolean"},
                "box": {"type": "integer", "minimum": 1},
                "position": {"type": "integer", "minimum": 1},
                "record_id": {"type": "integer", "minimum": 1},
                "active_only": {"type": "boolean"},
                "recent_days": {"type": "integer", "minimum": 1},
                "recent_count": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "query_takeout_events": {
        "description": "Query takeout/move events, or timeline summary via view=summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "view": {
                    "type": "string",
                    "enum": ["events", "summary"],
                },
                "date": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "action": {"type": "string"},
                "max_records": {"type": "integer", "minimum": 0},
                "all_history": {"type": "boolean"},
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
        "description": "Generate inventory statistics.",
        "parameters": {
            "type": "object",
            "properties": {},
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
    "add_entry": {
        "description": "Add new frozen tube records.",
        "notes": "Provide all sample metadata through fields object (e.g. fields.short_name, fields.cell_line).",
        "parameters": {
            "type": "object",
            "properties": {
                "box": {"type": "integer", "minimum": 1},
                "positions": {
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1},
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
    "record_takeout": {
        "description": "Record takeout for one tube using explicit source slot.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "from": _SLOT_SCHEMA,
                "date": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["record_id", "from", "date"],
            "additionalProperties": False,
        },
    },
    "record_move": {
        "description": "Record move for one tube using explicit source and target slots.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer", "minimum": 1},
                "from": _SLOT_SCHEMA,
                "to": _SLOT_SCHEMA,
                "date": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["record_id", "from", "to", "date"],
            "additionalProperties": False,
        },
    },
    "batch_takeout": {
        "description": "Record takeout for multiple tubes using explicit source slots.",
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
    "batch_move": {
        "description": "Record move for multiple tubes using explicit source and target slots.",
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
        "description": "Rollback inventory YAML to a backup snapshot using explicit backup_path.",
        "notes": "Always provide explicit backup_path.",
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
        "description": "Safely add or remove inventory boxes.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "remove"]},
                "count": {"type": "integer", "minimum": 1},
                "box": {"type": "integer", "minimum": 1},
                "renumber_mode": {
                    "type": "string",
                    "enum": ["keep_gaps", "renumber_contiguous"],
                },
                "dry_run": {"type": "boolean"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
    "question": {
        "description": "Ask user clarifying questions when required values are unknown.",
        "notes": "question tool is not a write tool and must run alone.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "multiple": {"type": "boolean"},
                        },
                        "required": ["header", "question"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
    "manage_staged": {
        "description": "List, remove, or clear staged plan items.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "remove", "clear"],
                },
                "index": {"type": "integer", "minimum": 0},
                "action": {"type": "string"},
                "record_id": {"type": "integer", "minimum": 1},
                "position": {"type": "integer", "minimum": 1},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
}


WRITE_TOOLS = {
    "add_entry",
    "edit_entry",
    "record_takeout",
    "record_move",
    "batch_takeout",
    "batch_move",
    "rollback",
}


def get_tool_contracts():
    """Return a defensive copy of canonical contracts."""
    return deepcopy(TOOL_CONTRACTS)
