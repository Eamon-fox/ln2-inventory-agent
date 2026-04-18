"""Unified Operation Plan model: validation and printable rendering."""

from collections import defaultdict
from datetime import date
from typing import Optional

from app_gui.i18n import tr as _tr
from app_gui.ui.theme import (
    FONT_SIZE_MONO,
    FONT_SIZE_XS,
    FONT_SIZE_SM,
    FONT_SIZE_MD,
    FONT_SIZE_XXL,
    MONO_FONT_CSS_FAMILY,
    resolve_theme_token,
)
from lib.plan_item_factory import PlanItem
from lib.plan_validation import validate_plan_item
from lib.tool_registry import VALID_PLAN_ACTIONS

_VALID_ACTIONS = VALID_PLAN_ACTIONS
_SHEET_THEME_MODE = "light"


def _sheet_color(token_name, fallback):
    return resolve_theme_token(token_name, mode=_SHEET_THEME_MODE, fallback=fallback)


def _apply_sheet_theme_tokens(html):
    """Replace legacy hardcoded sheet colors with theme token values."""
    if not isinstance(html, str) or not html:
        return html

    replacements = {
        "#666": _sheet_color("sheet-text-muted", "#6b7280"),
        "#1f2937": _sheet_color("sheet-text-primary", "#1f2937"),
        "#fff": _sheet_color("sheet-bg", "#ffffff"),
        "#6b7280": _sheet_color("sheet-text-muted", "#6b7280"),
        "#9ca3af": _sheet_color("status-muted", "#9ca3af"),
        "#f9fafb": _sheet_color("sheet-section-bg", "#f9fafb"),
        "#f3f4f6": _sheet_color("sheet-chip-rollback-bg", "#f3f4f6"),
        "#e5e7eb": _sheet_color("sheet-border", "#e5e7eb"),
        "#d1d5db": _sheet_color("sheet-border", "#d1d5db"),
        "#fef3c7": _sheet_color("sheet-chip-takeout-bg", "#fef3c7"),
        "#f59e0b": _sheet_color("sheet-action-takeout", "#f59e0b"),
        "#92400e": _sheet_color("sheet-tip-title", "#92400e"),
        "#78350f": _sheet_color("sheet-tip-text", "#78350f"),
        "#dbeafe": _sheet_color("sheet-chip-move-bg", "#dbeafe"),
        "#ede9fe": _sheet_color("sheet-chip-add-bg", "#ede9fe"),
        "#cffafe": _sheet_color("sheet-chip-edit-bg", "#cffafe"),
        "#0f1a2a": _sheet_color("sheet-grid-bg", "#0f1a2a"),
        "#36506d": _sheet_color("sheet-grid-border", "#36506d"),
        "#c6dbf3": _sheet_color("sheet-grid-text", "#c6dbf3"),
        "#1a2a40": _sheet_color("sheet-grid-empty-bg", "#1a2a40"),
        "#86a0bb": _sheet_color("sheet-grid-empty-text", "#86a0bb"),
        "rgba(0, 0, 0, 0.7)": _sheet_color("sheet-grid-overlay-bg", "rgba(0, 0, 0, 0.7)"),
        "rgba(34, 197, 94, 0.25)": _sheet_color("preview-add-bg", "rgba(34, 197, 94, 0.25)"),
        "rgba(239, 68, 68, 0.25)": _sheet_color("preview-takeout-bg", "rgba(239, 68, 68, 0.25)"),
        "rgba(99, 179, 255, 0.2)": _sheet_color("preview-move-source-bg", "rgba(99, 179, 255, 0.2)"),
        "rgba(99, 179, 255, 0.35)": _sheet_color("preview-move-target-bg", "rgba(99, 179, 255, 0.35)"),
        "#63b3ff": _sheet_color("sheet-action-move", "#63b3ff"),
    }

    themed_html = html
    for raw, themed in replacements.items():
        themed_html = themed_html.replace(raw, str(themed))
    return themed_html


