#!/usr/bin/env python3
"""验证版本号一致性"""
import json
import re
from pathlib import Path

def main():
    repo_root = Path(__file__).parent.parent
    
    # 1. 从 app_gui/version.py 提取版本（权威来源）
    version_py = repo_root / 'app_gui/version.py'
    version_content = version_py.read_text()
    main_version = re.search(r'APP_VERSION.*?=.*?"([\d.]+)"', version_content)
    if not main_version:
        print("❌ 无法从 app_gui/version.py 提取版本号")
        return 1
    main_ver = main_version.group(1)
    
    # 2. 从 latest.json 读取版本
    latest_json = repo_root / 'latest.json'
    with open(latest_json) as f:
        latest_data = json.load(f)
    latest_ver = latest_data['version']
    
    # 3. 从 CHANGELOG.md 读取最新版本
    changelog = repo_root / 'CHANGELOG.md'
    changelog_content = changelog.read_text()
    changelog_version = re.search(r'^##\s+([\d.]+)', changelog_content, re.MULTILINE)
    if not changelog_version:
        print("❌ 无法从 CHANGELOG.md 提取版本号")
        return 1
    changelog_ver = changelog_version.group(1)
    
    # 比较版本号
    print(f"📋 版本号检查:")
    print(f"  version.py:    {main_ver}")
    print(f"  latest.json:   {latest_ver}")
    print(f"  CHANGELOG.md:  {changelog_ver}")
    print()

    if main_ver == latest_ver == changelog_ver:
        print(f"✅ 所有版本号一致: {main_ver}")
        return 0
    else:
        print("❌ 版本号不一致!")
        if main_ver != latest_ver:
            print(f"  ⚠️  version.py ({main_ver}) != latest.json ({latest_ver})")
        if main_ver != changelog_ver:
            print(f"  ⚠️  version.py ({main_ver}) != CHANGELOG.md ({changelog_ver})")
        if latest_ver != changelog_ver:
            print(f"  ⚠️  latest.json ({latest_ver}) != CHANGELOG.md ({changelog_ver})")
        return 1

if __name__ == '__main__':
    exit(main())
