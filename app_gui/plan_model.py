"""Unified Operation Plan model: validation and printable rendering."""

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from app_gui.ui.theme import FONT_SIZE_MONO, FONT_SIZE_XS, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_XXL

_VALID_ACTIONS = {"takeout", "thaw", "discard", "move", "add", "rollback", "edit"}


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
        if to == pos:
            return "to_position must differ from position"
        to_box = item.get("to_box")
        if to_box is not None:
            if not isinstance(to_box, int) or to_box < 1:
                return "to_box must be a positive integer"

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


def extract_grid_state_for_print(overview_panel):
    """Extract current grid state from overview panel for print view.

    Args:
        overview_panel: OverviewPanel instance

    Returns:
        Dict with grid state data
    """
    from lib.custom_fields import get_display_key, get_color_key, get_color_key_options
    from app_gui.ui.utils import cell_color, build_color_palette
    from lib.position_fmt import pos_to_display, box_to_display

    rows, cols, box_numbers = overview_panel.overview_shape
    meta = overview_panel._current_meta
    layout = overview_panel._current_layout

    # Build color palette
    color_options = get_color_key_options(meta)
    build_color_palette(color_options)

    display_key = get_display_key(meta)
    color_key = get_color_key(meta)

    boxes_data = []
    for box_num in box_numbers:
        cells_data = []
        for position in range(1, rows * cols + 1):
            key = (box_num, position)
            record = overview_panel.overview_pos_map.get(key)

            cell = {
                "box": box_num,
                "position": position,
                "display_pos": pos_to_display(position, layout),
                "is_occupied": record is not None,
            }

            if record:
                label_val = str(record.get(display_key) or "")
                color_val = str(record.get(color_key) or "")
                cell.update({
                    "id": record.get("id"),
                    "label": label_val[:8] if label_val else str(position),
                    "color": cell_color(color_val if color_val else None),
                })

            cells_data.append(cell)

        boxes_data.append({
            "box_number": box_num,
            "box_label": box_to_display(box_num, layout),
            "cells": cells_data,
        })

    return {
        "rows": rows,
        "cols": cols,
        "boxes": boxes_data,
        "theme": "dark",
    }


def apply_operation_markers_to_grid(grid_state, plan_items):
    """Add operation markers to grid state based on plan items.

    Args:
        grid_state: Dict from extract_grid_state_for_print
        plan_items: List of plan items

    Returns:
        Modified grid_state with operation markers
    """
    markers = {}
    move_counter = 1

    for item in plan_items:
        action = item.get("action", "").lower()
        box = item.get("box")
        position = item.get("position")

        if action == "add" and box and position:
            markers[(box, position)] = {"type": "add"}

        elif action in ("takeout", "thaw", "discard") and box and position:
            markers[(box, position)] = {"type": "takeout"}

        elif action == "move" and box and position:
            move_id = move_counter
            move_counter += 1

            markers[(box, position)] = {"type": "move-source", "move_id": move_id}

            to_box = item.get("to_box") or box
            to_pos = item.get("to_position")
            if to_pos:
                markers[(to_box, to_pos)] = {"type": "move-target", "move_id": move_id}

    for box_data in grid_state["boxes"]:
        for cell in box_data["cells"]:
            key = (cell["box"], cell["position"])
            if key in markers:
                marker = markers[key]
                cell["operation_marker"] = marker["type"]
                if "move_id" in marker:
                    cell["move_id"] = marker["move_id"]

    return grid_state


def render_grid_html(grid_state):
    """Render grid visualization HTML from grid state.

    Args:
        grid_state: Dict with grid state data

    Returns:
        HTML string for grid visualization
    """
    if not grid_state or not grid_state.get("boxes"):
        return ""

    boxes_html = []
    for box_data in grid_state["boxes"]:
        cells_html = []
        for cell in box_data["cells"]:
            classes = ["cell"]
            attrs = []
            content = ""

            if cell["is_occupied"]:
                classes.append("cell-occupied")
                content = cell["label"]
                color = cell.get("color", "#36506d")
                attrs.append(f'style="background-color: {color};"')
            else:
                classes.append("cell-empty")
                content = cell["display_pos"]

            marker = cell.get("operation_marker")
            if marker:
                attrs.append(f'data-operation="{marker}"')
                if "move_id" in cell:
                    attrs.append(f'data-move-id="{cell["move_id"]}"')

            class_str = " ".join(classes)
            attr_str = " ".join(attrs)
            cells_html.append(f'<div class="{class_str}" {attr_str}>{content}</div>')

        box_html = f"""
        <div class="box">
            <div class="box-header">{box_data["box_label"]}</div>
            <div class="box-grid">
                {"".join(cells_html)}
            </div>
        </div>
        """
        boxes_html.append(box_html)

    return f"""
    <div class="grid-section">
        <h2>Visual Guide - Tank Layout</h2>
        <div class="grid-container">
            {"".join(boxes_html)}
        </div>
    </div>
    """


