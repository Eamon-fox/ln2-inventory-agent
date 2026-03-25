"""Shared public contract helpers for inventory read/query surfaces."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .custom_fields import get_color_key, get_display_key, get_effective_fields
from .field_schema import get_applicable_alias_map
from .schema_aliases import LEGACY_TO_CANONICAL_MAP

SEARCH_MODE_VALUES = ("fuzzy", "exact", "keywords")

SEARCH_QUERY_DESCRIPTION = (
    "Optional search text (cell line, short name, notes, etc). "
    "Text normalizes spaces, hyphens, and underscores as equivalent separators; "
    "empty or '*' skips text filtering."
)

SEARCH_MODE_DESCRIPTION = (
    "Search strategy over separator-normalized text: "
    "fuzzy = substring match, keywords = AND-token match, "
    "exact = scalar equality against one normalized field value."
)

_PUBLIC_EFFECTIVE_FIELD_KEYS = (
    "key",
    "label",
    "type",
    "required",
    "default",
    "options",
    "multiline",
)

_INVENTORY_STRUCTURAL_FIELDS = (
    {"key": "id", "type": "integer"},
    {"key": "box", "type": "integer"},
    {"key": "position", "type": "integer-or-null", "nullable": True},
    {"key": "stored_at", "type": "date-string", "format": "YYYY-MM-DD"},
    {"key": "storage_events", "type": "array<object>"},
)


def _shape_field(
    name: str,
    field_type: str,
    description: str,
    *,
    optional: bool = False,
) -> dict[str, Any]:
    item = {
        "name": str(name or "").strip(),
        "type": str(field_type or "").strip(),
        "description": str(description or "").strip(),
    }
    if optional:
        item["optional"] = True
    return item


def _serialize_effective_field(field_def: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key in _PUBLIC_EFFECTIVE_FIELD_KEYS:
        if key in field_def:
            public[key] = deepcopy(field_def.get(key))
    return public


def build_inventory_dataset_schema_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the public dataset schema payload exposed by read-only surfaces."""

    if not isinstance(data, dict):
        return None

    raw_meta = data.get("meta")
    raw_inventory = data.get("inventory")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    inventory = list(raw_inventory) if isinstance(raw_inventory, list) else []
    raw_box_layout = meta.get("box_layout")

    effective_fields = [
        _serialize_effective_field(field_def)
        for field_def in get_effective_fields(meta, inventory=inventory)
        if isinstance(field_def, dict)
    ]

    alias_map = dict(LEGACY_TO_CANONICAL_MAP)
    alias_map.update(get_applicable_alias_map(meta, inventory=inventory))

    return {
        "box_layout": deepcopy(raw_box_layout) if isinstance(raw_box_layout, dict) else {},
        "structural_fields": [deepcopy(item) for item in _INVENTORY_STRUCTURAL_FIELDS],
        "custom_fields": effective_fields,
        "display_key": get_display_key(meta, inventory=inventory),
        "color_key": get_color_key(meta, inventory=inventory),
        "alias_map": alias_map,
    }


