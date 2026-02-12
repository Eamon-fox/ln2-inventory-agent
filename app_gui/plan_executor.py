"""Unified Plan execution engine with preflight validation."""

from __future__ import annotations

import copy
import os
import tempfile
from datetime import date
from typing import Dict, List, Optional, Tuple

from lib.yaml_ops import load_yaml, write_yaml


def _analyze_move_plan(items: List[Dict[str, object]]) -> Dict[str, object]:
    """Analyze move operations for swap/cycle detection."""
    move_graph: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    reverse_graph: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}

    for item in items:
        if item.get("action") != "move":
            continue
        from_box = int(item.get("box", 0) or 0)
        from_pos = int(item.get("position", 0) or 0)
        to_box = int(item.get("to_box", from_box) or from_box)
        to_pos = int(item.get("to_position", 0) or 0)
        record_id = int(item.get("record_id", 0) or 0)

        src = (from_box, from_pos)
        dst = (to_box, to_pos)
        move_graph[src] = (to_box, to_pos, record_id)

        if dst not in reverse_graph:
            reverse_graph[dst] = []
        reverse_graph[dst].append((from_box, from_pos, record_id))

    visited = set()
    cycles = []

    def find_cycle(start: Tuple[int, int], path: List[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
        current = path[-1] if path else start
        if current in visited:
            if current == start and len(path) > 1:
                return path
            return None

        visited.add(current)
        nxt = move_graph.get(current)
        if nxt is None:
            return None
        nxt_loc = (nxt[0], nxt[1])
        if nxt_loc in path:
            idx = path.index(nxt_loc)
            return path[idx:] + [nxt_loc]
        return find_cycle(start, path + [nxt_loc])

    for src in list(move_graph.keys()):
        if src in visited:
            continue
        visited.clear()
        cycle = find_cycle(src, [src])
        if cycle:
            cycles.append(cycle)

    simple_swaps = []
    for cycle in cycles:
        if len(cycle) == 3:
            a, b = cycle[0], cycle[1]
            if move_graph.get(a) and move_graph.get(b):
                if (move_graph[a][0], move_graph[a][1]) == b and (move_graph[b][0], move_graph[b][1]) == a:
                    simple_swaps.append((a, b))

    has_cycle = len(cycles) > 0
    is_swap = all(len(c) == 3 for c in cycles) if cycles else True
    can_execute_directly = not has_cycle or is_swap

    return {
        "is_swap": is_swap,
        "has_cycle": has_cycle,
        "move_graph": move_graph,
        "reverse_graph": reverse_graph,
        "can_execute_directly": can_execute_directly,
        "cycles": cycles,
        "simple_swaps": simple_swaps,
    }


def _validate_moves_holistically(items: List[Dict[str, object]], records: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Validate move operations as a whole, supporting swap semantics."""
    errors = []
    analysis = _analyze_move_plan(items)
    move_graph = analysis["move_graph"]
    reverse_graph = analysis["reverse_graph"]

    pos_map: Dict[Tuple[int, int], Dict[str, object]] = {}
    for rec in records:
        box = rec.get("box")
        if box is None:
            continue
        for pos in rec.get("positions") or []:
            pos_map[(int(box), int(pos))] = rec

    for item in items:
        if item.get("action") != "move":
            continue
        from_box = int(item.get("box", 0) or 0)
        from_pos = int(item.get("position", 0) or 0)
        record_id = int(item.get("record_id", 0) or 0)

        src = (from_box, from_pos)
        rec_at_src = pos_map.get(src)

        if rec_at_src is None:
            errors.append({
                "item": item,
                "error_code": "source_empty",
                "message": f"No record at source position Box {from_box}:{from_pos}",
            })
        elif int(rec_at_src.get("id", 0)) != record_id:
            errors.append({
                "item": item,
                "error_code": "source_mismatch",
                "message": f"Record ID mismatch at Box {from_box}:{from_pos}: expected {record_id}, found {rec_at_src.get('id')}",
            })

    for item in items:
        if item.get("action") != "move":
            continue
        to_box = int(item.get("to_box", item.get("box", 0)) or 0)
        to_pos = int(item.get("to_position", 0) or 0)
        dst = (to_box, to_pos)

        if dst in pos_map:
            existing = pos_map[dst]
            existing_id = int(existing.get("id", 0))

            is_being_moved_away = dst in move_graph

            if not is_being_moved_away:
                errors.append({
                    "item": item,
                    "error_code": "target_occupied",
                    "message": f"Target position Box {to_box}:{to_pos} is occupied by ID {existing.get('id')} and not part of swap",
                })

    return errors


def _make_error_item(item: Dict[str, object], error_code: str, message: str) -> Dict[str, object]:
    """Create an error report for a plan item."""
    return {
        "item": item,
        "ok": False,
        "blocked": True,
        "error_code": error_code,
        "message": message,
    }


def _make_ok_item(item: Dict[str, object], response: Dict[str, object]) -> Dict[str, object]:
    """Create a success report for a plan item."""
    return {
        "item": item,
        "ok": True,
        "blocked": False,
        "response": response,
    }


def preflight_plan(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: Optional[str] = None,
) -> Dict[str, object]:
    """Run plan validation without modifying real data.

    Creates a temporary copy of the YAML and executes the plan against it.
    Returns a report with per-item validation status.
    """
    if not items:
        return {
            "ok": True,
            "blocked": False,
            "items": [],
            "stats": {"total": 0, "ok": 0, "blocked": 0},
            "summary": "No items to validate.",
        }

    if not os.path.isfile(yaml_path):
        return {
            "ok": False,
            "blocked": True,
            "items": [_make_error_item(it, "yaml_not_found", f"YAML file not found: {yaml_path}") for it in items],
            "stats": {"total": len(items), "ok": 0, "blocked": len(items)},
            "summary": f"YAML file not found: {yaml_path}",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "blocked": True,
            "items": [_make_error_item(it, "yaml_load_failed", str(exc)) for it in items],
            "stats": {"total": len(items), "ok": 0, "blocked": len(items)},
            "summary": f"Failed to load YAML: {exc}",
        }

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp_path = tmp.name
        write_yaml(data, tmp_path, auto_html=False, auto_server=False, auto_backup=False, audit_meta={"action": "preflight", "source": "plan_executor"})

    try:
        result = run_plan(
            yaml_path=tmp_path,
            items=items,
            bridge=bridge,
            date_str=date_str,
            mode="preflight",
        )
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def run_plan(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: Optional[str] = None,
    mode: str = "execute",
) -> Dict[str, object]:
    """Execute or validate a plan against a YAML file.

    Args:
        yaml_path: Path to the inventory YAML file.
        items: List of plan items (each with action, box, position, record_id, payload, etc.).
        bridge: GuiToolBridge instance for executing operations.
        date_str: Optional date string for operations.
        mode: "execute" for real execution, "preflight" for validation-only.

    Returns:
        Dict with keys:
        - ok: overall success
        - blocked: whether any item was blocked
        - items: per-item reports
        - stats: summary counts
        - summary: human-readable summary
        - backup_path: backup path if any writes occurred (execute mode only)
    """
    if not items:
        return {
            "ok": True,
            "blocked": False,
            "items": [],
            "stats": {"total": 0, "ok": 0, "blocked": 0},
            "summary": "No items to process.",
            "backup_path": None,
        }

    if mode not in ("execute", "preflight"):
        mode = "execute"

    effective_date = date_str or date.today().isoformat()
    reports: List[Dict[str, object]] = []
    last_backup: Optional[str] = None

    remaining = list(items)

    # Phase 1: add operations (each add is independent)
    adds = [it for it in remaining if it.get("action") == "add"]
    for item in adds:
        payload = dict(item.get("payload") or {})
        if mode == "preflight":
            response = _preflight_add_entry(bridge, yaml_path, payload)
        else:
            response = bridge.add_entry(yaml_path=yaml_path, **payload)

        if response.get("ok"):
            reports.append(_make_ok_item(item, response))
            remaining.remove(item)
            if response.get("backup_path"):
                last_backup = response["backup_path"]
        else:
            reports.append(_make_error_item(item, response.get("error_code", "add_failed"), response.get("message", "Add failed")))

    # Phase 2: move operations (holistic validation, batch first, fallback to individual)
    moves = [it for it in remaining if it.get("action") == "move"]
    if moves:
        try:
            if os.path.isfile(yaml_path):
                data = load_yaml(yaml_path)
                records = data.get("inventory", []) if isinstance(data, dict) else []
            else:
                records = []
        except Exception:
            records = []

        move_errors = _validate_moves_holistically(moves, records) if records else []
        error_by_item = {id(e["item"]): e for e in move_errors}

        for item in moves:
            err = error_by_item.get(id(item))
            if err:
                reports.append(_make_error_item(item, err["error_code"], err["message"]))
                continue

        valid_moves = [it for it in moves if id(it) not in error_by_item]

        if valid_moves:
            batch_ok, batch_reports = _execute_moves_batch_then_fallback(
                yaml_path=yaml_path,
                items=valid_moves,
                bridge=bridge,
                date_str=effective_date,
                mode=mode,
                skip_target_check=bool(records),
            )
            reports.extend(batch_reports)
            for r in batch_reports:
                if r.get("ok") and r.get("item") in remaining:
                    remaining.remove(r["item"])
                    if r.get("response", {}).get("backup_path"):
                        last_backup = r["response"]["backup_path"]

    # Phase 3: takeout/thaw/discard operations (batch first, fallback to individual)
    for action_name in ("Takeout", "Thaw", "Discard"):
        action_items = [it for it in remaining if it.get("action") == action_name.lower()]
        if not action_items:
            continue

        batch_ok, batch_reports = _execute_thaw_batch_then_fallback(
            yaml_path=yaml_path,
            items=action_items,
            action_name=action_name,
            bridge=bridge,
            date_str=effective_date,
            mode=mode,
        )
        reports.extend(batch_reports)
        for r in batch_reports:
            if r.get("ok") and r.get("item") in remaining:
                remaining.remove(r["item"])
                if r.get("response", {}).get("backup_path"):
                    last_backup = r["response"]["backup_path"]

    # Finalize
    ok_count = sum(1 for r in reports if r.get("ok"))
    blocked_count = sum(1 for r in reports if r.get("blocked"))
    has_blocked = blocked_count > 0

    if has_blocked:
        summary = f"Blocked: {blocked_count}/{len(reports)} items cannot execute."
    elif ok_count == len(reports):
        summary = f"All {ok_count} operation(s) succeeded."
    else:
        summary = f"Completed: {ok_count} ok, {blocked_count} blocked, {len(remaining)} remaining."

    return {
        "ok": not has_blocked,
        "blocked": has_blocked,
        "items": reports,
        "stats": {"total": len(reports), "ok": ok_count, "blocked": blocked_count, "remaining": len(remaining)},
        "summary": summary,
        "backup_path": last_backup,
        "remaining_items": remaining,
    }


def _run_dry_tool(
    bridge: object,
    yaml_path: str,
    tool_name: str,
    **payload: object,
) -> Dict[str, object]:
    """Invoke a lib.tool_api tool in dry-run mode with shared metadata."""
    try:
        from lib import tool_api
    except ImportError:
        return {"ok": False, "error_code": "import_error", "message": "Failed to import tool_api"}

    tool_fn = getattr(tool_api, tool_name, None)
    build_actor_context = getattr(tool_api, "build_actor_context", None)
    if not callable(tool_fn) or not callable(build_actor_context):
        return {"ok": False, "error_code": "import_error", "message": f"Failed to resolve {tool_name}"}

    actor_context = getattr(bridge, "_ctx", lambda: None)() or build_actor_context(actor_type="human", channel="gui")

    return tool_fn(
        yaml_path=yaml_path,
        dry_run=True,
        actor_context=actor_context,
        source="plan_executor",
        auto_html=False,
        auto_server=False,
        auto_backup=False,
        **payload,
    )


def _preflight_add_entry(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate add_entry without writing (using dry_run semantics)."""
    return _run_dry_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_add_entry",
        parent_cell_line=payload.get("parent_cell_line"),
        short_name=payload.get("short_name"),
        box=payload.get("box"),
        positions=payload.get("positions"),
        frozen_at=payload.get("frozen_at"),
        plasmid_name=payload.get("plasmid_name"),
        plasmid_id=payload.get("plasmid_id"),
        note=payload.get("note"),
    )


def _preflight_record_thaw(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate record_thaw without writing (using dry_run semantics)."""
    return _run_dry_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_record_thaw",
        record_id=payload.get("record_id"),
        position=payload.get("position"),
        to_position=payload.get("to_position"),
        to_box=payload.get("to_box"),
        date_str=payload.get("date_str"),
        action=payload.get("action", "Takeout"),
        note=payload.get("note"),
    )

def _preflight_batch_thaw(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate batch_thaw without writing (using dry_run semantics)."""
    return _run_dry_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_batch_thaw",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
        action=payload.get("action", "Takeout"),
        note=payload.get("note"),
    )


def _execute_moves_batch_then_fallback(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: str,
    mode: str,
    skip_target_check: bool = False,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute move operations: batch first, fallback to individual on failure."""
    reports: List[Dict[str, object]] = []

    entries = []
    for item in items:
        p = item.get("payload") or {}
        entry = (p.get("record_id"), p.get("position"), p.get("to_position"))
        if p.get("to_box") is not None:
            entry = entry + (p.get("to_box"),)
        entries.append(entry)

    first_item = items[0] if items else {}
    first_payload = first_item.get("payload") or {}
    batch_payload = {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
        "action": "Move",
        "note": first_payload.get("note"),
    }

    if mode == "preflight":
        if skip_target_check:
            response = {"ok": True, "message": "Preflight passed (holistic validation)"}
        else:
            response = _preflight_batch_thaw(bridge, yaml_path, batch_payload)
    else:
        response = bridge.batch_thaw(yaml_path=yaml_path, **batch_payload)

    if response.get("ok"):
        for item in items:
            reports.append(_make_ok_item(item, response))
        return True, reports

    # Batch failed - try each individually
    all_ok = True
    for item in items:
        p = item.get("payload") or {}
        single_payload = {
            "record_id": p.get("record_id"),
            "position": p.get("position"),
            "to_position": p.get("to_position"),
            "to_box": p.get("to_box"),
            "date_str": p.get("date_str", date_str),
            "action": "Move",
            "note": p.get("note"),
        }

        if mode == "preflight":
            single = _preflight_record_thaw(bridge, yaml_path, single_payload)
        else:
            single = bridge.record_thaw(yaml_path=yaml_path, **single_payload)

        if single.get("ok"):
            reports.append(_make_ok_item(item, single))
        else:
            reports.append(_make_error_item(item, single.get("error_code", "move_failed"), single.get("message", "Move failed")))
            all_ok = False

    return all_ok, reports


def _execute_thaw_batch_then_fallback(
    yaml_path: str,
    items: List[Dict[str, object]],
    action_name: str,
    bridge: object,
    date_str: str,
    mode: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute takeout/thaw/discard operations: batch first, fallback to individual on failure."""
    reports: List[Dict[str, object]] = []

    entries = []
    for item in items:
        p = item.get("payload") or {}
        entries.append((p.get("record_id"), p.get("position")))

    first_item = items[0] if items else {}
    first_payload = first_item.get("payload") or {}
    batch_payload = {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
        "action": action_name,
        "note": first_payload.get("note"),
    }

    if mode == "preflight":
        response = _preflight_batch_thaw(bridge, yaml_path, batch_payload)
    else:
        response = bridge.batch_thaw(yaml_path=yaml_path, **batch_payload)

    if response.get("ok"):
        for item in items:
            reports.append(_make_ok_item(item, response))
        return True, reports

    # Batch failed - try each individually
    all_ok = True
    for item in items:
        p = item.get("payload") or {}
        single_payload = {
            "record_id": p.get("record_id"),
            "position": p.get("position"),
            "date_str": p.get("date_str", date_str),
            "action": action_name,
            "note": p.get("note"),
        }

        if mode == "preflight":
            single = _preflight_record_thaw(bridge, yaml_path, single_payload)
        else:
            single = bridge.record_thaw(yaml_path=yaml_path, **single_payload)

        if single.get("ok"):
            reports.append(_make_ok_item(item, single))
        else:
            reports.append(_make_error_item(item, single.get("error_code", "thaw_failed"), single.get("message", "Operation failed")))
            all_ok = False

    return all_ok, reports
