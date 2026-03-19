#!/usr/bin/env python3
"""验证版本号一致性。"""
import json
import re
from pathlib import Path


def main():
    repo_root = Path(__file__).parent.parent

    # 1. 从 app_gui/version.py 提取版本（权威来源）
    version_py = repo_root / 'app_gui/version.py'
    version_content = version_py.read_text(encoding='utf-8')
    main_version = re.search(r'APP_VERSION.*?=.*?"([\d.]+)"', version_content)
    if not main_version:
        print("[ERROR] 无法从 app_gui/version.py 提取版本号")
        return 1
    main_ver = main_version.group(1)

    # 2. 从 latest.json 读取版本
    latest_json = repo_root / 'latest.json'
    with open(latest_json, encoding='utf-8') as f:
        latest_data = json.load(f)
    latest_ver = latest_data['version']
    latest_url = latest_data.get('download_url', '')

    # 3. 从 CHANGELOG.md 读取最新版本
    changelog = repo_root / 'CHANGELOG.md'
    changelog_content = changelog.read_text(encoding='utf-8')
    changelog_version = re.search(r'^##\s+([\d.]+)', changelog_content, re.MULTILINE)
    if not changelog_version:
        print("[ERROR] 无法从 CHANGELOG.md 提取版本号")
        return 1
    changelog_ver = changelog_version.group(1)

    # 4. 从 Inno Setup 脚本读取默认版本
    iss_file = repo_root / 'installer/windows/LN2InventoryAgent.iss'
    iss_content = iss_file.read_text(encoding='utf-8')
    iss_version = re.search(r'#define MyAppVersion "([\d.]+)"', iss_content)
    if not iss_version:
        print("[ERROR] 无法从 installer/windows/LN2InventoryAgent.iss 提取默认版本号")
        return 1
    iss_ver = iss_version.group(1)

    download_url_ok = main_ver in str(latest_url)

    # 比较版本号
    print("[版本号检查]")
    print(f"  version.py:    {main_ver}")
    print(f"  latest.json:   {latest_ver}")
    print(f"  CHANGELOG.md:  {changelog_ver}")
    print(f"  installer.iss: {iss_ver}")
    print(f"  download_url:  {latest_url}")
    print()

    if main_ver == latest_ver == changelog_ver == iss_ver and download_url_ok:
        print(f"[OK] 所有版本号一致: {main_ver}")
        return 0
    else:
        print("[ERROR] 版本号不一致!")
        if main_ver != latest_ver:
            print(f"  [WARN] version.py ({main_ver}) != latest.json ({latest_ver})")
        if main_ver != changelog_ver:
            print(f"  [WARN] version.py ({main_ver}) != CHANGELOG.md ({changelog_ver})")
        if latest_ver != changelog_ver:
            print(f"  [WARN] latest.json ({latest_ver}) != CHANGELOG.md ({changelog_ver})")
        if main_ver != iss_ver:
            print(f"  [WARN] version.py ({main_ver}) != installer.iss ({iss_ver})")
        if not download_url_ok:
            print(f"  [WARN] latest.json download_url 未包含版本号 {main_ver}")
        return 1

if __name__ == '__main__':
    exit(main())