def render_operation_sheet_with_grid(items, grid_state=None):
    """Generate enhanced printable HTML with grid visualization + operation list.

    Args:
        items: List of plan items
        grid_state: Dict with grid data from overview panel (optional)

    Returns:
        HTML string
    """
    if not items:
        return render_operation_sheet(items)

    if not grid_state:
        return render_operation_sheet(items)

    today = date.today().isoformat()
    total_count = len(items)

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

    grid_html = render_grid_html(grid_state)

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LN2 Operation Preview & Guide - {today}</title>
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

        .grid-section {{
            margin-bottom: 30px;
            page-break-inside: avoid;
        }}

        .grid-section h2 {{
            font-size: {FONT_SIZE_MD}px;
            margin-bottom: 15px;
            color: #1f2937;
        }}

        .grid-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .box {{
            border: 2px solid #36506d;
            border-radius: 8px;
            padding: 12px;
            background: #0f1a2a;
            page-break-inside: avoid;
        }}

        .box-header {{
            font-size: {FONT_SIZE_SM}px;
            font-weight: 600;
            margin-bottom: 10px;
            color: #c6dbf3;
        }}

        .box-grid {{
            display: grid;
            grid-template-columns: repeat(9, 1fr);
            gap: 2px;
        }}

        .cell {{
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 500;
            border: 1px solid #36506d;
            border-radius: 2px;
            padding: 2px;
            position: relative;
        }}

        .cell-occupied {{
            color: white;
        }}

        .cell-empty {{
            background-color: #1a2a40;
            color: #86a0bb;
            font-size: 8px;
        }}

        .cell[data-operation="add"]::after {{
            content: "ADD";
            position: absolute;
            bottom: 1px;
            right: 1px;
            font-size: 7px;
            font-weight: bold;
            color: #22c55e;
            background: rgba(0, 0, 0, 0.7);
            padding: 1px 2px;
            border-radius: 2px;
        }}

        .cell[data-operation="add"] {{
            border: 2px solid #22c55e;
            box-shadow: inset 0 0 0 2px rgba(34, 197, 94, 0.25);
        }}

        .cell[data-operation="takeout"]::after {{
            content: "OUT";
            position: absolute;
            bottom: 1px;
            right: 1px;
            font-size: 7px;
            font-weight: bold;
            color: #ef4444;
            background: rgba(0, 0, 0, 0.7);
            padding: 1px 2px;
            border-radius: 2px;
        }}

        .cell[data-operation="takeout"] {{
            border: 2px solid #ef4444;
            box-shadow: inset 0 0 0 2px rgba(239, 68, 68, 0.25);
        }}

        .cell[data-operation="move-source"]::after {{
            content: attr(data-move-id) "→";
            position: absolute;
            bottom: 1px;
            right: 1px;
            font-size: 9px;
            font-weight: bold;
            color: #63b3ff;
            background: rgba(0, 0, 0, 0.7);
            padding: 1px 2px;
            border-radius: 2px;
        }}

        .cell[data-operation="move-source"] {{
            border: 2px solid #63b3ff;
            box-shadow: inset 0 0 0 2px rgba(99, 179, 255, 0.2);
        }}

        .cell[data-operation="move-target"]::after {{
            content: "←" attr(data-move-id);
            position: absolute;
            bottom: 1px;
            right: 1px;
            font-size: 9px;
            font-weight: bold;
            color: #63b3ff;
            background: rgba(0, 0, 0, 0.7);
            padding: 1px 2px;
            border-radius: 2px;
        }}

        .cell[data-operation="move-target"] {{
            border: 2px solid #63b3ff;
            box-shadow: inset 0 0 0 2px rgba(99, 179, 255, 0.35);
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

        @media print {{
            body {{ padding: 10px; }}
            .grid-section {{ page-break-inside: avoid; }}
            .box {{ page-break-inside: avoid; }}
            .action-section {{ page-break-inside: avoid; }}
            .op-table {{ page-break-inside: auto; }}
            .op-row {{ page-break-inside: avoid; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>LN2 Operation Preview & Guide</h1>
        <div class="header-meta">
            <span>Date: <strong>{today}</strong></span>
            <span>Total: <strong>{total_count} operations</strong></span>
        </div>
    </div>

    {grid_html}

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
