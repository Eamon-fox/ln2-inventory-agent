"""Occupancy statistics and capacity/size warning helpers.

These functions derive compact stats from inventory documents and format the
capacity/file-size warnings surfaced during writes and audits. They are pure
(aside from ``os`` for file size / stdout for the ``emit_*`` variants) and hold
no module-level state.
"""
import os

from .config import (
    BOX_EMPTY_WARNING_THRESHOLD,
    TOTAL_EMPTY_WARNING_THRESHOLD,
    YAML_PATH,
    YAML_SIZE_WARNING_MB,
)
from .position_fmt import get_box_numbers, get_total_slots
from .yaml_ops_paths import _abs_path


def compute_occupancy(records):
    """
    Compute occupied positions from inventory records.

    Args:
        records: List of inventory records

    Returns:
        Dict mapping box number (as string) to sorted list of occupied positions
    """
    occupied = {}
    for rec in records:
        box = rec.get("box")
        if box is None:
            continue
        box = str(box)
        occupied.setdefault(box, set())
        position = rec.get("position")
        if position is not None:
            occupied[box].add(int(position))
    return {k: sorted(v) for k, v in sorted(occupied.items(), key=lambda x: int(x[0]))}


def collect_inventory_stats(data):
    """Collect compact occupancy stats for warnings/audit."""
    records = (data or {}).get("inventory", []) if isinstance(data, dict) else []
    layout = (data or {}).get("meta", {}).get("box_layout", {})
    per_box_total = get_total_slots(layout)
    box_numbers = get_box_numbers(layout)
    total_slots = per_box_total * len(box_numbers)

    occupancy = compute_occupancy(records)
    boxes = {}
    total_occupied = 0

    for box_num in box_numbers:
        key = str(box_num)
        occupied = len(occupancy.get(key, []))
        empty = max(per_box_total - occupied, 0)
        boxes[key] = {"occupied": occupied, "empty": empty, "total": per_box_total}
        total_occupied += occupied

    total_empty = max(total_slots - total_occupied, 0)

    return {
        "record_count": len(records),
        "total_slots": total_slots,
        "total_occupied": total_occupied,
        "total_empty": total_empty,
        "boxes": boxes,
    }


def get_capacity_warnings(
    data,
    total_empty_threshold=TOTAL_EMPTY_WARNING_THRESHOLD,
    box_empty_threshold=BOX_EMPTY_WARNING_THRESHOLD,
):
    """Return capacity warning messages based on thresholds."""
    stats = collect_inventory_stats(data)
    warnings = []

    total_empty = stats["total_empty"]
    if total_empty <= int(total_empty_threshold):
        warnings.append(
            f"容量预警: 全罐仅剩 {total_empty} 个空位 (阈值 {total_empty_threshold})"
        )

    for box_key, box_stats in stats["boxes"].items():
        box_empty = box_stats["empty"]
        if box_empty <= int(box_empty_threshold):
            warnings.append(
                f"容量预警: 盒子 {box_key} 仅剩 {box_empty} 个空位 (阈值 {box_empty_threshold})"
            )

    return warnings


def emit_capacity_warnings(
    data,
    total_empty_threshold=TOTAL_EMPTY_WARNING_THRESHOLD,
    box_empty_threshold=BOX_EMPTY_WARNING_THRESHOLD,
):
    """Print capacity warnings and return warning strings."""
    warnings = get_capacity_warnings(
        data,
        total_empty_threshold=total_empty_threshold,
        box_empty_threshold=box_empty_threshold,
    )
    for msg in warnings:
        print(f"[WARN] {msg}")
    return warnings


def get_yaml_size_warning(path=YAML_PATH, warn_mb=YAML_SIZE_WARNING_MB):
    """Return file-size warning message if YAML grows too large."""
    yaml_abs = _abs_path(path)
    if not os.path.exists(yaml_abs):
        return None

    size_bytes = os.path.getsize(yaml_abs)
    size_mb = size_bytes / (1024 * 1024)
    threshold = float(warn_mb)

    if size_mb < threshold:
        return None

    return (
        f"文件体积预警: {os.path.basename(yaml_abs)} 当前 {size_mb:.2f} MB "
        f"(阈值 {threshold:.1f} MB)，建议归档长期不活动记录"
    )


def emit_yaml_size_warning(path=YAML_PATH, warn_mb=YAML_SIZE_WARNING_MB):
    """Print file-size warning and return warning string or None."""
    warning = get_yaml_size_warning(path=path, warn_mb=warn_mb)
    if warning:
        print(f"⚠️  {warning}")
    return warning