def build_inventory_search_response_shape() -> dict[str, Any]:
    return {
        "route": "GET /api/v1/inventory/search",
        "notes": [
            "records[] returns raw inventory record objects from the current dataset.",
            "Legacy alias keys may still appear in records[]; use dataset_schema.alias_map to interpret them.",
            "Search text treats space, hyphen, and underscore as equivalent separators.",
            "fuzzy = separator-normalized substring match; keywords = separator-normalized AND-token match; exact = separator-normalized scalar equality.",
        ],
        "result_fields": [
            _shape_field("query", "string-or-null", "Original query echo."),
            _shape_field("normalized_query", "string", "Separator-normalized query used for matching."),
            _shape_field("keywords", "array<string>", "Normalized query tokens used by keywords mode."),
            _shape_field("mode", "string", "Applied search mode."),
            _shape_field("records", "array<object>", "Matched raw inventory records."),
            _shape_field("total_count", "integer", "Total matched record count before max_results."),
            _shape_field("display_count", "integer", "Returned record count after max_results."),
            _shape_field("suggestions", "array<string>", "Operator hints when results are empty or too broad."),
            _shape_field("applied_filters", "object", "Normalized structured filters and sort settings."),
            _shape_field("slot_lookup", "object", "Resolved slot status when box/position is known.", optional=True),
        ],
        "nested_objects": {
            "applied_filters": [
                _shape_field("record_id", "integer-or-null", "Normalized record_id filter."),
                _shape_field("box", "integer-or-null", "Normalized box filter."),
                _shape_field("position", "integer-or-null", "Normalized internal position filter."),
                _shape_field("status", "string", "Applied status filter."),
                _shape_field("sort_by", "string", "Applied sort field."),
                _shape_field("sort_order", "string", "Applied sort order."),
                _shape_field("sort_nulls", "string", "Null ordering rule."),
                _shape_field(
                    "query_shortcut",
                    "string-or-null",
                    "Original location shortcut query when query resolved to box/position.",
                ),
            ],
            "slot_lookup": [
                _shape_field("box", "integer", "Resolved box."),
                _shape_field("position", "integer", "Resolved internal position."),
                _shape_field("status", "string", "One of empty/occupied/conflict."),
                _shape_field("record_count", "integer", "Number of records occupying the slot."),
                _shape_field("record_ids", "array<integer>", "Record IDs found at the slot."),
            ],
        },
    }


def build_inventory_filter_response_shape() -> dict[str, Any]:
    return {
        "route": "GET /api/v1/inventory/filter",
        "notes": [
            "rows[] returns Overview-table rows, not raw inventory records.",
            "rows[].values is a display-ready map keyed by columns[].",
            "column_types maps each column to one of list/text/number/date.",
        ],
        "result_fields": [
            _shape_field("columns", "array<string>", "Ordered Overview-table columns."),
            _shape_field("column_types", "object<string,string>", "Detected filter/sort type per column."),
            _shape_field("rows", "array<object>", "Overview-table rows after filtering, sorting, and pagination."),
            _shape_field("color_key", "string", "Current dataset color_key."),
            _shape_field("total_count", "integer", "Total matched row count before pagination."),
            _shape_field("display_count", "integer", "Returned row count after pagination."),
            _shape_field("matched_boxes", "array<integer>", "Boxes represented in the matched rows."),
            _shape_field("limit", "integer-or-null", "Applied page size."),
            _shape_field("offset", "integer", "Applied row offset."),
            _shape_field("has_more", "boolean", "Whether more rows remain after this page."),
            _shape_field("applied_filters", "object", "Normalized filter and sort state."),
            _shape_field("suggestions", "array<string>", "Operator hints when rows are empty.", optional=True),
        ],
        "nested_objects": {
            "rows[]": [
                _shape_field("row_kind", "string", "One of active/taken_out/empty_slot."),
                _shape_field("record_id", "integer-or-null", "Backing record ID when present."),
                _shape_field("box", "integer-or-null", "Row box."),
                _shape_field("position", "integer-or-null", "Row internal position."),
                _shape_field("active", "boolean", "Whether the row represents an active occupied slot."),
                _shape_field("color_value", "string", "Display value of the current color_key."),
                _shape_field("values", "object<string,string>", "Display-ready values keyed by columns[]."),
            ],
            "applied_filters": [
                _shape_field("keyword", "string", "Normalized top-level keyword filter."),
                _shape_field("box", "integer-or-null", "Applied box filter."),
                _shape_field("color_value", "string-or-null", "Applied color_key value filter."),
                _shape_field("include_inactive", "boolean", "Whether taken-out rows were included."),
                _shape_field("column_filters", "object", "Normalized per-column filter map."),
                _shape_field("sort_by", "string", "Applied sort field."),
                _shape_field("sort_order", "string", "Applied sort order."),
                _shape_field("sort_nulls", "string", "Null ordering rule."),
            ],
        },
    }


def build_inventory_response_shapes_payload() -> dict[str, Any]:
    return {
        "inventory_search": build_inventory_search_response_shape(),
        "inventory_filter": build_inventory_filter_response_shape(),
    }
