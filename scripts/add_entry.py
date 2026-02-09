#!/usr/bin/env python3
"""
添加新的冻存记录
"""
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH, VALID_CELL_LINES, BOX_RANGE
from lib.yaml_ops import load_yaml, write_yaml
from lib.validators import validate_date, parse_positions
from lib.operations import get_next_id, check_position_conflicts


def add_entry(
    yaml_path,
    parent_cell_line,
    short_name,
    box,
    positions,
    frozen_at,
    plasmid_name=None,
    plasmid_id=None,
    note=None,
    dry_run=False
):
    """
    添加新的冻存记录

    Args:
        yaml_path: YAML文件路径
        parent_cell_line: 亲本细胞系名称
        short_name: 简称
        box: 盒子编号 1-5
        positions: 位置列表
        frozen_at: 冻存日期 YYYY-MM-DD
        plasmid_name: 质粒名称（可选）
        plasmid_id: 质粒ID（可选）
        note: 备注（可选）
        dry_run: 是否只预览不实际修改
    """
    # 验证参数
    if VALID_CELL_LINES and parent_cell_line not in VALID_CELL_LINES:
        print(f"❌ 错误: parent_cell_line 必须是以下之一:")
        for cl in VALID_CELL_LINES:
            print(f"   - {cl}")
        print(f"\n   你输入的是: {parent_cell_line!r}")
        print(f"   如需新增细胞系，请在配置文件中更新 schema.valid_cell_lines")
        return 1

    if not validate_date(frozen_at):
        print(f"❌ 错误: 日期格式无效，请使用 YYYY-MM-DD 格式（如 2026-01-08）")
        return 1

    if box < BOX_RANGE[0] or box > BOX_RANGE[1]:
        print(f"❌ 错误: 盒子编号必须在 {BOX_RANGE[0]}-{BOX_RANGE[1]} 之间")
        return 1

    if not positions:
        print(f"❌ 错误: 必须指定至少一个位置")
        return 1

    # 加载数据
    try:
        data = load_yaml(yaml_path)
    except Exception as e:
        print(f"❌ 错误: 无法读取YAML文件: {e}")
        return 1

    records = data.get("inventory", [])

    # 检查位置冲突
    conflicts = check_position_conflicts(records, box, positions)
    if conflicts:
        print(f"\n❌ 错误: 位置冲突！以下位置已被占用:\n")
        for conf in conflicts:
            print(f"  - ID {conf['id']} ({conf['short_name']}): 位置 {conf['positions']}")
        print(f"\n请使用其他位置或运行 'python query_inventory.py --empty --box {box}' 查看空位\n")
        return 1

    # 生成新ID
    new_id = get_next_id(records)

    # 创建新记录
    new_record = {
        "id": new_id,
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "plasmid_name": plasmid_name,
        "plasmid_id": plasmid_id,
        "box": box,
        "positions": positions,
        "frozen_at": frozen_at,
        "thaw_log": None,
        "note": note
    }

    # 显示预览
    print(f"\n{'=' * 60}")
    print(f"📋 新记录预览")
    print(f"{'=' * 60}")
    print(f"ID:          {new_id} (自动分配)")
    print(f"细胞系:      {parent_cell_line}")
    print(f"简称:        {short_name}")
    print(f"质粒名称:    {plasmid_name or '(未指定)'}")
    print(f"质粒ID:      {plasmid_id or '(未指定)'}")
    print(f"盒子:        {box}")
    print(f"位置:        {positions}")
    print(f"冻存日期:    {frozen_at}")
    print(f"备注:        {note or '(无)'}")
    print(f"{'=' * 60}\n")

    if dry_run:
        print("ℹ️  这是预览模式，未实际修改文件")
        print("   移除 --dry-run 参数以执行实际添加\n")
        return 0

    # 执行添加
    try:
        records.append(new_record)

        # 写入文件
        write_yaml(
            data,
            yaml_path,
            audit_meta={
                "action": "add_entry",
                "source": "scripts/add_entry.py",
                "details": {
                    "new_id": new_id,
                    "box": box,
                    "positions": positions,
                    "parent_cell_line": parent_cell_line,
                    "short_name": short_name,
                },
            },
        )

        print(f"✅ 成功！新记录已添加")
        print(f"✅ 占用位置信息已自动重建")
        print(f"\n新记录 ID: {new_id}\n")
        return 0

    except Exception as e:
        print(f"❌ 错误: 添加失败: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="添加新的液氮罐冻存记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 添加基本记录
  python add_entry.py \\
    --parent-cell-line "K562" \\
    --short-name "C-ABL1-dTAG-clone12" \\
    --box 1 \\
    --positions "30,31" \\
    --frozen-at "2026-01-08"

  # 添加完整信息的记录
  python add_entry.py \\
    --parent-cell-line "K562" \\
    --short-name "N-RTCB-dTAG-clone11" \\
    --plasmid-name "pGEMT-N-RTCB-dTAG" \\
    --plasmid-id "p260101-1" \\
    --box 2 \\
    --positions "70-72" \\
    --frozen-at "2026-01-08" \\
    --note "纯合单克隆"

  # 预览模式
  python add_entry.py \\
    --parent-cell-line "K562" \\
    --short-name "test" \\
    --box 1 \\
    --positions "1,2,3" \\
    --frozen-at "2026-01-08" \\
    --dry-run

位置格式:
  单个: "30"
  多个: "30,31,32"
  范围: "30-32" (等同于 "30,31,32")
        """
    )

    # 必填参数
    parser.add_argument(
        "--parent-cell-line",
        type=str,
        required=True,
        help="亲本细胞系名称（必填）"
    )
    parser.add_argument(
        "--short-name",
        type=str,
        required=True,
        help="细胞系简称（必填）"
    )
    parser.add_argument(
        "--box",
        type=int,
        required=True,
        choices=list(range(BOX_RANGE[0], BOX_RANGE[1] + 1)),
        help=f"盒子编号 {BOX_RANGE[0]}-{BOX_RANGE[1]}（必填）"
    )
    parser.add_argument(
        "--positions",
        type=str,
        required=True,
        help="位置列表，格式: '1,2,3' 或 '1-3'（必填）"
    )
    parser.add_argument(
        "--frozen-at",
        type=str,
        required=True,
        help="冻存日期 YYYY-MM-DD（必填，如 2026-01-08）"
    )

    # 可选参数
    parser.add_argument(
        "--plasmid-name",
        type=str,
        help="质粒名称（可选）"
    )
    parser.add_argument(
        "--plasmid-id",
        type=str,
        help="质粒ID（可选）"
    )
    parser.add_argument(
        "--note",
        type=str,
        help="备注信息（可选）"
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")

    args = parser.parse_args()

    # 解析位置
    try:
        positions = parse_positions(args.positions)
    except ValueError as e:
        print(f"❌ 错误: {e}\n")
        parser.print_help()
        return 1

    return add_entry(
        args.yaml,
        args.parent_cell_line,
        args.short_name,
        args.box,
        positions,
        args.frozen_at,
        args.plasmid_name,
        args.plasmid_id,
        args.note,
        args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
