#!/usr/bin/env python3
"""从 CHANGELOG.md 自动提取并更新网站的历史版本列表。"""
import html
import re
from pathlib import Path

_ENTRY_PATTERN = re.compile(
    r'^##\s+(?P<version>\d+\.\d+\.\d+)\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$',
    re.MULTILINE,
)


def _build_summary(body, max_items=3, max_chars=140):
    """从 changelog 正文提取简短摘要，用于历史版本 list 的 title 提示。"""
    bullets = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        item = re.sub(r"\s+", " ", line[2:]).strip().rstrip(".。")
        if item:
            bullets.append(item)
        if len(bullets) >= max_items:
            break

    if not bullets:
        return ""

    summary = "；".join(bullets)
    if len(summary) > max_chars:
        return summary[: max_chars - 3].rstrip() + "..."
    return summary


def extract_releases_from_changelog(changelog_path):
    """从 CHANGELOG.md 提取版本、日期和简短摘要。"""
    content = changelog_path.read_text(encoding="utf-8")
    matches = list(_ENTRY_PATTERN.finditer(content))
    releases = []

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        body = content[start:end]
        releases.append(
            {
                "version": match.group("version"),
                "date": match.group("date"),
                "summary": _build_summary(body),
            }
        )

    return releases


def extract_versions_from_changelog(changelog_path):
    """兼容旧调用方，只返回版本号列表。"""
    return [release["version"] for release in extract_releases_from_changelog(changelog_path)]


def generate_history_html(releases, max_count=5):
    """生成 download.html 的历史版本 HTML。"""
    if not releases or len(releases) < 2:
        return None

    history_releases = releases[1 : max_count + 1]

    html_lines = []
    for release in history_releases:
        version = release["version"]
        release_date = release["date"]
        summary = release["summary"]
        url = f"https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-{version}.exe"
        label = f"v{version} · {release_date}"
        title = f"{release_date} | {summary}" if summary else release_date
        html_lines.append(
            f'                <a class="btn ghost history-link" href="{url}" '
            f'target="_blank" rel="noopener" title="{html.escape(title, quote=True)}">'
            f'{html.escape(label)}</a>'
        )

    return "\n".join(html_lines)

def main():
    repo_root = Path(__file__).parent.parent
    website_dir = Path('/var/www/snowfox.bio')
    
    # 1. 从 CHANGELOG.md 提取版本
    changelog = repo_root / 'CHANGELOG.md'
    if not changelog.exists():
        print("❌ CHANGELOG.md 不存在")
        return 1
    
    releases = extract_releases_from_changelog(changelog)
    if not releases:
        print("❌ 未找到版本号")
        return 1

    print(f"📋 发现版本: {', '.join(release['version'] for release in releases)}")

    # 2. 生成历史版本 HTML
    history_html = generate_history_html(releases)
    if not history_html:
        print("⚠️  历史版本不足，跳过更新")
        return 0
    
    # 3. 更新 download.html
    download_file = website_dir / 'assets/partials/download.html'
    if not download_file.exists():
        print("❌ download.html 不存在")
        return 1
    
    content = download_file.read_text(encoding="utf-8")

    # 替换历史版本区域
    pattern = r'(<div class="history-list">)(.*?)(</div>)'
    
    def replace_history(match):
        return f'{match.group(1)}\n{history_html}\n              {match.group(3)}'
    
    new_content = re.sub(
        pattern, 
        replace_history, 
        content, 
        flags=re.DOTALL
    )
    
    if new_content == content:
        print("⚠️  未找到历史版本区域，跳过更新")
        return 0
    
    download_file.write_text(new_content, encoding="utf-8")
    print(f"✅ 已更新历史版本列表到 {download_file}")

    return 0

if __name__ == '__main__':
    exit(main())
