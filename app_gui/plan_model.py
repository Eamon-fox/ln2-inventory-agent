"""Grid-aware operation sheet rendering built on plan_model_sheet helpers."""

import os
from datetime import date

from app_gui.ui.theme import (
    FONT_SIZE_MONO,
    FONT_SIZE_XS,
    FONT_SIZE_SM,
    FONT_SIZE_MD,
    FONT_SIZE_XXL,
    MONO_FONT_CSS_FAMILY,
)
from app_gui.plan_model_sheet import (
    _sheet_color,
    _apply_sheet_theme_tokens,
    validate_plan_item,
    render_operation_sheet,
)
from lib.position_fmt import box_tag_text, format_box_position_display, format_box_positions_display


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
                raw_color = cell_color(color_val if color_val else None)
                cell.update({
                    "id": record.get("id"),
                    "label": label_val if label_val else pos_to_display(position, layout),
                    "color": raw_color,
                })

            cells_data.append(cell)

        boxes_data.append({
            "box_number": box_num,
            "box_label": box_to_display(box_num, layout),
            "box_tag": box_tag_text(box_num, layout),
            "cells": cells_data,
        })

    return {
        "rows": rows,
        "cols": cols,
        "boxes": boxes_data,
        "theme": "dark",
        "display_key": str(display_key or ""),
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
    display_key = str(grid_state.get("display_key") or "").strip()

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
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            raw_positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
            add_positions = []
            for raw_pos in raw_positions:
                try:
                    normalized_pos = int(raw_pos)
                except Exception:
                    continue
                if normalized_pos > 0:
                    add_positions.append(normalized_pos)
            if not add_positions:
                add_positions = [position]
            preview_label = ""
            if display_key:
                fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
                raw_value = fields.get(display_key) if isinstance(fields, dict) else None
                preview_label = str(raw_value).strip() if raw_value is not None else ""
            for add_pos in add_positions:
                marker = {"type": "add"}
                if preview_label:
                    marker["preview_label"] = preview_label
                markers[(box, add_pos)] = marker

        elif action == "takeout" and box and position:
            markers[(box, position)] = {"type": "takeout"}

        elif action == "edit" and box and position:
            markers[(box, position)] = {"type": "edit"}

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
                if "preview_label" in marker:
                    cell["preview_label"] = marker["preview_label"]

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
    from html import escape

    if not grid_state or not grid_state.get("boxes"):
        return ""

    def _resolve_grid_metrics(state):
        """Compute grid geometry for both screen preview and print output."""
        try:
            cols = int(state.get("cols") or 0)
        except Exception:
            cols = 0
        if cols <= 0:
            cols = 9

        # Keep 9x9 appearance as baseline and scale with layout columns.
        cell_gap_mm = 0.6
        baseline_cols = 9
        baseline_cell_mm = 7.2
        baseline_grid_width_mm = baseline_cols * baseline_cell_mm + (baseline_cols - 1) * cell_gap_mm
        raw_cell_mm = (baseline_grid_width_mm - (cols - 1) * cell_gap_mm) / float(cols)

        # Cap growth for sparse layouts; allow shrink for dense layouts.
        cell_mm = max(2.6, min(8.8, raw_cell_mm))
        # Use whole pixels in preview to avoid axis-specific subpixel rounding differences.
        mm_to_px = 96.0 / 25.4
        cell_px = max(10, int(round(cell_mm * mm_to_px)))
        cell_gap_px = max(1, int(round(cell_gap_mm * mm_to_px)))
        cell_font_px = max(6, min(8, int(round(cell_mm + 0.8))))
        cell_empty_font_px = max(5, cell_font_px - 2)
        marker_font_px = max(4, cell_font_px - 2)

        return {
            "cols": cols,
            "cell_mm": cell_mm,
            "cell_gap_mm": cell_gap_mm,
            "cell_px": cell_px,
            "cell_gap_px": cell_gap_px,
            "cell_font_px": cell_font_px,
            "cell_empty_font_px": cell_empty_font_px,
            "marker_font_px": marker_font_px,
        }

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

    grid_metrics = _resolve_grid_metrics(grid_state)
    grid_cols = grid_metrics["cols"]
    grid_cell_mm = grid_metrics["cell_mm"]
    grid_cell_gap_mm = grid_metrics["cell_gap_mm"]
    grid_cell_px = grid_metrics["cell_px"]
    grid_cell_gap_px = grid_metrics["cell_gap_px"]
    grid_cell_font_px = grid_metrics["cell_font_px"]
    grid_cell_empty_font_px = grid_metrics["cell_empty_font_px"]
    grid_marker_font_px = grid_metrics["marker_font_px"]

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
                accent = cell.get("color", _sheet_color("sheet-grid-border", "#8fa4ba"))
                attrs.append(f'style="border-left: 2px solid {accent};"')
            else:
                classes.append("cell-empty")
                preview_label = str(cell.get("preview_label") or "").strip()
                if preview_label and cell.get("operation_marker") == "add":
                    classes.append("cell-add-preview")
                    content = preview_label
                else:
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
        box_tag_text_value = str(box_data.get("box_tag") or "").replace("\r", " ").replace("\n", " ").strip()
        grid_style = (
            f"grid-template-columns: repeat({grid_cols}, var(--cell-size, 7.2mm)); "
            f"--cell-size-print-mm: {grid_cell_mm:.2f}mm; "
            f"--cell-gap-print-mm: {grid_cell_gap_mm:.2f}mm; "
            f"--cell-size-screen-px: {grid_cell_px}px; "
            f"--cell-gap-screen-px: {grid_cell_gap_px}px; "
            f"--cell-font-size: {grid_cell_font_px}px; "
            f"--cell-empty-font-size: {grid_cell_empty_font_px}px; "
            f"--cell-marker-font-size: {grid_marker_font_px}px;"
        )
        tag_html = ""
        if box_tag_text_value:
            tag_html = (
                f'<span class="box-header-tag" title="{escape(box_tag_text_value)}">'
                f"{escape(box_tag_text_value)}</span>"
            )

        box_html = f"""
        <div class="box">
            <div class="box-header">
                <span class="box-header-main">BOX {escape(normalized_label)}</span>
                {tag_html}
                <span class="box-header-num">#{escape(badge_num)}</span>
            </div>
            <div class="box-grid" style="{grid_style}">
                {"".join(cells_html)}
            </div>
        </div>
        """
        boxes_html.append(box_html)

    if not boxes_html:
        return ""

    from app_gui.i18n import tr as _tr

    grid_title = escape(_tr("print.gridSectionTitle", default="Visual Guide - Box Layout"))
    return f"""
    <div class="grid-section print-grid-section">
        <h2>{grid_title}</h2>
        <div class="grid-container print-grid-container">
            {"".join(boxes_html)}
        </div>
    </div>
    """


def render_operation_sheet_with_grid(items, grid_state=None, table_rows=None):
    """Generate enhanced printable HTML with grid visualization + operation list.

    Args:
        items: List of plan items
        grid_state: Dict with grid data from overview panel (optional)
        table_rows: Optional rows from plan-table semantics.

    Returns:
        HTML string
    """
    if not items:
        return render_operation_sheet(items)

    if not grid_state:
        return render_operation_sheet(items)

    from html import escape
    from app_gui.i18n import tr as _tr

    def _text(value):
        return "" if value is None else str(value)

    def _safe_cell(value):
        text = _text(value).strip()
        return text if text else "-"

    def _normalize_action(value):
        return _text(value).strip().lower()

    def _build_fallback_row(item):
        action_norm = _normalize_action(item.get("action"))
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        layout = grid_state.get("layout") if isinstance(grid_state, dict) else None

        if action_norm == "rollback":
            target = "-"
        else:
            target = format_box_position_display(item.get("box"), item.get("position"), layout=layout)

            if action_norm == "move":
                to_pos = item.get("to_position")
                if to_pos not in (None, ""):
                    to_box = item.get("to_box")
                    target = (
                        f"{target} -> "
                        f"{format_box_position_display(to_box if to_box not in (None, '') else item.get('box'), to_pos, layout=layout)}"
                    )
            elif action_norm == "add":
                positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
                if positions:
                    shown_positions = list(positions[:6])
                    base_text = format_box_positions_display(item.get("box"), shown_positions, layout=layout)
                    suffix = f", ... +{len(positions) - 6}" if len(positions) > 6 else ""
                    target = base_text[:-1] + f"{suffix}]" if base_text.endswith("]") and suffix else base_text

        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        if action_norm == "rollback":
            source_event = payload.get("source_event") if isinstance(payload.get("source_event"), dict) else {}
            parts = []
            if source_event:
                parts.append(
                    f"source={_safe_cell(source_event.get('timestamp'))} "
                    f"{_safe_cell(source_event.get('action'))}"
                )
            backup_path = payload.get("backup_path")
            if backup_path:
                parts.append(f"backup={os.path.basename(_text(backup_path))}")
            changes = "; ".join(parts) if parts else "-"
        elif fields:
            field_parts = []
            for key, value in fields.items():
                value_text = _text(value).strip()
                if value_text:
                    field_parts.append(f"{key}={value_text}")
            changes = "; ".join(field_parts) if field_parts else "-"
        else:
            changes = "-"

        action_display = (action_norm.upper() if action_norm else _text(item.get("action"))).strip() or "-"
        date_display = _safe_cell(payload.get("date_str") or payload.get("stored_at") or payload.get("frozen_at"))
        return {
            "action_norm": action_norm,
            "action": action_display,
            "target": target,
            "date": date_display,
            "changes": changes,
            "changes_detail": changes,
            "status": "Ready",
            "status_detail": "",
            "status_blocked": False,
        }

    def _merge_table_row(item, row_data):
        fallback = _build_fallback_row(item)
        if not isinstance(row_data, dict):
            return fallback

        merged = dict(fallback)
        for key in (
            "action_norm",
            "action",
            "target",
            "date",
            "changes",
            "changes_detail",
            "status",
            "status_detail",
            "status_blocked",
        ):
            if key in row_data and row_data.get(key) not in (None, ""):
                merged[key] = row_data.get(key)

        merged["action_norm"] = _normalize_action(merged.get("action_norm") or merged.get("action"))
        merged["status_blocked"] = bool(row_data.get("status_blocked", merged.get("status_blocked")))
        return merged

    normalized_rows = []
    if isinstance(table_rows, list):
        for idx, item in enumerate(items):
            row_data = table_rows[idx] if idx < len(table_rows) else None
            normalized_rows.append(_merge_table_row(item, row_data))
    else:
        normalized_rows = [_build_fallback_row(item) for item in items]

    action_counts = {"takeout": 0, "move": 0, "add": 0, "edit": 0, "rollback": 0}
    for item in items:
        action_norm = _normalize_action(item.get("action"))
        if action_norm in action_counts:
            action_counts[action_norm] += 1

    rows_html = []
    for row in normalized_rows:
        changes_summary = _safe_cell(row.get("changes"))
        changes_detail = _text(row.get("changes_detail")).strip()
        status_summary = _safe_cell(row.get("status"))
        status_detail = _text(row.get("status_detail")).strip()
        is_blocked = bool(row.get("status_blocked"))

        row_classes = "op-row op-row-blocked" if is_blocked else "op-row"
        changes_title = changes_detail if changes_detail and changes_detail != changes_summary else ""
        status_title = status_detail

        rows_html.append(
            f"""
            <tr class="{row_classes}">
                <td class="op-action">{escape(_safe_cell(row.get("action")))}</td>
                <td class="op-target">{escape(_safe_cell(row.get("target")))}</td>
                <td class="op-date">{escape(_safe_cell(row.get("date")))}</td>
                <td class="op-changes" title="{escape(changes_title)}">{escape(changes_summary)}</td>
                <td class="op-status" title="{escape(status_title)}">{escape(status_summary)}</td>
            </tr>"""
        )

    col_action = _tr("operations.colAction", default="Action")
    col_target = _tr("operations.colPosition", default="Target")
    col_date = _tr("operations.date", default="Date")
    col_changes = _tr("operations.colChanges", default="Changes")
    col_status = _tr("operations.colStatus", default="Status")

    table_html = f"""
    <div class="operation-list">
        <table class="op-table">
            <thead>
                <tr>
                    <th class="op-action">{escape(col_action)}</th>
                    <th class="op-target">{escape(col_target)}</th>
                    <th class="op-date">{escape(col_date)}</th>
                    <th class="op-changes">{escape(col_changes)}</th>
                    <th class="op-status">{escape(col_status)}</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows_html)}
            </tbody>
        </table>
    </div>
    """

    today = date.today().isoformat()
    total_count = len(items)
    grid_html = render_grid_html(grid_state)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(_tr("print.title", default="Cryo Operation Preview & Guide"))} - {today}</title>
    <style>
        * {{ box-sizing: border-box; }}
        html, body {{
            width: 100%;
        }}
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

        .sheet-preview-shell {{
            width: 100%;
            max-width: 100%;
            margin: 0 auto;
        }}

        .sheet-page {{
            width: 210mm;
            min-height: 297mm;
            margin: 0 auto;
            background: #fff;
        }}

        .header {{
            border-bottom: 2px solid #1f2937;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}

        .header-title-row {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 5px;
        }}

        .header h1 {{
            margin: 0;
            font-size: {FONT_SIZE_XXL}px;
        }}

        .header-brand {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
            text-align: right;
            white-space: nowrap;
        }}

        .header-brand .brand-line {{
            display: flex;
            gap: 8px;
            align-items: baseline;
        }}

        .header-brand .brand-name {{
            font-size: {FONT_SIZE_SM}px;
            font-weight: 700;
            color: #1f2937;
            letter-spacing: 0.05em;
        }}

        .header-brand .brand-link {{
            font-size: {FONT_SIZE_SM}px;
            font-weight: 600;
            color: #2563eb;
            text-decoration: underline;
        }}

        .header-brand .brand-tagline {{
            font-size: {FONT_SIZE_XS}px;
            color: #64748b;
            font-weight: 400;
            font-style: italic;
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
            justify-items: start;
        }}

        .box {{
            border: 0.4mm solid #9fb2c8;
            border-radius: 2mm;
            padding: 2.5mm;
            background: #f6f8fb;
            break-inside: avoid;
            page-break-inside: avoid;
            justify-self: start;
            align-self: start;
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
            color: #334155;
        }}

        .box-header-tag {{
            flex: 1;
            min-width: 0;
            font-size: 6px;
            color: #64748b;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .box-header-num {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 0;
            padding: 0.4mm 1.4mm;
            border-radius: 999px;
            border: 0.25mm solid #b8c7d8;
            background: rgba(255, 255, 255, 0.92);
            color: #334155;
            font-size: 8px;
            font-weight: 800;
            line-height: 1;
        }}

        .box-grid {{
            display: grid;
            column-gap: var(--cell-gap, 0.6mm);
            row-gap: var(--cell-gap, 0.6mm);
            justify-content: start;
            align-content: start;
        }}

        .cell {{
            aspect-ratio: auto;
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
            align-items: center;
            justify-content: center;
            width: var(--cell-size, 7.2mm);
            height: var(--cell-size, 7.2mm);
            min-width: var(--cell-size, 7.2mm);
            min-height: var(--cell-size, 7.2mm);
            font-size: var(--cell-font-size, 8px);
            line-height: 1.15;
            font-weight: 500;
            border: 0.3mm solid #8fa4ba;
            border-radius: 0.5mm;
            padding: 0 1px;
            position: relative;
            overflow: hidden;
            text-overflow: ellipsis;
            word-break: break-all;
            text-align: center;
        }}

        .cell-occupied {{
            color: #334155;
        }}

        .cell-empty {{
            background-color: transparent;
            color: #7a8796;
            border-color: #dce3ed;
            font-size: var(--cell-empty-font-size, 6px);
            white-space: nowrap;
            -webkit-line-clamp: unset;
        }}

        .cell-empty.cell-add-preview {{
            color: #166534;
            font-size: var(--cell-font-size, 8px);
            font-weight: 600;
            white-space: normal;
            -webkit-line-clamp: 2;
        }}

        .cell[data-operation="add"]::after {{
            content: "ADD";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: var(--cell-marker-font-size, 6px);
            font-weight: bold;
            color: #22c55e;
            background: rgba(255, 255, 255, 0.82);
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
            font-size: var(--cell-marker-font-size, 6px);
            font-weight: bold;
            color: #ef4444;
            background: rgba(255, 255, 255, 0.82);
            padding: 0 1px;
            border-radius: 2px;
        }}

        .cell[data-operation="takeout"] {{
            border: 2px solid #ef4444;
            box-shadow: inset 0 0 0 2px rgba(239, 68, 68, 0.25);
        }}

        .cell[data-operation="edit"]::after {{
            content: "EDIT";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: var(--cell-marker-font-size, 6px);
            font-weight: bold;
            color: #06b6d4;
            background: rgba(255, 255, 255, 0.82);
            padding: 0 1px;
            border-radius: 2px;
        }}

        .cell[data-operation="edit"] {{
            border: 2px solid #06b6d4;
            box-shadow: inset 0 0 0 2px rgba(6, 182, 212, 0.28);
        }}

        .cell[data-operation="move-source"]::after {{
            content: "M" attr(data-move-id) "-FROM";
            position: absolute;
            bottom: 0;
            right: 0;
            font-size: var(--cell-marker-font-size, 6px);
            font-weight: bold;
            color: #63b3ff;
            background: rgba(255, 255, 255, 0.82);
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
            font-size: var(--cell-marker-font-size, 6px);
            font-weight: bold;
            color: #63b3ff;
            background: rgba(255, 255, 255, 0.82);
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

        .operation-list {{
            margin-bottom: 10px;
            break-inside: auto;
            page-break-inside: auto;
        }}

        .op-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
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
            white-space: pre-wrap;
            word-break: break-word;
        }}

        .op-row {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}

        .op-row-blocked .op-status {{
            color: #b91c1c;
            font-weight: 700;
        }}

        .op-action {{
            width: 18%;
            font-weight: 600;
        }}

        .op-target {{
            width: 24%;
            font-family: {MONO_FONT_CSS_FAMILY};
        }}

        .op-date {{
            width: 16%;
        }}

        .op-changes {{
            width: 26%;
        }}

        .op-status {{
            width: 16%;
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

        @media screen {{
            body {{
                background: #e2e8f0;
                padding: 12px;
            }}

            .sheet-page {{
                padding: 12mm;
                box-shadow: 0 14px 36px rgba(15, 23, 42, 0.16);
            }}

            .box-grid {{
                --cell-gap: var(--cell-gap-screen-px, 2px);
                --cell-size: var(--cell-size-screen-px, 27px);
            }}
        }}

        @media print {{
            body {{
                padding: 0;
                background: #fff;
            }}

            .sheet-preview-shell {{
                width: auto;
                height: auto !important;
            }}

            .sheet-page {{
                width: auto;
                min-height: auto;
                padding: 0;
                box-shadow: none;
                transform: none !important;
            }}

            .header {{
                margin-bottom: 6mm;
            }}

            .header-brand .brand-name,
            .header-brand .brand-link {{
                font-size: {FONT_SIZE_XS}px;
            }}

            .header-brand .brand-tagline {{
                font-size: {FONT_SIZE_XS}px;
            }}

            .box-grid {{
                --cell-gap: var(--cell-gap-print-mm, 0.6mm);
                --cell-size: var(--cell-size-print-mm, 7.2mm);
            }}
        }}

        @media (max-width: 180mm) {{
            .print-grid-container {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="sheet-preview-shell">
    <div class="sheet-page">
    <div class="header">
        <div class="header-title-row">
            <h1>{escape(_tr("print.title", default="Cryo Operation Preview & Guide"))}</h1>
            <div class="header-brand">
                <div class="brand-line">
                    <span class="brand-name">SnowFox</span>
                    <a class="brand-link" href="https://snowfox.bio">https://snowfox.bio</a>
                </div>
                <div class="brand-tagline">{escape(_tr("print.brandTagline", default="Intelligent sample inventory for biology labs."))}</div>
            </div>
        </div>
        <div class="header-meta">
            <span>{escape(_tr("print.headerDateLabel", default="Date:"))} <strong>{today}</strong></span>
            <span>{escape(_tr("print.headerTotalLabel", default="Total:"))} <strong>{escape(_tr("print.headerTotalOperations", count=total_count, default=f"{total_count} operations"))}</strong></span>
        </div>
    </div>

    {grid_html}

    <div class="summary">
        <div class="summary-item" style="background: #fef3c7;">{escape(_tr("print.summaryTakeout", count=action_counts.get("takeout", 0), default=f"Takeout: {action_counts.get('takeout', 0)}"))}</div>
        <div class="summary-item" style="background: #dbeafe;">{escape(_tr("print.summaryMove", count=action_counts.get("move", 0), default=f"Move: {action_counts.get('move', 0)}"))}</div>
        <div class="summary-item" style="background: #ede9fe;">{escape(_tr("print.summaryAdd", count=action_counts.get("add", 0), default=f"Add: {action_counts.get('add', 0)}"))}</div>
        <div class="summary-item" style="background: #cffafe;">{escape(_tr("print.summaryEdit", count=action_counts.get("edit", 0), default=f"Edit: {action_counts.get('edit', 0)}"))}</div>
        <div class="summary-item" style="background: #f3f4f6;">{escape(_tr("print.summaryRollback", count=action_counts.get("rollback", 0), default=f"Rollback: {action_counts.get('rollback', 0)}"))}</div>
    </div>

    {table_html}

    <div class="footer">
        <div class="footer-row">
            <span>{escape(_tr("print.footerCompletedBy", default="Completed by:"))} <span class="sign-box"></span></span>
            <span>{escape(_tr("print.footerVerifiedBy", default="Verified by:"))} <span class="sign-box"></span></span>
        </div>
        <div class="footer-row">
            <span>{escape(_tr("print.footerNotes", default="Notes:"))} <span class="sign-box" style="width: 400px;"></span></span>
        </div>
    </div>
    </div>
    </div>
    <script>
    (function () {{
        const shell = document.querySelector('.sheet-preview-shell');
        const page = document.querySelector('.sheet-page');
        if (!shell || !page) {{
            return;
        }}

        function fitA4Preview() {{
            if (window.matchMedia && window.matchMedia('print').matches) {{
                return;
            }}

            page.style.transform = 'none';
            page.style.transformOrigin = 'top center';
            shell.style.height = 'auto';

            const shellWidth = shell.clientWidth;
            const pageWidth = page.offsetWidth;
            if (!shellWidth || !pageWidth) {{
                return;
            }}

            const scale = Math.min(1, shellWidth / pageWidth);
            page.style.transform = `scale(${{scale}})`;
            shell.style.height = `${{Math.ceil(page.offsetHeight * scale)}}px`;
        }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', fitA4Preview);
        }} else {{
            fitA4Preview();
        }}

        window.addEventListener('resize', fitA4Preview);

        if (window.matchMedia) {{
            const mql = window.matchMedia('print');
            const onAfterPrint = function () {{
                window.setTimeout(fitA4Preview, 0);
            }};
            if (mql.addEventListener) {{
                mql.addEventListener('change', function (ev) {{
                    if (!ev.matches) {{
                        onAfterPrint();
                    }}
                }});
            }} else if (mql.addListener) {{
                mql.addListener(function (ev) {{
                    if (!ev.matches) {{
                        onAfterPrint();
                    }}
                }});
            }}
        }}
    }})();
    </script>
</body>
</html>"""
    return _apply_sheet_theme_tokens(html)
