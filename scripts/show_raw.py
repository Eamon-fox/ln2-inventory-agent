#!/usr/bin/env python3
"""
快速展示指定 ID 的完整原始 YAML 数据
用于让用户确认查询结果的准确性
"""

import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.cli_render import print_raw_entries
from lib.config import YAML_PATH
from lib.tool_api import tool_get_raw_entries

def show_raw_entries(yaml_path, ids):
    """展示指定 ID 的原始 YAML 条目"""
    response = tool_get_raw_entries(yaml_path, ids)
    if not response.get("ok"):
        print(response.get("message", f"未找到 ID: {', '.join(map(str, ids))}"))
        return 1

    payload = response["result"]
    results = payload["entries"]

    # 按 ID 排序
    results.sort(key=lambda x: x['id'])

    print_raw_entries(results)

    # 检查是否有缺失的 ID
    missing_ids = set(payload.get("missing_ids", []))
    if missing_ids:
        print(f"\n[WARN]  未找到的 ID: {', '.join(map(str, sorted(missing_ids)))}", file=sys.stderr)
        return 1

    return 0

def main():
    parser = argparse.ArgumentParser(
        description="展示指定 ID 的完整原始 YAML 数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 展示单个条目
  python show_raw.py 168

  # 展示多个条目
  python show_raw.py 166 167 168

  # 指定 YAML 文件
  python show_raw.py 168 --yaml /path/to/file.yaml
        """
    )

    parser.add_argument(
        "ids",
        type=int,
        nargs='+',
        help="要展示的条目 ID（可以指定多个）"
    )

    parser.add_argument(
        "--yaml",
        default=YAML_PATH,
        help="YAML 文件路径（默认: %(default)s）"
    )

    args = parser.parse_args()

    try:
        return show_raw_entries(args.yaml, args.ids)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {args.yaml}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
