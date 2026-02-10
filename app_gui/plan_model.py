"""Unified Operation Plan model: validation and printable rendering."""

from collections import defaultdict
from datetime import date

_VALID_ACTIONS = {"takeout", "thaw", "discard", "move", "add"}


def validate_plan_item(item: dict) -> str | None:
    """Return an error message if *item* is invalid, or ``None`` if OK."""
    action = str(item.get("action", "")).lower()
    if action not in _VALID_ACTIONS:
        return f"Unknown action: {item.get('action')}"

    box = item.get("box")
    if not isinstance(box, int) or box < 0:
        return "box must be a non-negative integer"

    pos = item.get("position")
    if not isinstance(pos, int) or pos < 1:
        return "position must be a positive integer"

    if action == "move":
        to = item.get("to_position")
        if not isinstance(to, int) or to < 1:
            return "to_position must be a positive integer for move"
        if to == pos:
            return "to_position must differ from position"

    if action != "add":
        rid = item.get("record_id")
        if not isinstance(rid, int) or rid < 1:
            return "record_id must be a positive integer"
    else:
        payload = item.get("payload") or {}
        if not payload.get("parent_cell_line"):
            return "parent_cell_line is required for add"
        if not payload.get("short_name"):
            return "short_name is required for add"

    return None


def render_operation_sheet(items: list[dict]) -> str:
    """Generate a printable HTML operation sheet grouped by box."""
    by_box: dict[int, list[dict]] = defaultdict(list)
    for item in items:
        by_box[item.get("box", 0)].append(item)

    today = date.today().isoformat()
    rows_html = []
    for box_num in sorted(by_box):
        entries = sorted(by_box[box_num], key=lambda x: x.get("position", 0))
        rows_html.append(
            f'<tr class="box-header"><td colspan="6">'
            f'<strong>Box {box_num}</strong> ({len(entries)} ops)</td></tr>'
        )
        for it in entries:
            action = str(it.get("action", "")).capitalize()
            pos = it.get("position", "")
            to_pos = it.get("to_position")
            pos_str = f"{pos} &rarr; {to_pos}" if to_pos else str(pos)
            label = it.get("label", "-")
            rid = it.get("record_id")
            rid_str = f"ID {rid}" if rid else "new"
            note = (it.get("payload") or {}).get("note", "") or ""
            source = it.get("source", "")
            rows_html.append(
                f"<tr>"
                f'<td class="chk"><input type="checkbox"></td>'
                f"<td>{action}</td>"
                f"<td>{pos_str}</td>"
                f"<td>{rid_str}</td>"
                f"<td>{label}</td>"
                f"<td>{note}</td>"
                f"</tr>"
            )

    table = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>LN2 Operation Sheet</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; }}
  h1 {{ font-size: 18px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 4px 8px; font-size: 13px; }}
  th {{ background: #f0f0f0; text-align: left; }}
  .box-header td {{ background: #e8e8e8; font-size: 14px; border-top: 2px solid #888; }}
  .chk {{ width: 24px; text-align: center; }}
  @media print {{ input[type=checkbox] {{ -webkit-appearance: checkbox; }} }}
</style></head><body>
<h1>LN2 Operation Sheet &mdash; {today}</h1>
<p>Total: {len(items)} operation(s)</p>
<table>
<tr><th class="chk"></th><th>Action</th><th>Position</th><th>Record</th><th>Label</th><th>Note</th></tr>
{table}
</table>
</body></html>"""
