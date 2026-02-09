#!/usr/bin/env python3
"""
Generate statistics and visualizations for LN2 inventory.
"""
import argparse
import sys
from collections import defaultdict

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml, compute_occupancy
from lib.config import YAML_PATH, BOX_RANGE


def get_box_total_slots(layout):
    """Get total slots per box from layout."""
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    return rows * cols


def generate_stats(data):
    """Generate comprehensive statistics."""
    records = data.get("inventory", [])
    layout = data.get("meta", {}).get("box_layout", {})
    total_slots = get_box_total_slots(layout)

    occupancy = compute_occupancy(records)

    # Overall stats
    total_boxes = BOX_RANGE[1] - BOX_RANGE[0] + 1
    total_occupied = sum(len(positions) for positions in occupancy.values())
    total_capacity = total_boxes * total_slots
    overall_rate = (total_occupied / total_capacity * 100) if total_capacity > 0 else 0

    # Per-box stats
    box_stats = {}
    for box_num in range(1, total_boxes + 1):
        box_key = str(box_num)
        occupied_count = len(occupancy.get(box_key, []))
        rate = (occupied_count / total_slots * 100) if total_slots > 0 else 0
        box_stats[box_key] = {
            "occupied": occupied_count,
            "empty": total_slots - occupied_count,
            "total": total_slots,
            "rate": rate
        }

    # Cell line distribution
    cell_lines = defaultdict(int)
    for rec in records:
        if rec.get("positions"):  # Only count records with active positions
            cell_line = rec.get("parent_cell_line", "Unknown")
            cell_lines[cell_line] += len(rec.get("positions", []))

    return {
        "overall": {
            "total_occupied": total_occupied,
            "total_empty": total_capacity - total_occupied,
            "total_capacity": total_capacity,
            "occupancy_rate": overall_rate
        },
        "boxes": box_stats,
        "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True))
    }


def visualize_box(box_num, occupied_positions, layout):
    """Generate ASCII visualization of a box."""
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    occupied_set = set(occupied_positions)

    # Header
    lines = [f"\n盒子 {box_num} 占用情况 (●=占用, ○=空闲):"]
    lines.append("  " + "".join(f"{i+1:3}" for i in range(cols)))

    # Grid
    for row in range(rows):
        line = f"{row+1} "
        for col in range(cols):
            pos = row * cols + col + 1
            symbol = "●" if pos in occupied_set else "○"
            line += f" {symbol} "
        lines.append(line)

    return "\n".join(lines)


def print_stats(stats, data, show_visual=False):
    """Print formatted statistics."""
    layout = data.get("meta", {}).get("box_layout", {})

    print("\n" + "="*60)
    print("液氮罐库存统计")
    print("="*60)

    # Overall stats
    overall = stats["overall"]
    print(f"\n总体情况:")
    print(f"  总容量: {overall['total_capacity']} 个位置")
    print(f"  已占用: {overall['total_occupied']} 个位置")
    print(f"  空  闲: {overall['total_empty']} 个位置")
    print(f"  占用率: {overall['occupancy_rate']:.1f}%")

    # Per-box stats
    print(f"\n各盒子占用情况:")
    print(f"{'盒子':^6} {'占用':>6} {'空闲':>6} {'总计':>6} {'占用率':>8}")
    print("-" * 40)
    for box_num in sorted(stats["boxes"].keys(), key=int):
        box = stats["boxes"][box_num]
        print(f"{box_num:^6} {box['occupied']:>6} {box['empty']:>6} "
              f"{box['total']:>6} {box['rate']:>7.1f}%")

    # Cell line distribution
    if stats["cell_lines"]:
        print(f"\n细胞系分布 (按占用数量排序):")
        print(f"{'细胞系':<20} {'数量':>6}")
        print("-" * 30)
        for cell_line, count in list(stats["cell_lines"].items())[:10]:
            print(f"{cell_line:<20} {count:>6}")

        if len(stats["cell_lines"]) > 10:
            print(f"... 还有 {len(stats['cell_lines']) - 10} 种细胞系")

    # Visual representation
    if show_visual:
        occupancy = compute_occupancy(data.get("inventory", []))
        for box_num in sorted(stats["boxes"].keys(), key=int):
            occupied = occupancy.get(box_num, [])
            print(visualize_box(box_num, occupied, layout))

    print("\n" + "="*60)


def main():
    parser = argparse.ArgumentParser(
        description="Generate statistics and visualizations for LN2 inventory"
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="Path to inventory YAML")
    parser.add_argument("--visual", "-v", action="store_true", help="Show visual box representation")
    parser.add_argument("--box", type=int, help="Show visualization for specific box only")
    args = parser.parse_args()

    data = load_yaml(args.yaml)

    # If only box visualization is requested
    if args.box:
        layout = data.get("meta", {}).get("box_layout", {})
        occupancy = compute_occupancy(data.get("inventory", []))
        occupied = occupancy.get(str(args.box), [])
        print(visualize_box(args.box, occupied, layout))
        return 0

    # Generate and print stats
    stats = generate_stats(data)
    print_stats(stats, data, show_visual=args.visual)

    return 0


if __name__ == "__main__":
    sys.exit(main())
