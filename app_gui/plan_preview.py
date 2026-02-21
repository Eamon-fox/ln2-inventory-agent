"""Pure-python plan simulation helpers for GUI previews.

This module intentionally does not depend on PySide6 so it can be unit-tested.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from lib.yaml_ops import load_yaml

Loc = Tuple[int, int]  # (box, position)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _copy_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(rec)
    pos = rec.get("position")
    out["position"] = pos
    return out


def _build_owner_map(records_by_id: Dict[int, Dict[str, Any]]) -> tuple[Dict[Loc, int], List[str]]:
    owner: Dict[Loc, int] = {}
    errors: List[str] = []
    for rid, rec in records_by_id.items():
        box = rec.get("box")
        pos = rec.get("position")
        if box is None or pos is None:
            continue
        try:
            box_i = int(box)
            loc = (box_i, int(pos))
        except (TypeError, ValueError):
            continue
        prev = owner.get(loc)
        if prev is not None and prev != rid:
            errors.append(f"Position conflict at Box {loc[0]}:{loc[1]} (IDs {prev} vs {rid})")
        owner[loc] = rid
    return owner, errors


def simulate_plan_pos_map(
    *,
    base_records_by_id: Dict[int, Dict[str, Any]],
    plan_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Simulate the post-execution occupancy map for a plan (best-effort).

    Returns:
        dict with keys:
        - ok: bool
        - pos_map: Dict[(box,pos), record]
        - errors: List[str]
        - predicted_new_ids: List[int] (for add actions)
    """
    items = [it for it in (plan_items or []) if isinstance(it, dict)]
    rollback_items = [it for it in items if str(it.get("action") or "").lower() == "rollback"]
    if rollback_items:
        if len(items) != 1:
            return {
                "ok": False,
                "pos_map": {},
                "errors": ["Rollback must be the only item in the plan preview."],
                "predicted_new_ids": [],
            }

        payload = rollback_items[0].get("payload") or {}
        backup_path = payload.get("backup_path")
        if not backup_path:
            return {
                "ok": False,
                "pos_map": {},
                "errors": ["rollback payload.backup_path is required for preview."],
                "predicted_new_ids": [],
            }
        try:
            data = load_yaml(str(backup_path))
        except Exception as exc:
            return {
                "ok": False,
                "pos_map": {},
                "errors": [f"Failed to load rollback backup for preview: {exc}"],
                "predicted_new_ids": [],
            }

        inv = data.get("inventory", []) if isinstance(data, dict) else []
        records_by_id: Dict[int, Dict[str, Any]] = {}
        for rec in inv:
            if not isinstance(rec, dict):
                continue
            rid = _to_int(rec.get("id"), default=0)
            if rid <= 0:
                continue
            records_by_id[rid] = _copy_record(rec)

        owner, errors = _build_owner_map(records_by_id)
        pos_map = {loc: records_by_id[rid] for loc, rid in owner.items() if rid in records_by_id}
        return {
            "ok": not errors,
            "pos_map": pos_map,
            "errors": errors,
            "predicted_new_ids": [],
        }

    # Copy base inventory state so the preview doesn't mutate the real cache.
    records_by_id: Dict[int, Dict[str, Any]] = {}
    for rid, rec in (base_records_by_id or {}).items():
        if not isinstance(rec, dict):
            continue
        rid_i = _to_int(rid, default=0)
        if rid_i <= 0:
            continue
        records_by_id[rid_i] = _copy_record(rec)

    predicted_new_ids: List[int] = []
    errors: List[str] = []

    owner, owner_errors = _build_owner_map(records_by_id)
    errors.extend(owner_errors)

    next_id = (max(records_by_id.keys()) + 1) if records_by_id else 1

    # Phase 1: add (sequential, like executor)
    for item in items:
        if str(item.get("action") or "").lower() != "add":
            continue

        payload = item.get("payload") or {}
        box = _to_int(payload.get("box", item.get("box")), default=0)
        positions = payload.get("positions")
        if not isinstance(positions, list):
            positions = []

        for pos_raw in positions:
            pos = _to_int(pos_raw, default=0)
            if box <= 0 or pos <= 0:
                errors.append("Invalid add preview item (box/position).")
                continue

            loc = (box, pos)
            if loc in owner:
                errors.append(f"Add conflict: Box {box}:{pos} already occupied.")
                continue

            rid = next_id
            next_id += 1
            predicted_new_ids.append(rid)

            rec = {
                "id": rid,
                "box": box,
                "position": pos,
                "frozen_at": payload.get("frozen_at"),
            }
            fields = payload.get("fields") or {}
            rec.update(fields)
            records_by_id[rid] = rec
            owner[loc] = rid

    # Phase 2: moves (batch semantics, sequential swap behavior)
    for item in items:
        if str(item.get("action") or "").lower() != "move":
            continue

        record_id = _to_int(item.get("record_id"), default=0)
        from_pos = _to_int(item.get("position"), default=0)
        to_pos = _to_int(item.get("to_position"), default=0)
        if record_id <= 0 or from_pos <= 0 or to_pos <= 0:
            errors.append("Invalid move preview item (record_id/position/to_position).")
            continue

        rec = records_by_id.get(record_id)
        if not rec:
            errors.append(f"Move preview failed: ID {record_id} not found.")
            continue

        current_box = _to_int(rec.get("box"), default=0)
        current_position = rec.get("position")
        if current_position != from_pos:
            errors.append(
                f"Move preview failed: ID {record_id} source pos {from_pos} does not match {current_position}."
            )
            continue

        entry_to_box = item.get("to_box")
        to_box = _to_int(entry_to_box, default=0) if entry_to_box not in (None, "") else 0
        cross_box = bool(to_box) and to_box != current_box
        target_box = to_box if cross_box else current_box

        src_loc = (current_box, from_pos)
        dst_loc = (target_box, to_pos)

        if owner.get(src_loc) != record_id:
            errors.append(f"Move preview failed: source owner mismatch at Box {src_loc[0]}:{src_loc[1]}.")
            continue

        dest_owner = owner.get(dst_loc)
        if dest_owner is None:
            owner.pop(src_loc, None)
            owner[dst_loc] = record_id
            rec["position"] = to_pos
            if cross_box:
                rec["box"] = target_box
            continue

        if dest_owner == record_id:
            errors.append(f"Move preview failed: target already owned by ID {record_id}.")
            continue

        if cross_box:
            errors.append(
                f"Move preview failed: cross-box target occupied at Box {target_box}:{to_pos} by ID {dest_owner}."
            )
            continue

        # Same-box swap
        dest_rec = records_by_id.get(dest_owner)
        if not dest_rec:
            errors.append(f"Move preview failed: swap target ID {dest_owner} missing.")
            continue

        dest_box = _to_int(dest_rec.get("box"), default=0)
        if dest_box != current_box:
            errors.append(f"Move preview failed: swap target ID {dest_owner} is not in the same box.")
            continue

        dest_position = dest_rec.get("position")
        if dest_position != to_pos:
            errors.append(f"Move preview failed: swap target pos {to_pos} does not match {dest_position}.")
            continue

        dest_rec["position"] = from_pos
        rec["position"] = to_pos
        owner[src_loc] = dest_owner
        owner[dst_loc] = record_id

    # Phase 3: takeout (order by action group like executor)
    for action_name in ("takeout",):
        for item in items:
            if str(item.get("action") or "").lower() != action_name:
                continue

            record_id = _to_int(item.get("record_id"), default=0)
            pos = _to_int(item.get("position"), default=0)
            if record_id <= 0 or pos <= 0:
                errors.append(f"Invalid {action_name} preview item (record_id/position).")
                continue

            rec = records_by_id.get(record_id)
            if not rec:
                errors.append(f"{action_name.capitalize()} preview failed: ID {record_id} not found.")
                continue

            current_box = _to_int(rec.get("box"), default=0)
            current_position = rec.get("position")
            if current_position != pos:
                errors.append(
                    f"{action_name.capitalize()} preview failed: ID {record_id} pos {pos} does not match {current_position}."
                )
                continue

            rec["position"] = None
            owner.pop((current_box, pos), None)

    pos_map = {loc: records_by_id[rid] for loc, rid in owner.items() if rid in records_by_id}
    return {
        "ok": not errors,
        "pos_map": pos_map,
        "errors": errors,
        "predicted_new_ids": predicted_new_ids,
    }

