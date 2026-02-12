#!/usr/bin/env python3
"""
Check active position conflicts in LN2 inventory.
"""
import argparse
import sys
from collections import defaultdict

import _bootstrap

from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH
from lib.thaw_parser import extract_thaw_positions


def find_active_conflicts(records):
    """Find positions occupied by multiple active records."""
    usage = defaultdict(list)
    for rec in records:
        box = rec.get("box")
        if box is None:
            continue
        for p in rec.get("positions") or []:
            usage[(int(box), int(p))].append(rec)

    conflicts = []
    for (box, pos), recs in usage.items():
        if len(recs) <= 1:
            continue
        active = []
        for rec in recs:
            thawed = extract_thaw_positions(rec)
            if pos not in thawed:
                active.append(rec)
        if len(active) >= 2:
            conflicts.append((box, pos, active))

    conflicts.sort(key=lambda x: (x[0], x[1]))
    return conflicts


def main():
    parser = argparse.ArgumentParser(description="Check active position conflicts")
    parser.add_argument("--yaml", default=YAML_PATH)
    parser.add_argument("--max", type=int, default=0, help="limit conflicts shown")
    args = parser.parse_args()

    data = load_yaml(args.yaml)
    records = data.get("inventory", [])
    conflicts = find_active_conflicts(records)

    if not conflicts:
        print("no active conflicts")
        return 0

    limit = args.max if args.max and args.max > 0 else len(conflicts)
    shown = conflicts[:limit]

    print(f"active_conflicts {len(conflicts)}")
    for box, pos, active in shown:
        print(f"box {box} pos {pos}")
        for rec in active:
            thaw_log = rec.get("thaw_log")
            thaw_preview = str(thaw_log).strip() if thaw_log else "无"
            print(
                f"  id {rec.get('id')} | 冻存 {rec.get('frozen_at')} | {rec.get('parent_cell_line')} | {rec.get('short_name')} | 取出记录: {thaw_preview}"
            )
    return 1


if __name__ == "__main__":
    sys.exit(main())
