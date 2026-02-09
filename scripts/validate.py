#!/usr/bin/env python3
"""Validate LN2 inventory data for errors and inconsistencies."""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import YAML_PATH
from lib.validators import (
    has_depletion_history as _has_depletion_history,
    validate_inventory as _validate_inventory,
    validate_record as _validate_record,
)
from lib.yaml_ops import load_yaml


def has_depletion_history(rec):
    """Compatibility export for tests and external callers."""
    return _has_depletion_history(rec)


def validate_record(rec, idx, layout=None):
    """Compatibility wrapper around lib.validators.validate_record.

    ``layout`` is ignored because canonical validation now derives ranges
    from config and shared validators.
    """
    _ = layout
    return _validate_record(rec, idx=idx)


def validate_inventory(data):
    """Compatibility export for script-level validation."""
    return _validate_inventory(data)


def print_validation_results(errors, warnings):
    """Print validation results."""
    print("\n" + "=" * 60)
    print("数据验证报告")
    print("=" * 60)

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

    print("\n" + "=" * 60)

    if errors:
        print("\n建议: 修复上述错误以确保数据完整性")
        return 1
    if warnings:
        print("\n建议: 检查上述警告，确认是否需要修改")
        return 0

    print("\n数据验证通过!")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate LN2 inventory data for errors and inconsistencies"
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="Path to inventory YAML")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    try:
        data = load_yaml(args.yaml)
    except Exception as exc:
        print(f"错误: 无法加载 YAML 文件: {exc}")
        return 1

    errors, warnings = validate_inventory(data)

    if args.strict and warnings:
        errors.extend(warnings)
        warnings = []

    return print_validation_results(errors, warnings)


if __name__ == "__main__":
    sys.exit(main())
