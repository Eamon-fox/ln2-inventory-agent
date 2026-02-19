"""Unified Operation Plan model: validation and printable rendering."""

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from app_gui.ui.theme import FONT_SIZE_MONO, FONT_SIZE_XS, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XXL

_VALID_ACTIONS = {"takeout", "thaw", "discard", "move", "add", "rollback", "edit"}
_BOX_RANGE = (1, 5)


def _pos_to_coord(pos, cols=9):
    """Return position as-is (pure number format)."""
    return str(pos) if isinstance(pos, int) else str(pos)


def validate_plan_item(item: dict) -> Optional[str]:
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
    if box < 0 or box > _BOX_RANGE[1]:
        return f"box must be between 0 and {_BOX_RANGE[1]}"

    pos = item.get("position")
    if not isinstance(pos, int):
        return "position must be an integer"
    if pos < 1 or pos > 81:
        return "position must be between 1 and 81"

    if action == "move":
        to = item.get("to_position")
        if not isinstance(to, int) or to < 1:
            return "to_position must be a positive integer for move"
        if to == pos:
            return "to_position must differ from position"
        to_box = item.get("to_box")
        if to_box is not None:
            if not isinstance(to_box, int) or to_box < 1:
                return "to_box must be a positive integer"

    if action == "add":
        # No hardcoded required fields; required checks happen at execution time via meta
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


def _get_action_display(action):
    """Get display info for action type."""
    action_map = {
        "takeout": ("TAKEOUT", "#f59e0b", "Take out from tank"),
        "thaw": ("THAW", "#10b981", "Thaw for use"),
        "discard": ("DISCARD", "#ef4444", "Discard sample"),
        "move": ("MOVE", "#3b82f6", "Relocate sample"),
        "add": ("ADD", "#8b5cf6", "Add new sample"),
        "edit": ("EDIT", "#06b6d4", "Edit record fields"),
        "rollback": ("ROLLBACK", "#6b7280", "Restore from backup"),
    }
    return action_map.get(str(action).lower(), (str(action).upper(), "#6b7280", ""))


def _extract_sample_info(item):
    """Extract sample information from item for display."""
    payload = item.get("payload") or {}
    fields = payload.get("fields") or {}
    # Collect all non-empty user field values for labelling
    from lib.custom_fields import STRUCTURAL_FIELD_KEYS
    user_vals = []
    for k, v in fields.items():
        if k not in STRUCTURAL_FIELD_KEYS:
            text = str(v or "").strip()
            if text:
                user_vals.append(text)
    # Fallback to top-level keys on item/payload (legacy compat)
    if not user_vals:
        for src in (item, payload):
            for k in ("cell_line", "short_name"):
                text = str(src.get(k) or "").strip()
                if text and text not in user_vals:
                    user_vals.append(text)
    return {
        "label": " / ".join(user_vals[:2]) if user_vals else "",
        "frozen_at": fields.get("frozen_at") or item.get("frozen_at") or payload.get("frozen_at") or "",
    }


def render_operation_sheet(items):
    """Generate a user-friendly printable HTML operation sheet."""
    if not items:
        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>LN2 Operation Sheet</title>