def _pos_to_coord(pos, cols=9):
    """Return position as-is (pure number format)."""
    return str(pos) if isinstance(pos, int) else str(pos)


def _get_action_display(action):
    """Get display info for action type."""
    action_map = {
        "takeout": (
            _tr("print.actionTakeout", default="TAKEOUT"),
            _sheet_color("sheet-action-takeout", "#f59e0b"),
            _tr("print.actionTakeoutDesc", default="Take out from storage"),
        ),
        "move": (
            _tr("print.actionMove", default="MOVE"),
            _sheet_color("sheet-action-move", "#3b82f6"),
            _tr("print.actionMoveDesc", default="Relocate sample"),
        ),
        "add": (
            _tr("print.actionAdd", default="ADD"),
            _sheet_color("sheet-action-add", "#8b5cf6"),
            _tr("print.actionAddDesc", default="Add new sample"),
        ),
        "edit": (
            _tr("print.actionEdit", default="EDIT"),
            _sheet_color("sheet-action-edit", "#06b6d4"),
            _tr("print.actionEditDesc", default="Edit record fields"),
        ),
        "rollback": (
            _tr("print.actionRollback", default="ROLLBACK"),
            _sheet_color("sheet-action-rollback", "#6b7280"),
            _tr("print.actionRollbackDesc", default="Restore from backup"),
        ),
    }
    return action_map.get(
        str(action).lower(),
        (str(action).upper(), _sheet_color("sheet-action-rollback", "#6b7280"), ""),
    )


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
    fallback_label = str(item.get("label") or "").strip()
    return {
        "label": " / ".join(user_vals[:2]) if user_vals else fallback_label,
        "frozen_at": (
            fields.get("stored_at")
            or fields.get("frozen_at")
            or item.get("stored_at")
            or item.get("frozen_at")
            or payload.get("stored_at")
            or payload.get("frozen_at")
            or ""
        ),
    }


def render_operation_sheet(items):
    """Generate a user-friendly printable HTML operation sheet."""
    if not items:
        empty_title = _tr("print.fallbackTitle", default="Cryo Operation Sheet")
        empty_msg = _tr("print.emptyMessage", default="No operations to display.")
        empty_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{empty_title}</title>
