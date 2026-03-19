"""Plan item validation — shared by agent and GUI layers."""

from __future__ import annotations

from typing import Optional

from lib.plan_item_factory import PlanItem
from lib.tool_contracts import VALID_PLAN_ACTIONS

_VALID_ACTIONS = VALID_PLAN_ACTIONS


def validate_plan_item(item: PlanItem) -> Optional[str]:
    """Return an error message if *item* is invalid, or ``None`` if OK."""
    action = str(item.get("action", "")).lower()
    if action not in _VALID_ACTIONS:
        return f"Unknown action: {item.get('action')}"

    if action == "rollback":
        # rollback restores the whole YAML from backup; no box/position/record needed.
        return None

    box = item.get("box")
    if not isinstance(box, int):
        return "box must be an integer"
    if box < 0:
        return "box must be >= 0"

    pos = item.get("position")
    if not isinstance(pos, int):
        return "position must be an integer"
    if pos < 1:
        return "position must be a positive integer"

    if action == "move":
        to = item.get("to_position")
        if not isinstance(to, int) or to < 1:
            return "to_position must be a positive integer for move"
        to_box = item.get("to_box")
        if to_box is not None and to_box != "" and (not isinstance(to_box, int) or to_box < 1):
            return "to_box must be a positive integer"
        source_box = int(box)
        target_box = source_box if to_box in (None, "") else int(to_box)
        if target_box == source_box and to == pos:
            return "to_position must differ from position"

    if action == "add":
        # Keep this as lightweight schema validation.
        # Full write validation is handled by the shared staging gate.
        pass
    elif action == "edit":
        rid = item.get("record_id")
        if not isinstance(rid, int) or rid < 1:
            return "record_id must be a positive integer"
    else:
        rid = item.get("record_id")
        if not isinstance(rid, int) or rid < 1:
            return "record_id must be a positive integer"

    return None
