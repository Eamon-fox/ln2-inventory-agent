"""Utilities for normalized takeout/move events."""

from .config import POSITION_RANGE


ACTION_ALIAS = {
    "取出": "takeout",
    "鍙栧嚭": "takeout",
    "移动": "move",
    "绉诲姩": "move",
    "整理": "move",
    "takeout": "takeout",
    "move": "move",
}


ACTION_LABEL = {
    "takeout": "取出",
    "move": "移动",
}


def normalize_action(action):
    """Normalize action to canonical English form.

    Accepts Chinese or English values. Returns ``takeout``/``move``
    or ``None`` for unrecognized input.
    """
    if action is None:
        return None
    raw = str(action).strip()
    return ACTION_ALIAS.get(raw.lower()) or ACTION_ALIAS.get(raw)


def extract_events(rec):
    """Extract structured events from one record."""
    events = []
    thaw_events = rec.get("thaw_events") or []
    for ev in thaw_events:
        action = normalize_action(ev.get("action"))
        if not action:
            continue
        events.append(
            {
                "date": ev.get("date"),
                "action": action,
                "positions": ev.get("positions"),
            }
        )
    return events


def extract_takeout_positions(rec):
    """Extract all positions that have been taken out."""
    taken_out = set()
    thaw_events = rec.get("thaw_events") or []
    for ev in thaw_events:
        action = normalize_action(ev.get("action"))
        # Move/reorg is bookkeeping and should not mark position as depleted.
        if action == "move":
            continue
        pos = ev.get("positions")
        if pos is None:
            continue
        if isinstance(pos, str) and pos.strip().lower() == "all":
            taken_out.update(int(p) for p in (rec.get("positions") or []))
            continue
        if isinstance(pos, int):
            pos = [pos]
        if isinstance(pos, list):
            for p in pos:
                try:
                    p_int = int(p)
                except Exception:
                    continue
                if POSITION_RANGE[0] <= p_int <= POSITION_RANGE[1]:
                    taken_out.add(p_int)
    return taken_out


def is_position_active(rec, pos):
    """Check if a specific position is still active."""
    return pos not in extract_takeout_positions(rec)


def format_positions(positions):
    """Format position list for display."""
    if positions is None:
        return "未知"
    if isinstance(positions, str):
        return positions
    if isinstance(positions, list):
        if not positions:
            return "无"
        return ",".join(str(p) for p in positions)
    return str(positions)
