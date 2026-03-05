#!/usr/bin/env python3
"""从 CHANGELOG.md 自动提取并更新网站的历史版本列表"""
import re
from pathlib import Path

def extract_versions_from_changelog(changelog_path):
    """从 CHANGELOG.md 提取版本号列表"""
    content = changelog_path.read_text()
    
    # 匹配 "## 1.3.3 - 2026-03-05" 格式
    pattern = r'^##\s+(\d+\.\d+\.\d+)'
    versions = re.findall(pattern, content, re.MULTILINE)
    
    return versions

def generate_history_html(versions, max_count=5):
    """生成 download.html 的历史版本 HTML"""
    if not versions or len(versions) < 2:
        return None
    
    # 跳过最新版（第一个），只保留历史版本
    history_versions = versions[1:max_count+1]
    
    html_lines = []
    for ver in history_versions:
        url = f"https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-{ver}.exe"
        html_lines.append(
            f'                <a class="btn ghost history-link" href="{url}" '
            f'target="_blank" rel="noopener">v{ver}</a>'
        )
    
    return '\n'.join(html_lines)

def main():
    repo_root = Path(__file__).parent.parent
    website_dir = Path('/var/www/snowfox.bio')
    
    # 1. 从 CHANGELOG.md 提取版本
    changelog = repo_root / 'CHANGELOG.md'
    if not changelog.exists():
        print("❌ CHANGELOG.md 不存在")
        return 1
    
    versions = extract_versions_from_changelog(changelog)
    if not versions:
        print("❌ 未找到版本号")
        return 1
    
    print(f"📋 发现版本: {', '.join(versions)}")
    
    # 2. 生成历史版本 HTML
    history_html = generate_history_html(versions)
    if not history_html:
        print("⚠️  历史版本不足，跳过更新")
        return 0
    
    # 3. 更新 download.html
    download_file = website_dir / 'assets/partials/download.html'
    if not download_file.exists():
        print("❌ download.html 不存在")
        return 1
    
    content = download_file.read_text()
    
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
    
    download_file.write_text(new_content)
    print(f"✅ 已更新历史版本列表到 {download_file}")
    
    return 0

if __name__ == '__main__':
    exit(main())