<style>body { font-family: Arial, sans-serif; margin: 40px; color: #666; }</style>
</head><body><p>No operations to display.</p></body></html>"""

    today = date.today().isoformat()
    
    by_action = defaultdict(list)
    for item in items:
        by_action[item.get("action", "unknown")].append(item)
    
    action_order = ["takeout", "thaw", "move", "discard", "add", "edit", "rollback"]
    
    sections = []
    op_counter = 1
    
    for action in action_order:
        if action not in by_action:
            continue
        
        action_items = by_action[action]
        action_name, action_color, action_desc = _get_action_display(action)
        
        action_rows = []
        for item in sorted(action_items, key=lambda x: (x.get("box", 0), x.get("position", 0))):
            box = item.get("box", 0)
            pos = item.get("position", 0)
            to_pos = item.get("to_position")
            to_box = item.get("to_box")
            
            if action == "move" and to_pos:
                if to_box and to_box != box:
                    pos_display = f"Box{box}:{_pos_to_coord(pos)} &rarr; Box{to_box}:{_pos_to_coord(to_pos)}"
                    warning = '<span class="warning">[CROSS-BOX]</span>'
                else:
                    pos_display = f"Box{box}:{_pos_to_coord(pos)} &rarr; {_pos_to_coord(to_pos)}"
                    warning = ""
            else:
                pos_display = f"Box{box}:{_pos_to_coord(pos)}"
                warning = ""
            
            sample = _extract_sample_info(item)
            rid = item.get("record_id")
            
            sample_label = sample['label'] or item.get("label", "-")
            
            _payload = item.get("payload") or {}
            _fields = _payload.get("fields") or {}
            note = _fields.get("note", "") or _payload.get("note", "") or ""
            
            action_rows.append(f"""
            <tr class="op-row">
                <td class="op-num">{op_counter}</td>
                <td class="chk-cell"><input type="checkbox" id="op{op_counter}"></td>
                <td class="pos-cell">{pos_display} {warning}</td>
                <td class="sample-cell">
                    <div class="sample-name">{sample_label}</div>
                    <div class="sample-meta">ID: {rid if rid else 'NEW'}</div>
                </td>
                <td class="note-cell">{note}</td>
                <td class="confirm-cell">
                    <div class="confirm-line">Time: _______</div>
                    <div class="confirm-line">Init: _______</div>
                </td>
            </tr>""")
            op_counter += 1
        
        sections.append(f"""
        <div class="action-section" style="border-left: 4px solid {action_color};">
            <div class="action-header">
                <span class="action-name" style="background-color: {action_color};">{action_name}</span>
                <span class="action-count">{len(action_items)} operations</span>
                <span class="action-desc">{action_desc}</span>
            </div>
            <table class="op-table">
                <thead>
                    <tr>
                        <th class="col-num">#</th>
                        <th class="col-chk">Done</th>
                        <th class="col-pos">Location</th>
                        <th class="col-sample">Sample</th>
                        <th class="col-note">Notes</th>
                        <th class="col-confirm">Confirmation</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(action_rows)}
                </tbody>
            </table>
        </div>""")
    
    sections_html = "\n".join(sections)
    
    takeout_count = len(by_action.get("takeout", [])) + len(by_action.get("thaw", []))
    move_count = len(by_action.get("move", []))
    add_count = len(by_action.get("add", []))
    discard_count = len(by_action.get("discard", []))
    edit_count = len(by_action.get("edit", []))
    rollback_count = len(by_action.get("rollback", []))
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LN2 Operation Sheet - {today}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            font-size: {FONT_SIZE_SM}px;
            color: #1f2937;
            background: #fff;
        }}
        
        .header {{
            border-bottom: 2px solid #1f2937;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}
        
        .header h1 {{
            margin: 0 0 5px 0;
            font-size: {FONT_SIZE_XXL}px;
        }}
        
        .header-meta {{
            display: flex;
            gap: 30px;
            color: #6b7280;
            font-size: {FONT_SIZE_XS}px;
        }}
        
        .header-meta span {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        
        .summary {{
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
            padding: 10px;
            background: #f9fafb;
            border-radius: 6px;
        }}
        
        .summary-item {{
            padding: 5px 12px;
            border-radius: 4px;
            font-weight: 600;
        }}
        
        .action-section {{
            margin-bottom: 25px;
            padding-left: 10px;
        }}
        
        .action-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            padding: 8px 0;
        }}
        
        .action-name {{
            padding: 4px 12px;
            border-radius: 4px;
            color: white;
            font-weight: bold;
            font-size: {FONT_SIZE_MD}px;
        }}
        
        .action-count {{
            color: #6b7280;
            font-size: {FONT_SIZE_XS}px;
        }}
        
        .action-desc {{
            color: #9ca3af;
            font-size: {FONT_SIZE_MONO}px;
            font-style: italic;
        }}
        
        .op-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 10px;
        }}
        
        .op-table th {{
            background: #f3f4f6;
            padding: 8px;
            text-align: left;
            font-size: {FONT_SIZE_MONO}px;
            text-transform: uppercase;
            color: #6b7280;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        .op-table td {{
            padding: 10px 8px;
            border-bottom: 1px solid #e5e7eb;
            vertical-align: top;
        }}
        
        .op-num {{
            width: 30px;
            font-weight: bold;
            color: #9ca3af;
            text-align: center;
        }}
        
        .chk-cell {{
            width: 40px;
            text-align: center;
        }}
        
        .chk-cell input {{
            width: 16px;
            height: 16px;
        }}
        
        .pos-cell {{
            font-family: 'SF Mono', 'Consolas', monospace;
            font-weight: 600;
            font-size: {FONT_SIZE_MD}px;
            color: #1f2937;
        }}
        
        .warning {{
            color: #ef4444;
            font-weight: bold;
            font-size: {FONT_SIZE_MONO}px;
            margin-left: 5px;
        }}
        
        .sample-name {{
            font-weight: 600;
            color: #1f2937;
        }}
        
        .sample-meta {{
            font-size: {FONT_SIZE_MONO}px;
            color: #6b7280;
            margin-top: 2px;
        }}
        
        .note-cell {{
            color: #6b7280;
            font-size: {FONT_SIZE_XS}px;
            max-width: 150px;
        }}
        
        .confirm-cell {{
            width: 100px;
        }}
        
        .confirm-line {{
            font-size: {FONT_SIZE_MONO}px;
            color: #9ca3af;
            margin: 2px 0;
        }}
        
        .footer {{
            margin-top: 30px;
            padding-top: 15px;
            border-top: 1px solid #e5e7eb;
            font-size: {FONT_SIZE_MONO}px;
            color: #9ca3af;
        }}
        
        .footer-row {{
            display: flex;
            gap: 40px;
            margin-bottom: 10px;
        }}
        
        .sign-box {{
            border-bottom: 1px solid #d1d5db;
            width: 200px;
            display: inline-block;
            margin-left: 5px;
        }}
        
        .tips {{
            background: #fef3c7;
            border: 1px solid #f59e0b;
            border-radius: 4px;
            padding: 10px;
            margin-bottom: 20px;
            font-size: {FONT_SIZE_XS}px;
        }}
        
        .tips-title {{
            font-weight: bold;
            color: #92400e;
            margin-bottom: 5px;
        }}
        
        .tips ul {{
            margin: 0;
            padding-left: 20px;
            color: #78350f;
        }}
        
        .tips li {{
            margin: 2px 0;
        }}
        
        @media print {{
            body {{ padding: 10px; }}
            .action-section {{ page-break-inside: avoid; }}
            .op-table {{ page-break-inside: auto; }}
            .op-row {{ page-break-inside: avoid; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>LN2 Tank Operation Sheet</h1>
        <div class="header-meta">
            <span>Date: <strong>{today}</strong></span>
            <span>Total: <strong>{len(items)} operations</strong></span>
        </div>
    </div>
    
    <div class="summary">
        <div class="summary-item" style="background: #fef3c7;">Takeout/Thaw: {takeout_count}</div>
        <div class="summary-item" style="background: #dbeafe;">Move: {move_count}</div>
        <div class="summary-item" style="background: #ede9fe;">Add: {add_count}</div>
        <div class="summary-item" style="background: #fee2e2;">Discard: {discard_count}</div>
        <div class="summary-item" style="background: #cffafe;">Edit: {edit_count}</div>
        <div class="summary-item" style="background: #f3f4f6;">Rollback: {rollback_count}</div>
    </div>
    
    {sections_html}
    
    <div class="footer">
        <div class="footer-row">
            <span>Completed by: <span class="sign-box"></span></span>
            <span>Verified by: <span class="sign-box"></span></span>
        </div>
        <div class="footer-row">
            <span>Notes: <span class="sign-box" style="width: 400px;"></span></span>
        </div>
    </div>
</body>
</html>"""
