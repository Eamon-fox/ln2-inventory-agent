#!/usr/bin/env python3
"""
Recommend optimal positions for new frozen samples.
"""
import argparse
import sys

import _bootstrap

from lib.yaml_ops import compute_occupancy
from lib.config import YAML_PATH, BOX_RANGE
from lib.tool_api import tool_recommend_positions


def get_box_total_slots(layout):
    """Get total slots per box from layout."""
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    return rows * cols


def find_consecutive_slots(empty_positions, count):
    """Find consecutive empty slots."""
    if not empty_positions or count <= 0:
        return []

    consecutive_groups = []
    current_group = [empty_positions[0]]

    for i in range(1, len(empty_positions)):
        if empty_positions[i] == current_group[-1] + 1:
            current_group.append(empty_positions[i])
        else:
            if len(current_group) >= count:
                consecutive_groups.append(current_group[:count])
            current_group = [empty_positions[i]]

    # Check the last group
    if len(current_group) >= count:
        consecutive_groups.append(current_group[:count])

    return consecutive_groups


def find_same_row_slots(empty_positions, count, layout):
    """Find empty slots in the same row."""
    cols = int(layout.get("cols", 9))

    # Group by row
    row_groups = {}
    for pos in empty_positions:
        row = (pos - 1) // cols
        row_groups.setdefault(row, []).append(pos)

    # Find rows with enough empty slots
    same_row_groups = []
    for row, positions in sorted(row_groups.items()):
        if len(positions) >= count:
            consecutive = find_consecutive_slots(positions, count)
            if consecutive:
                same_row_groups.extend(consecutive)
            else:
                same_row_groups.append(sorted(positions)[:count])

    return same_row_groups


def recommend_positions(data, count, box_preference=None, strategy="consecutive"):
    """Recommend positions for new samples."""
    layout = data.get("meta", {}).get("box_layout", {})
    total_slots = get_box_total_slots(layout)
    all_positions = set(range(1, total_slots + 1))

    occupancy = compute_occupancy(data.get("inventory", []))

    recommendations = []

    # Determine which boxes to check
    if box_preference:
        boxes_to_check = [str(box_preference)]
    else:
        boxes_to_check = []
        for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
            box_key = str(box_num)
            occupied_count = len(occupancy.get(box_key, []))
            boxes_to_check.append((box_key, occupied_count))
        boxes_to_check = [box for box, _ in sorted(boxes_to_check, key=lambda x: x[1])]

    for box in boxes_to_check:
        occupied = set(occupancy.get(box, []))
        empty = sorted(all_positions - occupied)

        if len(empty) < count:
            continue

        box_recommendations = []

        if strategy in ("consecutive", "any"):
            consecutive_groups = find_consecutive_slots(empty, count)
            if consecutive_groups:
                for group in consecutive_groups[:3]:
                    box_recommendations.append({
                        "box": box,
                        "positions": group,
                        "reason": "连续位置",
                        "score": 100
                    })

        if strategy == "same_row":
            same_row_groups = find_same_row_slots(empty, count, layout)
            if same_row_groups:
                for group in same_row_groups[:3]:
                    box_recommendations.append({
                        "box": box,
                        "positions": group,
                        "reason": "同一行",
                        "score": 90
                    })

        # Fallback: first N empty slots
        if not box_recommendations:
            box_recommendations.append({
                "box": box,
                "positions": empty[:count],
                "reason": "最早空位",
                "score": 50
            })

        recommendations.extend(box_recommendations)

        if len(recommendations) >= 5:
            break

    return recommendations[:5]


def print_recommendations(recommendations, count):
    """Print formatted recommendations."""
    if not recommendations:
        print(f"\n未找到足够的空位（需要 {count} 个）")
        return

    print(f"\n为 {count} 个样品推荐的位置:\n")
    print(f"{'选项':<6} {'盒子':<6} {'位置':<30} {'优先级':<12} {'说明'}")
    print("-" * 80)

    for i, rec in enumerate(recommendations, 1):
        positions_str = ", ".join(str(p) for p in rec["positions"])
        score_bar = "★" * (rec["score"] // 20)
        print(f"{i:<6} {rec['box']:<6} {positions_str:<30} {score_bar:<12} {rec['reason']}")

    print(f"\n推荐使用选项 1（最优）\n")


def main():
    parser = argparse.ArgumentParser(
        description="Recommend optimal positions for new frozen samples"
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="Path to inventory YAML")
    parser.add_argument("--count", "-n", type=int, default=2,
                        help="Number of positions needed (default: 2)")
    parser.add_argument("--box", type=int, help="Prefer specific box")
    parser.add_argument("--strategy", choices=["consecutive", "same_row", "any"],
                        default="consecutive",
                        help="Position selection strategy (default: consecutive)")
    args = parser.parse_args()

    if args.count <= 0:
        print("错误: 数量必须大于 0")
        return 1

    response = tool_recommend_positions(
        yaml_path=args.yaml,
        count=args.count,
        box_preference=args.box,
        strategy=args.strategy,
    )
    if not response.get("ok"):
        print(f"错误: {response.get('message', '推荐失败')}")
        return 1

    recommendations = response["result"]["recommendations"]
    print_recommendations(recommendations, args.count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
