"""Grid-aware operation sheet rendering built on plan_model_sheet helpers."""

from collections import defaultdict
from datetime import date

from app_gui.ui.theme import (
    FONT_SIZE_MONO,
    FONT_SIZE_XS,
    FONT_SIZE_SM,
    FONT_SIZE_MD,
    FONT_SIZE_XXL,
    MONO_FONT_CSS_FAMILY,
    resolve_theme_token,
)
from app_gui.plan_model_sheet import (
    _sheet_color,
    _apply_sheet_theme_tokens,
    _pos_to_coord,
    validate_plan_item,
    _get_action_display,
    _extract_sample_info,
    render_operation_sheet,
)

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
    active_boxes = set()
    move_counter = 1

    def _normalize_box(raw):
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    for item in plan_items:
        action = item.get("action", "").lower()
        box = _normalize_box(item.get("box"))
        position = item.get("position")

        if box is not None:
            active_boxes.add(box)

        if action == "add" and box and position:
            markers[(box, position)] = {"type": "add"}

        elif action == "takeout" and box and position:
            markers[(box, position)] = {"type": "takeout"}

        elif action == "move" and box and position:
            move_id = move_counter
            move_counter += 1

            markers[(box, position)] = {"type": "move-source", "move_id": move_id}

            to_box = _normalize_box(item.get("to_box")) or box
            active_boxes.add(to_box)
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

    # Preserve explicit filter intent for render_grid_html:
    # empty list means "show no boxes" (e.g., rollback-only plan).
    grid_state["active_boxes"] = sorted(active_boxes)
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

    has_active_filter = "active_boxes" in grid_state
    active_boxes = set()
    if has_active_filter:
        for raw in (grid_state.get("active_boxes") or []):
            try:
                value = int(raw)
            except Exception:
                continue
            if value > 0:
                active_boxes.add(value)

    boxes_html = []
    for box_data in grid_state["boxes"]:
        box_num = box_data.get("box_number")
        try:
            box_num_int = int(box_num)
        except Exception:
            box_num_int = None

        if has_active_filter and box_num_int not in active_boxes:
            continue

        cells_html = []
        for cell in box_data["cells"]:
            classes = ["cell"]
            attrs = []
            content = ""

            if cell["is_occupied"]:
                classes.append("cell-occupied")
                content = cell["label"]
                color = cell.get("color", _sheet_color("sheet-grid-border", "#36506d"))
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

        raw_label = str(box_data.get("box_label") or "").strip()
        if not raw_label:
            raw_label = str(box_num_int) if box_num_int is not None else str(box_num or "?")

        # Avoid redundant "BOX Box1" style when layout labels already include "Box".
        normalized_label = raw_label
        if raw_label.lower().startswith("box"):
            suffix = raw_label[3:].strip()
            if suffix:
                normalized_label = suffix

        badge_num = str(box_num_int) if box_num_int is not None else normalized_label

        box_html = f"""
        <div class="box">
            <div class="box-header">
                <span class="box-header-main">BOX {normalized_label}</span>
                <span class="box-header-num">#{badge_num}</span>
            </div>
            <div class="box-grid">
                {"".join(cells_html)}
            </div>
        </div>
        """
        boxes_html.append(box_html)

    if not boxes_html:
        return ""

    return f"""
    <div class="grid-section print-grid-section">
        <h2>Visual Guide - Tank Layout</h2>
        <div class="grid-container print-grid-container">
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

    action_order = ["takeout", "move", "add", "edit", "rollback"]

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
            note = _fields.get("note", "") or ""

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

    takeout_count = len(by_action.get("takeout", []))
    move_count = len(by_action.get("move", []))
    add_count = len(by_action.get("add", []))
    edit_count = len(by_action.get("edit", []))
    rollback_count = len(by_action.get("rollback", []))

    grid_html = render_grid_html(grid_state)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LN2 Operation Preview & Guide - {today}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 0;
            font-size: {FONT_SIZE_SM}px;
            line-height: 1.3;
            color: #1f2937;
            background: #fff;
            print-color-adjust: exact;
            -webkit-print-color-adjust: exact;
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
            margin-bottom: 8mm;
            break-inside: auto;
            page-break-inside: auto;
        }}

        .grid-section h2 {{
            font-size: {FONT_SIZE_MD}px;
            margin-bottom: 15px;
            color: #1f2937;
        }}

        .grid-container {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 4mm;
            margin-bottom: 6mm;
            align-items: start;
        }}

        .box {{
            border: 0.4mm solid #36506d;
            border-radius: 2mm;
            padding: 2.5mm;
            background: #0f1a2a;
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        .box-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.4mm;
            margin-bottom: 1.8mm;
        }}

        .box-header-main {{
            font-size: 7px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #9fc2e8;
        }}

        .box-header-num {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 0;
            padding: 0.4mm 1.4mm;
            border-radius: 999px;
            border: 0.25mm solid #36506d;
            background: rgba(15, 26, 42, 0.85);
            color: #e6f1ff;
            font-size: 8px;
            font-weight: 800;
            line-height: 1;
        }}

        .box-grid {{
            display: grid;
            grid-template-columns: repeat(9, 1fr);
            gap: 0.6mm;
        }}

        .cell {{
            aspect-ratio: auto;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 7.2mm;
            height: 7.2mm;
            min-width: 7.2mm;
            min-height: 7.2mm;
            font-size: 8px;
            line-height: 1;
            font-weight: 500;
            border: 0.3mm solid #36506d;
            border-radius: 0.5mm;
            padding: 0;
            position: relative;
            overflow: hidden;
        }}

        .cell-occupied {{
            color: white;
        }}

        .cell-empty {{
            background-color: #1a2a40;
            color: #86a0bb;
            font-size: 6px;
        }}

        .cell[data-operation="add"]::after {{
            content: "ADD";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: 6px;
            font-weight: bold;
            color: #22c55e;
            background: rgba(0, 0, 0, 0.7);
            padding: 0 1px;
            border-radius: 2px;
        }}

        .cell[data-operation="add"] {{
            border: 2px solid #22c55e;
            box-shadow: inset 0 0 0 2px rgba(34, 197, 94, 0.25);
        }}

        .cell[data-operation="takeout"]::after {{
            content: "OUT";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: 6px;
            font-weight: bold;
            color: #ef4444;
            background: rgba(0, 0, 0, 0.7);
            padding: 0 1px;
            border-radius: 2px;
        }}

        .cell[data-operation="takeout"] {{
            border: 2px solid #ef4444;
            box-shadow: inset 0 0 0 2px rgba(239, 68, 68, 0.25);
        }}

        .cell[data-operation="move-source"]::after {{
            content: "M" attr(data-move-id) "-FROM";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: 6px;
            font-weight: bold;
            color: #63b3ff;
            background: rgba(0, 0, 0, 0.7);
            padding: 0 1px;
            border-radius: 2px;
        }}

        .cell[data-operation="move-source"] {{
            border: 2px solid #63b3ff;
            box-shadow: inset 0 0 0 2px rgba(99, 179, 255, 0.2);
        }}

        .cell[data-operation="move-target"]::after {{
            content: "M" attr(data-move-id) "-TO";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: 6px;
            font-weight: bold;
            color: #63b3ff;
            background: rgba(0, 0, 0, 0.7);
            padding: 0 1px;
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
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        .summary-item {{
            padding: 5px 12px;
            border-radius: 4px;
            font-weight: 600;
        }}

        .action-section {{
            margin-bottom: 25px;
            padding-left: 10px;
            break-inside: avoid;
            page-break-inside: avoid;
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
            break-inside: auto;
            page-break-inside: auto;
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

        .op-row {{
            break-inside: avoid;
            page-break-inside: avoid;
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
            font-family: {MONO_FONT_CSS_FAMILY};
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

        @page {{
            size: A4 portrait;
            margin: 10mm;
        }}

        @media (max-width: 180mm) {{
            .print-grid-container {{
                grid-template-columns: 1fr;
            }}
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
        <div class="summary-item" style="background: #fef3c7;">Takeout: {takeout_count}</div>
        <div class="summary-item" style="background: #dbeafe;">Move: {move_count}</div>
        <div class="summary-item" style="background: #ede9fe;">Add: {add_count}</div>
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
    return _apply_sheet_theme_tokens(html)


