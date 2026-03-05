#!/usr/bin/env python3
"""从 latest.json 同步版本号到网站"""
import json
import re
from pathlib import Path

def main():
    repo_root = Path(__file__).parent.parent
    website_dir = Path('/var/www/snowfox.bio')
    
    # 读取版本信息
    latest_file = repo_root / 'latest.json'
    if not latest_file.exists():
        print("❌ latest.json 不存在")
        return 1
    
    with open(latest_file) as f:
        version_info = json.load(f)
    
    version = version_info['version']
    download_url = version_info['download_url']
    
    print(f"📦 版本: {version}")
    print(f"🔗 URL: {download_url}")
    
    # 1. 更新 hero.html
    hero_file = website_dir / 'assets/partials/hero.html'
    if hero_file.exists():
        hero_content = hero_file.read_text()
        hero_content = re.sub(
            r'href="https://snowfox-release\.oss[^"]*"',
            f'href="{download_url}"',
            hero_content
        )
        hero_file.write_text(hero_content)
        print(f"✅ 已更新 {hero_file}")
    
    # 2. 更新 download.html - 最新版下载链接
    download_file = website_dir / 'assets/partials/download.html'
    if download_file.exists():
        download_content = download_file.read_text()
        
        # 更新所有 OSS 链接
        download_content = re.sub(
            r'href="https://snowfox-release\.oss[^"]*"',
            f'href="{download_url}"',
            download_content
        )
        
        # 更新版本号显示
        download_content = re.sub(
            r'SnowFox v[\d.]+',
            f'SnowFox v{version}',
            download_content
        )
        
        download_file.write_text(download_content)
        print(f"✅ 已更新 {download_file}")
    
    print(f"\n🎉 版本 {version} 已同步到网站")
    return 0

if __name__ == '__main__':
    exit(main())
