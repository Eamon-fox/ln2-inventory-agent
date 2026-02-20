"""Build printable operation guides from selected audit events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import os

import yaml
from lib.plan_item_factory import normalize_plan_action


_OUT_ACTIONS = {"takeout", "thaw", "discard"}


@dataclass
class _ParsedStep:
    record_id: Optional[int]
    label: str
    action: str
    source_loc: Optional[Tuple[int, int]]
    target_loc: Optional[Tuple[int, int]]
    timestamp: str


@dataclass
class _Flow:
    record_id: Optional[int]
    label: str
    start_loc: Optional[Tuple[int, int]]
    end_loc: Optional[Tuple[int, int]]
    last_action: str


def build_operation_guide_from_audit_events(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a net operation guide from selected audit events.

    Returns a dict with keys:
    - items: flattened operation sheet items
    - warnings: non-fatal parsing or integrity warnings
    - stats: counts for selected events, parsed steps, and final items
    """
    ordered_events = sorted(list(events or []), key=lambda ev: str(ev.get("timestamp", "")))
    warnings: List[str] = []
    snapshot_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}
    steps: List[_ParsedStep] = []
    skipped_events = 0

    for event in ordered_events:
        event_steps, skipped = _extract_steps_from_event(event, snapshot_cache, warnings)
        if skipped:
            skipped_events += 1
        steps.extend(event_steps)

    items = _collapse_steps_to_items(steps, warnings)
    _add_target_conflict_warnings(items, warnings)
    _add_cycle_warnings(items, warnings)

    return {
        "items": items,
        "warnings": warnings,
        "stats": {
            "selected_events": len(ordered_events),
            "skipped_events": skipped_events,
            "parsed_steps": len(steps),
            "final_items": len(items),
        },
    }


def _extract_steps_from_event(
    event: Dict[str, Any],
    snapshot_cache: Dict[str, Dict[int, Dict[str, Any]]],
    warnings: List[str],
) -> Tuple[List[_ParsedStep], bool]:
    status = str(event.get("status", "")).lower()
    action = str(event.get("action", "")).strip()
    timestamp = str(event.get("timestamp", ""))

    if status != "success":
        warnings.append(f"{timestamp} {action}: skipped because status={status or 'unknown'}")
        return [], True

    if action == "rollback":
        warnings.append(f"{timestamp} rollback: skipped (guide builder ignores rollback events)")
        return [], True

    lookup = _load_snapshot_lookup(event.get("backup_path"), snapshot_cache, warnings)
    if action == "record_thaw":
        return _parse_record_thaw(event, lookup, warnings), False
    if action == "batch_thaw":
        return _parse_batch_thaw(event, lookup, warnings), False
    if action == "add_entry":
        return _parse_add_entry(event, lookup, warnings), False

    warnings.append(f"{timestamp} {action}: skipped (unsupported action)")
    return [], True


def _parse_record_thaw(
    event: Dict[str, Any],
    lookup: Dict[int, Dict[str, Any]],
    warnings: List[str],
) -> List[_ParsedStep]:
    tool_input = dict(event.get("tool_input") or {})
    details = dict(event.get("details") or {})
    timestamp = str(event.get("timestamp", ""))

    record_id = _as_int(tool_input.get("record_id"))
    if record_id is None:
        record_id = _as_int(details.get("record_id"))
    if record_id is None:
        warnings.append(f"{timestamp} record_thaw: missing record_id, skipped")
        return []

    action = _normalize_action(details.get("action") or tool_input.get("action") or "takeout")
    src_pos = _as_int(tool_input.get("position"))
    if src_pos is None:
        src_pos = _as_int(details.get("position"))
    if src_pos is None:
        warnings.append(f"{timestamp} record_thaw#{record_id}: missing position, skipped")
        return []

    src_box = _as_int(details.get("box"))
    if src_box is None:
        src_box = _lookup_box(lookup, record_id)
    if src_box is None:
        src_box = 0
        warnings.append(f"{timestamp} record_thaw#{record_id}: unknown source box, using 0")

    target_loc: Optional[Tuple[int, int]] = None
    if action == "move":
        dst_pos = _as_int(tool_input.get("to_position"))
        if dst_pos is None:
            dst_pos = _as_int(details.get("to_position"))
        if dst_pos is None:
            warnings.append(f"{timestamp} record_thaw#{record_id}: move missing to_position, skipped")
            return []

        dst_box = _as_int(tool_input.get("to_box"))
        if dst_box is None:
            dst_box = _as_int(details.get("to_box"))
        if dst_box is None:
            dst_box = src_box
        target_loc = (dst_box, dst_pos)

    label = _lookup_label(lookup, record_id) or f"ID {record_id}"
    return [
        _ParsedStep(
            record_id=record_id,
            label=label,
            action=action,
            source_loc=(src_box, src_pos),
            target_loc=target_loc,
            timestamp=timestamp,
        )
    ]


