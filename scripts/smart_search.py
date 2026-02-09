#!/usr/bin/env python3
"""
智能搜索：自动处理搜索关键词，给出最佳结果
- 自动去除不必要的空格和特殊字符
- 支持分词搜索（多个关键词都要匹配）
- 显示搜索建议
"""

import argparse
import sys
import yaml

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.tool_api import tool_get_raw_entries, tool_search_records


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

    # 提取关键词（用于展示）
    normalized_query, keywords = extract_keywords(args.query)

    mode = "keywords" if args.keywords else "exact"
    response = tool_search_records(
        yaml_path=args.yaml,
        query=args.query,
        mode=mode,
        max_results=args.max,
    )
    if not response.get("ok"):
        print(f"❌ 错误: {response.get('message', '搜索失败')}")
        return 1

    payload = response["result"]
    matches = payload["records"]
    total_count = payload["total_count"]

    if args.keywords:
        print(f"🔍 分词搜索模式：{keywords}")
    else:
        print(f"🔍 精确搜索：'{normalized_query}'")

    # 结果
    if total_count == 0:
        print(f"\n❌ 未找到匹配的记录")
        for suggestion in payload.get("suggestions", suggest_alternative_queries(normalized_query, 0)):
            print(suggestion)
        return 1

    print(f"\n✅ 找到 {total_count} 条记录")

    # 显示建议
    suggestions = payload.get("suggestions", suggest_alternative_queries(normalized_query, total_count))
    if suggestions:
        print()
        for suggestion in suggestions:
            print(suggestion)
        print()

    display_matches = matches
    if total_count > len(display_matches):
        print(f"\n⚠️  仅显示前 {len(display_matches)} 条（共 {total_count} 条）\n")

    # 显示结果
    for rec in display_matches:
        print(format_record_compact(rec))

    # 原始数据
    if args.raw and len(display_matches) <= 20:
        print("\n" + "="*60)
        print("📋 原始 YAML 数据:")
        print("="*60 + "\n")

        ids = [rec['id'] for rec in display_matches]

        raw_response = tool_get_raw_entries(args.yaml, ids)
        if not raw_response.get("ok"):
            print(f"❌ {raw_response.get('message', '获取原始数据失败')}")
            return 1

        for i, entry in enumerate(raw_response["result"]["entries"]):
            if i > 0:
                print()
            print(f"# === ID {entry['id']} ===")
            yaml_str = yaml.dump([entry], allow_unicode=True, default_flow_style=False, sort_keys=False)
            lines = yaml_str.split('\n')
            if lines and lines[0].startswith('- '):
                lines[0] = lines[0][2:]
            for line in lines:
                if line:
                    if line.startswith('  '):
                        print(line[2:])
                    else:
                        print(line)

        missing = raw_response["result"].get("missing_ids", [])
        if missing:
            print(f"\n⚠️  未找到的 ID: {', '.join(str(i) for i in missing)}", file=sys.stderr)
    elif args.raw and len(display_matches) > 20:
        print("\n⚠️  结果超过20条，不自动显示原始数据")
        print(f"💡 手动运行: show_raw.py {' '.join(str(r['id']) for r in display_matches[:10])} ...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
