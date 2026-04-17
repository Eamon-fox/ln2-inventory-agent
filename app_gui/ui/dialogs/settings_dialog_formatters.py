from __future__ import annotations

from app_gui.i18n import t
from lib.position_fmt import box_to_display, pos_to_display


def format_removed_field_preview_value(value, *, max_length=80):
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    if len(text) > max_length:
        return f"{text[: max_length - 3]}..."
    return text


def format_removed_field_preview_box(box, layout):
    if box in (None, ""):
        return "?"
    try:
        return box_to_display(box, layout)
    except Exception:
        return str(box)


def format_removed_field_preview_position(position, layout):
    if position in (None, ""):
        return "?"
    try:
        return pos_to_display(int(position), layout)
    except Exception:
        return str(position)


def format_removed_field_preview_entry(entry, *, layout):
    record_id = entry.record_id
    if record_id in (None, ""):
        record_id = "?"
    return t(
        "main.cfRemoveDataPreviewItem",
        id=record_id,
        box=format_removed_field_preview_box(entry.box, layout),
        position=format_removed_field_preview_position(entry.position, layout),
        value=format_removed_field_preview_value(entry.value),
    )


def format_removed_field_preview_summary(previews, *, layout):
    blocks = []
    for preview in previews:
        lines = [
            t(
                "main.cfRemoveDataPreviewField",
                field=preview.field_key,
                count=preview.affected_count,
            )
        ]
        lines.extend(
            format_removed_field_preview_entry(entry, layout=layout)
            for entry in preview.samples
        )
        if preview.hidden_count:
            lines.append(t("main.cfRemoveDataPreviewMore", count=preview.hidden_count))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_removed_field_preview_details(previews, *, layout):
    blocks = []
    for preview in previews:
        lines = [
            t(
                "main.cfRemoveDataPreviewField",
                field=preview.field_key,
                count=preview.affected_count,
            )
        ]
        lines.extend(
            format_removed_field_preview_entry(entry, layout=layout)
            for entry in preview.entries
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
