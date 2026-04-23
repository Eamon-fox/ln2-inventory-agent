"""Shared compact plan-item description helpers."""

from __future__ import annotations

import os

from lib.position_fmt import position_display_text


def _format_default(default, **kwargs):
    if kwargs:
        try:
            return str(default).format(**kwargs)
        except Exception:
            return str(default)
    return str(default)


def _msg(msg_func, key, default, **kwargs):
    if callable(msg_func):
        try:
            text = msg_func(key, default, **kwargs)
            if kwargs:
                try:
                    return str(text).format(**kwargs)
                except Exception:
                    return str(text)
            return str(text)
        except Exception:
            return _format_default(default, **kwargs)
    return _format_default(default, **kwargs)


def _box_text(box):
    if box in (None, ""):
        return "?"
    try:
        return str(int(box))
    except Exception:
        return str(box)


def _position_text(position, *, layout=None):
    return position_display_text(position, layout, default="?")


def _positions_text(positions, *, layout=None):
    normalized = []
    for value in list(positions or []):
        if value in (None, ""):
            continue
        normalized.append(_position_text(value, layout=layout))
    if not normalized:
        return "[?]"
    return f"[{', '.join(normalized)}]"


def build_plan_item_desc(
    item,
    *,
    layout=None,
    action_label=None,
    msg_func=None,
):
    """Return a compact human-readable plan-item summary."""
    item = item if isinstance(item, dict) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    action = str(item.get("action") or "").strip()
    action_norm = action.lower()
    action_text = str(action_label or action or "?")

    if action_norm == "rollback":
        backup_path = payload.get("backup_path")
        if backup_path:
            backup_name = os.path.basename(str(backup_path))
            return _msg(
                msg_func,
                "itemDesc.rollbackWithPath",
                "{action} | {name}",
                action=action_text,
                name=backup_name,
                backup_path=backup_path,
            )
        return _msg(
            msg_func,
            "itemDesc.rollbackLatest",
            "{action} | latest backup",
            action=action_text,
        )

    if action_norm == "add":
        positions = item.get("positions")
        if not isinstance(positions, (list, tuple, set)):
            positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        return _msg(
            msg_func,
            "itemDesc.add",
            "{action} | Box {box} | Positions {positions}",
            action=action_text,
            box=_box_text(item.get("box")),
            positions=_positions_text(positions, layout=layout),
        )

    label_value = item.get("record_id")
    if label_value in (None, ""):
        label_value = item.get("label")
    label_text = str(label_value).strip() if label_value not in (None, "") else ""

    box_text = _box_text(item.get("box"))
    pos_text = _position_text(item.get("position"), layout=layout)

    target = ""
    if action_norm == "move":
        to_pos = item.get("to_position")
        if to_pos not in (None, ""):
            to_box = item.get("to_box")
            to_pos_text = _position_text(to_pos, layout=layout)
            if to_box not in (None, "", item.get("box")):
                target = _msg(
                    msg_func,
                    "itemDesc.moveTargetWithBox",
                    " → Box {to_box}:{to_pos}",
                    to_box=_box_text(to_box),
                    to_pos=to_pos_text,
                )
            else:
                target = _msg(
                    msg_func,
                    "itemDesc.moveTarget",
                    " → {to_pos}",
                    to_pos=to_pos_text,
                )

    if label_text:
        return _msg(
            msg_func,
            "itemDesc.default",
            "{action} | ID {label} | Box {box}:{pos}{target}",
            action=action_text,
            label=label_text,
            box=box_text,
            pos=pos_text,
            target=target,
        )

    return _msg(
        msg_func,
        "itemDesc.defaultNoLabel",
        "{action} | Box {box}:{pos}{target}",
        action=action_text,
        box=box_text,
        pos=pos_text,
        target=target,
    )
