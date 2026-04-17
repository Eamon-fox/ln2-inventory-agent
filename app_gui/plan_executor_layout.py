from __future__ import annotations

from typing import Dict, List

from lib import tool_api_write_adapter as _write_adapter
from lib.schema_aliases import coalesce_stored_at_value
from lib.yaml_ops import load_yaml


def load_box_layout(yaml_path: str) -> Dict[str, object]:
    try:
        data = load_yaml(yaml_path)
    except Exception:
        return {}
    return (data or {}).get("meta", {}).get("box_layout", {}) or {}


def to_tool_position(value: object, layout: Dict[str, object], *, field_name: str) -> str:
    return _write_adapter.to_tool_position(value, layout, field_name=field_name)


def to_tool_positions(values: object, layout: Dict[str, object], *, field_name: str) -> List[str]:
    return _write_adapter.to_tool_positions(values, layout, field_name=field_name)


def build_add_tool_payload(payload: Dict[str, object], layout: Dict[str, object]) -> Dict[str, object]:
    tool_payload = dict(payload or {})
    if "positions" not in tool_payload:
        raise ValueError("positions is required")
    tool_payload["positions"] = to_tool_positions(tool_payload.get("positions"), layout, field_name="positions")
    return tool_payload


def build_takeout_payload(
    items: List[Dict[str, object]],
    *,
    date_str: str,
    layout: Dict[str, object],
    include_target: bool = False,
) -> Dict[str, object]:
    entries = []
    for idx, item in enumerate(items):
        payload = item.get("payload") or {}
        source_box = item.get("box")
        if source_box in (None, ""):
            raise ValueError(f"items[{idx}].box is required")
        source_position = to_tool_position(
            payload.get("position"),
            layout,
            field_name=f"items[{idx}].position",
        )
        if include_target:
            target_box = payload.get("to_box")
            if target_box in (None, ""):
                target_box = source_box
            entry = {
                "record_id": payload.get("record_id"),
                "from": {"box": source_box, "position": source_position},
                "to": {
                    "box": target_box,
                    "position": to_tool_position(
                        payload.get("to_position"),
                        layout,
                        field_name=f"items[{idx}].to_position",
                    ),
                },
            }
        else:
            entry = {
                "record_id": payload.get("record_id"),
                "from": {"box": source_box, "position": source_position},
            }
        entries.append(entry)

    first_payload = (items[0].get("payload") or {}) if items else {}
    return {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
    }


def coalesce_add_stored_at(payload: Dict[str, object]):
    return coalesce_stored_at_value(
        stored_at=payload.get("stored_at"),
        frozen_at=payload.get("frozen_at"),
    )


_load_box_layout = load_box_layout
_to_tool_position = to_tool_position
_to_tool_positions = to_tool_positions
_build_add_tool_payload = build_add_tool_payload
_build_takeout_payload = build_takeout_payload