def _parse_batch_thaw(
    event: Dict[str, Any],
    lookup: Dict[int, Dict[str, Any]],
    warnings: List[str],
) -> List[_ParsedStep]:
    tool_input = dict(event.get("tool_input") or {})
    details = dict(event.get("details") or {})
    timestamp = str(event.get("timestamp", ""))
    action = _normalize_action(details.get("action") or tool_input.get("action") or "takeout")

    entries = tool_input.get("entries")
    if isinstance(entries, str):
        warnings.append(f"{timestamp} batch_thaw: string entries are unsupported here, skipped")
        return []
    if not isinstance(entries, list):
        warnings.append(f"{timestamp} batch_thaw: missing entries, skipped")
        return []

    steps: List[_ParsedStep] = []
    for idx, entry in enumerate(entries, 1):
        parsed = _parse_batch_entry(entry)
        if parsed is None:
            warnings.append(f"{timestamp} batch_thaw: invalid entry #{idx}, skipped")
            continue
        record_id, src_pos, dst_pos, dst_box_hint, src_box_hint = parsed

        src_box = src_box_hint
        if src_box is None:
            src_box = _lookup_box(lookup, record_id)
        if src_box is None:
            src_box = 0
            warnings.append(f"{timestamp} batch_thaw#{record_id}: unknown source box, using 0")

        target_loc: Optional[Tuple[int, int]] = None
        if action == "move":
            if dst_pos is None:
                warnings.append(f"{timestamp} batch_thaw#{record_id}: move missing to_position, skipped")
                continue
            dst_box = dst_box_hint if dst_box_hint is not None else src_box
            target_loc = (dst_box, dst_pos)

        label = _lookup_label(lookup, record_id) or f"ID {record_id}"
        steps.append(
            _ParsedStep(
                record_id=record_id,
                label=label,
                action=action,
                source_loc=(src_box, src_pos),
                target_loc=target_loc,
                timestamp=timestamp,
            )
        )

    return steps


def _parse_add_entry(
    event: Dict[str, Any],
    _lookup: Dict[int, Dict[str, Any]],
    warnings: List[str],
) -> List[_ParsedStep]:
    tool_input = dict(event.get("tool_input") or {})
    details = dict(event.get("details") or {})
    timestamp = str(event.get("timestamp", ""))

    box = _as_int(tool_input.get("box"))
    if box is None:
        box = _as_int(details.get("box"))
    if box is None:
        warnings.append(f"{timestamp} add_entry: missing box, skipped")
        return []

    raw_positions = tool_input.get("positions")
    positions: List[int] = []
    if isinstance(raw_positions, list):
        for p in raw_positions:
            pv = _as_int(p)
            if pv is not None:
                positions.append(pv)
    if not positions:
        details_positions = details.get("positions")
        if isinstance(details_positions, list):
            for p in details_positions:
                pv = _as_int(p)
                if pv is not None:
                    positions.append(pv)
    # Also check for single position field
    if not positions:
        single_pos = tool_input.get("position") or details.get("position")
        pv = _as_int(single_pos)
        if pv is not None:
            positions.append(pv)
    if not positions:
        warnings.append(f"{timestamp} add_entry: missing positions, skipped")
        return []

    record_id = _as_int(details.get("new_id"))
    record_ids = []
    raw_new_ids = details.get("new_ids")
    if isinstance(raw_new_ids, list):
        for item in raw_new_ids:
            rid = _as_int(item)
            if rid is not None:
                record_ids.append(rid)
    # Extract label from fields dict (new format) or top-level keys (legacy)
    input_fields = tool_input.get("fields") or {}
    detail_fields = details.get("fields") or {}
    label = (
        str(input_fields.get("short_name") or tool_input.get("short_name") or "").strip()
        or str(detail_fields.get("short_name") or details.get("short_name") or "").strip()
        or (f"ID {record_id}" if record_id is not None else "new")
    )

    steps = []
    sorted_positions = sorted(set(positions))
    if record_ids and len(record_ids) == len(sorted_positions):
        for rid, position in zip(record_ids, sorted_positions):
            steps.append(
                _ParsedStep(
                    record_id=rid,
                    label=label,
                    action="add",
                    source_loc=None,
                    target_loc=(box, position),
                    timestamp=timestamp,
                )
            )
    else:
        for position in sorted_positions:
            steps.append(
                _ParsedStep(
                    record_id=record_id,
                    label=label,
                    action="add",
                    source_loc=None,
                    target_loc=(box, position),
                    timestamp=timestamp,
                )
            )
    return steps


