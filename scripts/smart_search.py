#!/usr/bin/env python3
"""
智能搜索：自动处理搜索关键词，给出最佳结果
- 自动去除不必要的空格和特殊字符
- 支持分词搜索（多个关键词都要匹配）
- 显示搜索建议
"""

import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH, PYTHON_PATH, SCRIPTS_DIR


def normalize_query(query):
    """规范化查询词：去除多余空格，保留有意义的符号"""
    # 保留 # 和 - 等有意义的符号
    return ' '.join(query.split())


def extract_keywords(query):
    """
    从查询中提取关键词
    支持：
    1. 完整字符串匹配
    2. 分词匹配（空格分隔）
    """
    normalized = normalize_query(query)
    # 按空格分词
    keywords = normalized.split()
    return normalized, keywords


def search_record_multi_keywords(rec, keywords):
    """
    多关键词搜索：所有关键词都要匹配（AND逻辑）
    """
    # 将记录转为可搜索的字符串
    searchable_text = []

    fields = [
        'id', 'parent_cell_line', 'short_name',
        'plasmid_name', 'plasmid_id', 'note',
        'thaw_log', 'box', 'frozen_at'
    ]

    for field in fields:
        value = rec.get(field)
        if value:
            searchable_text.append(str(value).lower())

    # positions
    positions = rec.get('positions', [])
    if positions:
        searchable_text.append(','.join(str(p) for p in positions))

    # 合并所有可搜索文本
    full_text = ' '.join(searchable_text)

    # 检查所有关键词是否都出现
    for keyword in keywords:
        if keyword.lower() not in full_text:
            return False

    return True


def search_record_exact(rec, query):
    """精确搜索：完整字符串匹配"""
    query_lower = query.lower()

    fields = [
        'parent_cell_line', 'short_name', 'plasmid_name',
        'plasmid_id', 'note', 'thaw_log'
    ]

    # Search simple fields
    for field in fields:
        value = rec.get(field)
        if value and query_lower in str(value).lower():
            return True

    # Search other fields
    if query_lower in str(rec.get('id', '')).lower():
        return True
    if query_lower in str(rec.get('box', '')).lower():
        return True
    if query_lower in str(rec.get('frozen_at', '')).lower():
        return True

    # Search positions
    positions = rec.get('positions', [])
    if positions:
        pos_str = ','.join(str(p) for p in positions)
        if query_lower in pos_str.lower():
            return True

    return False


def suggest_alternative_queries(query, matches_count):
    """根据搜索结果给出建议"""
    suggestions = []

    if matches_count == 0:
        suggestions.append("💡 尝试使用更短的关键词，如 'reporter' 或 '36'")
        suggestions.append("💡 检查是否有拼写错误")
        suggestions.append("💡 使用 --keywords 模式尝试分词搜索")
    elif matches_count > 50:
        suggestions.append("⚠️  结果太多！建议：")
        suggestions.append("   - 添加更多关键词缩小范围")
        suggestions.append("   - 使用更具体的完整名称")

    return suggestions


def format_record_compact(rec):
    """紧凑格式输出"""
    pos = ",".join(str(p) for p in rec.get("positions") or [])
    return (
        f"ID {rec.get('id'):3d} | 盒{rec.get('box')} | "
        f"位置:[{pos:20s}] | {rec.get('short_name')}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="智能搜索液氮罐库存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
搜索模式:
  1. 默认：精确匹配（完整字符串出现在任意字段）
  2. --keywords：分词搜索（所有关键词都要匹配）

示例:
  # 精确搜索完整名称
  smart_search.py "StitchR reporter-36#"

  # 分词搜索（reporter AND 36 都要匹配）
  smart_search.py "reporter 36" --keywords

  # 显示原始数据
  smart_search.py "reporter 36" --raw
        """
    )

    parser.add_argument("query", help="搜索关键词")
    parser.add_argument(
        "--yaml",
        default=YAML_PATH,
        help="YAML 文件路径"
    )
    parser.add_argument(
        "--keywords", "-k",
        action="store_true",
        help="分词搜索模式（多关键词 AND）"
    )
    parser.add_argument(
        "--raw", "-r",
        action="store_true",
        help="显示找到的记录的完整原始 YAML（自动调用 show_raw.py）"
    )
    parser.add_argument(
        "--max", "-m",
        type=int,
        default=50,
        help="最多显示多少条结果（默认50）"
    )

    args = parser.parse_args()

    data = load_yaml(args.yaml)
    records = data.get("inventory", [])

    # 提取关键词
    normalized_query, keywords = extract_keywords(args.query)

    # 搜索
    if args.keywords:
        print(f"🔍 分词搜索模式：{keywords}")
        matches = [rec for rec in records if search_record_multi_keywords(rec, keywords)]
    else:
        print(f"🔍 精确搜索：'{normalized_query}'")
        matches = [rec for rec in records if search_record_exact(rec, normalized_query)]

    # 结果
    if not matches:
        print(f"\n❌ 未找到匹配的记录")
        for suggestion in suggest_alternative_queries(normalized_query, 0):
            print(suggestion)
        return 1

    print(f"\n✅ 找到 {len(matches)} 条记录")

    # 显示建议
    suggestions = suggest_alternative_queries(normalized_query, len(matches))
    if suggestions:
        print()
        for suggestion in suggestions:
            print(suggestion)
        print()

    # 限制显示数量
    display_matches = matches[:args.max]
    if len(matches) > args.max:
        print(f"\n⚠️  仅显示前 {args.max} 条（共 {len(matches)} 条）\n")

    # 显示结果
    for rec in display_matches:
        print(format_record_compact(rec))

    # 原始数据
    if args.raw and len(display_matches) <= 20:
        print("\n" + "="*60)
        print("📋 原始 YAML 数据:")
        print("="*60 + "\n")

        ids = [rec['id'] for rec in display_matches]

        # 调用 show_raw.py
        import subprocess
        cmd = [
            PYTHON_PATH,
            os.path.join(SCRIPTS_DIR, "show_raw.py")
        ] + [str(i) for i in ids]

        subprocess.run(cmd)
    elif args.raw and len(display_matches) > 20:
        print("\n⚠️  结果超过20条，不自动显示原始数据")
        print(f"💡 手动运行: show_raw.py {' '.join(str(r['id']) for r in display_matches[:10])} ...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
