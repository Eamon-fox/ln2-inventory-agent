"""
Module: test_tool_api
Layer: integration/inventory
Covers: lib/tool_api.py

Tool API 全链路读写
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    build_actor_context,
    tool_add_entry,
    tool_manage_boxes,
    tool_collect_timeline,
    tool_edit_entry,
    tool_export_inventory_csv,
    tool_move,
    tool_rollback,
    tool_set_box_layout_indexing,
    tool_set_box_tag,
    tool_takeout,
)
from lib.tool_api import (
    tool_filter_records,
    tool_get_raw_entries,
    tool_list_audit_timeline,
    tool_query_takeout_events,
    tool_recommend_positions,
    tool_search_records,
    tool_generate_stats,
    tool_list_empty_positions,
)
from lib.path_policy import PathPolicyError
from lib.tool_api_write_validation import resolve_request_backup_path
from lib.yaml_ops import (
    create_yaml_backup,
    get_audit_log_path,
    load_yaml,
    read_audit_events,
    write_yaml,
)
from tests.managed_paths import ManagedPathTestCase


def tool_batch_takeout(*args, **kwargs):
    return tool_takeout(*args, **kwargs)


def tool_batch_move(*args, **kwargs):
    return tool_move(*args, **kwargs)


def _flatten_single_preview(response):
    if not isinstance(response, dict):
        return response
    preview = response.get("preview")
    if not isinstance(preview, dict):
        return response
    operations = preview.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        return response
    op = operations[0]
    if not isinstance(op, dict):
        return response
    flat_preview = dict(preview)
    for key in (
        "record_id",
        "cell_line",
        "short_name",
        "box",
        "position",
        "old_position",
        "new_position",
        "to_position",
        "swap_with_record_id",
    ):
        if key in op:
            flat_preview[key] = op.get(key)
    if "old_position" in op and "position_before" not in flat_preview:
        flat_preview["position_before"] = op.get("old_position")
    if "new_position" in op and "position_after" not in flat_preview:
        flat_preview["position_after"] = op.get("new_position")
    normalized = dict(response)
    normalized["preview"] = flat_preview
    return normalized


def tool_record_takeout(
    yaml_path,
    record_id,
    from_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    response = tool_takeout(
        yaml_path=yaml_path,
        entries=[{"record_id": record_id, "from": from_slot}],
        date_str=date_str,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _flatten_single_preview(response)


def tool_record_move(
    yaml_path,
    record_id,
    from_slot,
    to_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    response = tool_move(
        yaml_path=yaml_path,
        entries=[{"record_id": record_id, "from": from_slot, "to": to_slot}],
        date_str=date_str,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _flatten_single_preview(response)


def make_record(rec_id=1, box=1, position=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records,
    }


def slot(box, position):
    return {"box": box, "position": position}


def takeout_entry(record_id, box, position):
    return {"record_id": record_id, "from": slot(box, position)}


def move_entry(record_id, from_box, from_position, to_box, to_position):
    return {
        "record_id": record_id,
        "from": slot(from_box, from_position),
        "to": slot(to_box, to_position),
    }


def write_raw_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def read_audit_rows(temp_dir):
    yaml_path = Path(temp_dir) / "inventory.yaml"
    if not yaml_path.exists():
        return []
    return read_audit_events(str(yaml_path))


def make_data_custom(records, rows=9, cols=9, box_count=None, indexing=None):
    """Build YAML data dict with custom box_layout."""
    layout = {"rows": rows, "cols": cols}
    if box_count is not None:
        layout["box_count"] = box_count
    if indexing is not None:
        layout["indexing"] = indexing
    return {"meta": {"box_layout": layout, "cell_line_required": False}, "inventory": records}