def _parse_batch_entry(entry: Any) -> Optional[Tuple[int, int, Optional[int], Optional[int], Optional[int]]]:
    """Return (record_id, src_pos, dst_pos, dst_box, src_box) from one batch entry."""
    if isinstance(entry, (list, tuple)):
        if len(entry) >= 4:
            rid = _as_int(entry[0])
            src_pos = _as_int(entry[1])
            dst_pos = _as_int(entry[2])
            dst_box = _as_int(entry[3])
            if rid is None or src_pos is None:
                return None
            return rid, src_pos, dst_pos, dst_box, None
        if len(entry) == 3:
            rid = _as_int(entry[0])
            src_pos = _as_int(entry[1])
            dst_pos = _as_int(entry[2])
            if rid is None or src_pos is None:
                return None
            return rid, src_pos, dst_pos, None, None
        if len(entry) == 2:
            rid = _as_int(entry[0])
            src_pos = _as_int(entry[1])
            if rid is None or src_pos is None:
                return None
            return rid, src_pos, None, None, None
        return None

    if isinstance(entry, dict):
        rid = _as_int(entry.get("record_id"))
        if rid is None:
            rid = _as_int(entry.get("id"))
        src_pos = _as_int(entry.get("position"))
        if src_pos is None:
            src_pos = _as_int(entry.get("from_position"))
        dst_pos = _as_int(entry.get("to_position"))
        dst_box = _as_int(entry.get("to_box"))
        src_box = _as_int(entry.get("box"))
        if rid is None or src_pos is None:
            return None
        return rid, src_pos, dst_pos, dst_box, src_box

    return None


def _collapse_steps_to_items(steps: List[_ParsedStep], warnings: List[str]) -> List[Dict[str, Any]]:
    flows: List[_Flow] = []

    for step in sorted(steps, key=lambda s: s.timestamp):
        if step.action == "add":
            flows.append(
                _Flow(
                    record_id=step.record_id,
                    label=step.label,
                    start_loc=None,
                    end_loc=step.target_loc,
                    last_action="add",
                )
            )
            continue

        if step.source_loc is None:
            warnings.append(f"{step.timestamp} {step.action}: missing source location, skipped")
            continue

        flow_idx = _find_flow_for_step(flows, step.record_id, step.source_loc)
        if flow_idx is None:
            flows.append(
                _Flow(
                    record_id=step.record_id,
                    label=step.label,
                    start_loc=step.source_loc,
                    end_loc=step.source_loc,
                    last_action=step.action,
                )
            )
            flow_idx = len(flows) - 1

        flow = flows[flow_idx]
        if (flow.label.startswith("ID ") or flow.label == "-") and step.label:
            flow.label = step.label
        flow.end_loc = step.target_loc
        flow.last_action = step.action

    items: List[Dict[str, Any]] = []
    for flow in flows:
        item = _flow_to_item(flow)
        if item is not None:
            items.append(item)

    action_order = {"takeout": 0, "thaw": 0, "discard": 0, "move": 1, "add": 2}
    items.sort(
        key=lambda it: (
            action_order.get(str(it.get("action", "")), 9),
            int(it.get("box", 0) or 0),
            int(it.get("position", 0) or 0),
            int(it.get("record_id", 0) or 0),
        )
    )
    return items


def _find_flow_for_step(
    flows: List[_Flow],
    record_id: Optional[int],
    source_loc: Tuple[int, int],
) -> Optional[int]:
    for idx in range(len(flows) - 1, -1, -1):
        flow = flows[idx]
        if flow.record_id != record_id:
            continue
        if flow.end_loc == source_loc:
            return idx
    return None


