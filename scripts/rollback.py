#!/usr/bin/env python3
"""
一键回滚液氮库存 YAML 到最近备份。
"""
import argparse
import os
import sys
from datetime import datetime

# Import from lib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.yaml_ops import list_yaml_backups, rollback_yaml


def format_backup_line(path):
    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    size = os.path.getsize(path)
    return f"{mtime} | {size:>8} B | {path}"


def main():
    parser = argparse.ArgumentParser(
        description="Rollback LN2 inventory YAML to latest backup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出可用备份
  python rollback.py --list

  # 一键回滚到最新备份（默认行为）
  python rollback.py

  # 回滚到指定备份文件
  python rollback.py --backup /path/to/ln2_inventory.yaml.20260209-010101.bak
        """,
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML文件路径")
    parser.add_argument("--list", action="store_true", help="列出可用备份并退出")
    parser.add_argument("--backup", help="指定要恢复的备份文件路径")
    parser.add_argument("--no-html", action="store_true", help="回滚后不刷新 HTML 快照")
    parser.add_argument("--no-server", action="store_true", help="回滚后不启动/复用 HTTP 预览服务")
    args = parser.parse_args()

    backups = list_yaml_backups(args.yaml)

    if args.list:
        if not backups:
            print("未找到任何备份。")
            return 0
        print(f"找到 {len(backups)} 个备份（新 -> 旧）:\n")
        for i, p in enumerate(backups, 1):
            print(f"{i:>3}. {format_backup_line(p)}")
        return 0

    if not backups and not args.backup:
        print("❌ 无可用备份，无法回滚。")
        print("   请先执行一次写入操作以生成备份。")
        return 1

    target = args.backup or backups[0]

    try:
        result = rollback_yaml(
            path=args.yaml,
            backup_path=target,
            auto_html=not args.no_html,
            auto_server=not args.no_server,
            audit_meta={
                "action": "rollback",
                "source": "scripts/rollback.py",
                "details": {"requested_backup": target},
            },
        )
    except Exception as exc:
        print(f"❌ 回滚失败: {exc}")
        return 1

    print("✅ 回滚成功")
    print(f"   恢复来源: {result['restored_from']}")
    print(f"   回滚前快照: {result['snapshot_before_rollback']}")
    if result.get("preview_url"):
        print(f"   预览地址: {result['preview_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