<style>body {{ font-family: Arial, sans-serif; margin: 40px; color: #666; }}</style>
</head><body><p>{empty_msg}</p></body></html>"""
        return _apply_sheet_theme_tokens(empty_html)

    today = date.today().isoformat()
    
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
                    warning = f'<span class="warning">{_tr("print.crossBoxWarning", default="[CROSS-BOX]")}</span>'
                else:
                    pos_display = f"Box{box}:{_pos_to_coord(pos)} &rarr; {_pos_to_coord(to_pos)}"
                    warning = ""
            else:
                pos_display = f"Box{box}:{_pos_to_coord(pos)}"
                warning = ""
            
            sample = _extract_sample_info(item)
            rid = item.get("record_id")
            
            sample_label = str(sample.get("label") or "").strip() or "-"
            
            _payload = item.get("payload") or {}
            _fields = _payload.get("fields") or {}
            note = _fields.get("note", "") or ""
            
            id_display = rid if rid else _tr("print.sampleIdNew", default="NEW")
            sample_id_text = _tr("print.sampleIdLabel", id=id_display, default=f"ID: {id_display}")
            action_rows.append(f"""
            <tr class="op-row">
                <td class="op-num">{op_counter}</td>
                <td class="chk-cell"><input type="checkbox" id="op{op_counter}"></td>
                <td class="pos-cell">{pos_display} {warning}</td>
                <td class="sample-cell">
                    <div class="sample-name">{sample_label}</div>
                    <div class="sample-meta">{sample_id_text}</div>
                </td>
                <td class="note-cell">{note}</td>
                <td class="confirm-cell">
                    <div class="confirm-line">{_tr("print.confirmTime", default="Time: _______")}</div>
                    <div class="confirm-line">{_tr("print.confirmInit", default="Init: _______")}</div>
                </td>
            </tr>""")
            op_counter += 1
        
        action_count_label = _tr("print.actionCount", count=len(action_items), default=f"{len(action_items)} operations")
        sections.append(f"""
        <div class="action-section" style="border-left: 4px solid {action_color};">
            <div class="action-header">
                <span class="action-name" style="background-color: {action_color};">{action_name}</span>
                <span class="action-count">{action_count_label}</span>
                <span class="action-desc">{action_desc}</span>
            </div>
            <table class="op-table">
                <thead>
                    <tr>
                        <th class="col-num">{_tr("print.colNum", default="#")}</th>
                        <th class="col-chk">{_tr("print.colDone", default="Done")}</th>
                        <th class="col-pos">{_tr("print.colLocation", default="Location")}</th>
                        <th class="col-sample">{_tr("print.colSample", default="Sample")}</th>
                        <th class="col-note">{_tr("print.colNotes", default="Notes")}</th>
                        <th class="col-confirm">{_tr("print.colConfirmation", default="Confirmation")}</th>
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
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{_tr("print.fallbackTitle", default="Cryo Operation Sheet")} - {today}</title>
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

        .header-title-row {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 5px;
        }}

        .header h1 {{
            margin: 0 0 5px 0;
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
        
        @page {{
            size: A4 portrait;
            margin: 10mm;
        }}

        @media print {{
            html, body {{
                width: auto;
                max-width: none;
            }}

            body {{
                padding: 0;
                line-height: 1.3;
                print-color-adjust: exact;
                -webkit-print-color-adjust: exact;
            }}

            .action-section {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}

            .op-table {{
                break-inside: auto;
                page-break-inside: auto;
            }}

            .op-row {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-title-row">
            <h1>{_tr("print.fallbackTitle", default="Cryo Operation Sheet")}</h1>
            <div class="header-brand">
                <div class="brand-line">
                    <span class="brand-name">SnowFox</span>
                    <a class="brand-link" href="https://snowfox.bio">https://snowfox.bio</a>
                </div>
                <div class="brand-tagline">{_tr("print.brandTagline", default="Intelligent sample inventory for biology labs.")}</div>
            </div>
        </div>
        <div class="header-meta">
            <span>{_tr("print.headerDateLabel", default="Date:")} <strong>{today}</strong></span>
            <span>{_tr("print.headerTotalLabel", default="Total:")} <strong>{_tr("print.headerTotalOperations", count=len(items), default=f"{len(items)} operations")}</strong></span>
        </div>
    </div>

    <div class="summary">
        <div class="summary-item" style="background: #fef3c7;">{_tr("print.summaryTakeout", count=takeout_count, default=f"Takeout: {takeout_count}")}</div>
        <div class="summary-item" style="background: #dbeafe;">{_tr("print.summaryMove", count=move_count, default=f"Move: {move_count}")}</div>
        <div class="summary-item" style="background: #ede9fe;">{_tr("print.summaryAdd", count=add_count, default=f"Add: {add_count}")}</div>
        <div class="summary-item" style="background: #cffafe;">{_tr("print.summaryEdit", count=edit_count, default=f"Edit: {edit_count}")}</div>
        <div class="summary-item" style="background: #f3f4f6;">{_tr("print.summaryRollback", count=rollback_count, default=f"Rollback: {rollback_count}")}</div>
    </div>

    {sections_html}

    <div class="footer">
        <div class="footer-row">
            <span>{_tr("print.footerCompletedBy", default="Completed by:")} <span class="sign-box"></span></span>
            <span>{_tr("print.footerVerifiedBy", default="Verified by:")} <span class="sign-box"></span></span>
        </div>
        <div class="footer-row">
            <span>{_tr("print.footerNotes", default="Notes:")} <span class="sign-box" style="width: 400px;"></span></span>
        </div>
    </div>
</body>
</html>"""
    return _apply_sheet_theme_tokens(html)