def _flow_to_item(flow: _Flow) -> Optional[Dict[str, Any]]:
    label = flow.label or (f"ID {flow.record_id}" if flow.record_id is not None else "-")

    if flow.start_loc is None and flow.end_loc is None:
        return None

    if flow.start_loc is None and flow.end_loc is not None:
        box, position = flow.end_loc
        item = {
            "action": "add",
            "source": "audit",
            "box": int(box),
            "position": int(position),
            "record_id": flow.record_id,
            "label": label,
            "payload": {},
        }
        return item

    if flow.start_loc is not None and flow.end_loc is None:
        box, position = flow.start_loc
        action = flow.last_action if flow.last_action in _OUT_ACTIONS else "takeout"
        item = {
            "action": action,
            "source": "audit",
            "box": int(box),
            "position": int(position),
            "record_id": flow.record_id,
            "label": label,
            "payload": {},
        }
        return item

    if flow.start_loc is not None and flow.end_loc is not None:
        src_box, src_pos = flow.start_loc
        dst_box, dst_pos = flow.end_loc
        if src_box == dst_box and src_pos == dst_pos:
            return None

        item = {
            "action": "move",
            "source": "audit",
            "box": int(src_box),
            "position": int(src_pos),
            "to_position": int(dst_pos),
            "record_id": flow.record_id,
            "label": label,
            "payload": {},
        }
        if dst_box != src_box:
            item["to_box"] = int(dst_box)
        return item

    return None


def _add_target_conflict_warnings(items: List[Dict[str, Any]], warnings: List[str]) -> None:
    target_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for item in items:
        action = str(item.get("action", "")).lower()
        if action == "move":
            t_box = int(item.get("to_box", item.get("box", 0)) or 0)
            t_pos = int(item.get("to_position", 0) or 0)
        elif action == "add":
            t_box = int(item.get("box", 0) or 0)
            t_pos = int(item.get("position", 0) or 0)
        else:
            continue

        key = (t_box, t_pos)
        if key in target_map:
            warnings.append(
                f"Target conflict detected at Box {t_box}:{t_pos} between IDs "
                f"{target_map[key].get('record_id')} and {item.get('record_id')}"
            )
        else:
            target_map[key] = item


def _add_cycle_warnings(items: List[Dict[str, Any]], warnings: List[str]) -> None:
    graph: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for item in items:
        if str(item.get("action", "")).lower() != "move":
            continue
        src = (int(item.get("box", 0) or 0), int(item.get("position", 0) or 0))
        dst = (
            int(item.get("to_box", item.get("box", 0)) or 0),
            int(item.get("to_position", 0) or 0),
        )
        if src != dst and src not in graph:
            graph[src] = dst

    visited: Dict[Tuple[int, int], int] = {}
    in_stack: Dict[Tuple[int, int], bool] = {}

    def dfs(node: Tuple[int, int]) -> bool:
        visited[node] = 1
        in_stack[node] = True
        nxt = graph.get(node)
        if nxt is not None:
            if nxt not in visited:
                if dfs(nxt):
                    return True
            elif in_stack.get(nxt):
                return True
        in_stack[node] = False
        return False

    for node in list(graph.keys()):
        if node not in visited and dfs(node):
            warnings.append(
                "Move cycle detected in selected events. Use a temporary empty slot when executing the printed guide."
            )
            return


def _normalize_action(value: Any) -> str:
    return normalize_plan_action(value)


def _load_snapshot_lookup(
    backup_path: Any,
    cache: Dict[str, Dict[int, Dict[str, Any]]],
    warnings: List[str],
) -> Dict[int, Dict[str, Any]]:
    path = str(backup_path or "").strip()
    if not path:
        return {}
    if path in cache:
        return cache[path]

    if not os.path.isfile(path):
        warnings.append(f"Snapshot not found: {path}")
        cache[path] = {}
        return cache[path]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        records = data.get("inventory") if isinstance(data, dict) else None
        lookup: Dict[int, Dict[str, Any]] = {}
        if isinstance(records, list):
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                rid = _as_int(rec.get("id"))
                if rid is None:
                    continue
                lookup[rid] = rec
        cache[path] = lookup
        return lookup
    except Exception as exc:  # pragma: no cover - defensive branch
        warnings.append(f"Failed to read snapshot {path}: {exc}")
        cache[path] = {}
        return cache[path]


def _lookup_box(lookup: Dict[int, Dict[str, Any]], record_id: int) -> Optional[int]:
    record = lookup.get(record_id)
    if not isinstance(record, dict):
        return None
    return _as_int(record.get("box"))


def _lookup_label(lookup: Dict[int, Dict[str, Any]], record_id: int) -> Optional[str]:
    from lib.custom_fields import STRUCTURAL_FIELD_KEYS
    record = lookup.get(record_id)
    if not isinstance(record, dict):
        return None
    # Try all non-structural keys; prefer short_name then cell_line for
    # backwards compat, then fall back to any non-empty user field value.
    for key in ("short_name", "cell_line"):
        val = str(record.get(key) or "").strip()
        if val:
            return val
    for key, val in record.items():
        if key in STRUCTURAL_FIELD_KEYS:
            continue
        text = str(val or "").strip()
        if text:
            return text
    return None


def _as_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
