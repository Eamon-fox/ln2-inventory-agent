#!/usr/bin/env python3
"""
Validate LN2 inventory data for errors and inconsistencies.
"""
import argparse
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH, BOX_RANGE, POSITION_RANGE
from lib.thaw_parser import is_position_active, normalize_action


def validate_date_format(date_str):
    """Check if date is in YYYY-MM-DD format."""
    if not date_str:
        return True  # null is acceptable
    try:
        datetime.strptime(str(date_str), "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def has_depletion_history(rec):
    """Return True if record has thaw/takeout/discard history.

    Fully consumed records are expected to end with positions=[].
    """
    thaw_events = rec.get("thaw_events") or []
    for ev in thaw_events:
        if normalize_action(ev.get("action")) in {"takeout", "thaw", "discard"}:
            return True

    # Backward compatibility for legacy free-text logs.
    thaw_log = rec.get("thaw_log")
    return bool(thaw_log and str(thaw_log).strip())


def validate_record(rec, idx, layout):
    """Validate a single inventory record."""
    errors = []
    warnings = []

    rec_id = f"记录 #{idx+1} (id={rec.get('id', 'N/A')})"

    # Check required fields
    required_fields = ["id", "parent_cell_line", "short_name", "box", "positions", "frozen_at"]
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{rec_id}: 缺少必填字段 '{field}'")

    # Validate ID
    if "id" in rec:
        if not isinstance(rec["id"], int) or rec["id"] <= 0:
            errors.append(f"{rec_id}: 'id' 必须是正整数")

    # Validate box
    if "box" in rec:
        if not isinstance(rec["box"], int):
            errors.append(f"{rec_id}: 'box' 必须是整数")
        elif rec["box"] < BOX_RANGE[0] or rec["box"] > BOX_RANGE[1]:
            warnings.append(f"{rec_id}: 'box' 值 {rec['box']} 超出常规范围 ({BOX_RANGE[0]}-{BOX_RANGE[1]})")

    # Validate positions
    if "positions" in rec:
        positions = rec.get("positions")
        if not isinstance(positions, list):
            errors.append(f"{rec_id}: 'positions' 必须是列表")
        elif not positions:
            if not has_depletion_history(rec):
                errors.append(f"{rec_id}: 'positions' 为空，但没有取出/复苏/扔掉记录")
        else:
            for pos in positions:
                if not isinstance(pos, int):
                    errors.append(f"{rec_id}: 位置 {pos} 必须是整数")
                elif pos < POSITION_RANGE[0] or pos > POSITION_RANGE[1]:
                    errors.append(f"{rec_id}: 位置 {pos} 超出范围 ({POSITION_RANGE[0]}-{POSITION_RANGE[1]})")

            # Check for duplicates within the record
            if len(positions) != len(set(positions)):
                warnings.append(f"{rec_id}: 'positions' 中存在重复值")

    # Validate date
    if "frozen_at" in rec and not validate_date_format(rec["frozen_at"]):
        errors.append(f"{rec_id}: 'frozen_at' 日期格式错误，应为 YYYY-MM-DD")

    # Check for suspiciously old dates
    if "frozen_at" in rec and rec["frozen_at"]:
        try:
            frozen_date = datetime.strptime(str(rec["frozen_at"]), "%Y-%m-%d")
            if frozen_date.year < 2020:
                warnings.append(f"{rec_id}: 冻存日期 {rec['frozen_at']} 看起来很旧")
            if frozen_date > datetime.now():
                errors.append(f"{rec_id}: 冻存日期 {rec['frozen_at']} 在未来")
        except ValueError:
            pass

    # Check for empty strings
    for field in ["parent_cell_line", "short_name"]:
        if field in rec and rec[field] == "":
            warnings.append(f"{rec_id}: '{field}' 为空字符串")

    return errors, warnings


def check_duplicate_ids(records):
    """Check for duplicate IDs."""
    id_map = {}
    errors = []

    for idx, rec in enumerate(records):
        rec_id = rec.get("id")
        if rec_id is not None:
            if rec_id in id_map:
                errors.append(
                    f"重复的 ID {rec_id}: 记录 #{idx+1} 和记录 #{id_map[rec_id]+1}"
                )
            else:
                id_map[rec_id] = idx

    return errors


def check_position_conflicts(records):
    """Check for position conflicts (active double-occupancy)."""
    usage = defaultdict(list)
    for idx, rec in enumerate(records):
        box = rec.get("box")
        if box is None:
            continue
        for p in rec.get("positions") or []:
            if is_position_active(rec, p):
                usage[(int(box), int(p))].append((idx, rec))

    conflicts = []
    for (box, pos), records_list in usage.items():
        if len(records_list) > 1:
            rec_ids = ", ".join(f"#{idx+1} (id={rec.get('id')})"
                                for idx, rec in records_list)
            conflicts.append(
                f"位置冲突: 盒子 {box} 位置 {pos} 被多条记录占用: {rec_ids}"
            )

    return conflicts


def validate_inventory(data):
    """Validate entire inventory."""
    all_errors = []
    all_warnings = []

    layout = data.get("meta", {}).get("box_layout", {})
    records = data.get("inventory", [])

    # Validate each record
    for idx, rec in enumerate(records):
        errors, warnings = validate_record(rec, idx, layout)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    # Check for duplicate IDs
    dup_errors = check_duplicate_ids(records)
    all_errors.extend(dup_errors)

    # Check for position conflicts
    conflicts = check_position_conflicts(records)
    all_errors.extend(conflicts)

    return all_errors, all_warnings


def print_validation_results(errors, warnings):
    """Print validation results."""
    print("\n" + "="*60)
    print("数据验证报告")
    print("="*60)

    if errors:
        print(f"\n发现 {len(errors)} 个错误:\n")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}")
    else:
        print("\n✓ 未发现错误")

    if warnings:
        print(f"\n发现 {len(warnings)} 个警告:\n")
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}")
    else:
        print("\n✓ 未发现警告")

    print("\n" + "="*60)

    if errors:
        print("\n建议: 修复上述错误以确保数据完整性")
        return 1
    elif warnings:
        print("\n建议: 检查上述警告，确认是否需要修改")
        return 0
    else:
        print("\n数据验证通过!")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate LN2 inventory data for errors and inconsistencies"
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="Path to inventory YAML")
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors")
    args = parser.parse_args()

    try:
        data = load_yaml(args.yaml)
    except Exception as e:
        print(f"错误: 无法加载 YAML 文件: {e}")
        return 1

    errors, warnings = validate_inventory(data)

    if args.strict and warnings:
        errors.extend(warnings)
        warnings = []

    return print_validation_results(errors, warnings)


if __name__ == "__main__":
    sys.exit(main())
