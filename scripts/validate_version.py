#!/usr/bin/env python3
"""验证版本号与双平台发布元数据一致性。"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _extract_version(path: Path, pattern: str, *, label: str) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        raise SystemExit(f"[ERROR] 无法从 {label} 提取版本号")
    return match.group(1)


def _expected_assets(version: str) -> dict[str, str]:
    return {
        "windows": f"SnowFox-Setup-{version}.exe",
        "macos": f"SnowFox-{version}-macOS.pkg",
    }


def _platform_entry_ok(entry: object, *, expected_asset: str, version: str) -> tuple[bool, str, str]:
    if not isinstance(entry, dict):
        return False, "", ""

    asset_name = str(entry.get("asset_name", "")).strip()
    download_url = str(entry.get("download_url", "")).strip()
    ok = (
        bool(asset_name)
        and bool(download_url)
        and asset_name == expected_asset
        and version in asset_name
        and version in download_url
        and download_url.endswith(asset_name)
    )
    return ok, asset_name, download_url


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    main_ver = _extract_version(
        repo_root / "app_gui/version.py",
        r'APP_VERSION[^=]*=\s*"([\d.]+)"',
        label="app_gui/version.py",
    )
    latest_payload = json.loads((repo_root / "latest.json").read_text(encoding="utf-8"))
    latest_ver = str(latest_payload.get("version", "")).strip()
    changelog_ver = _extract_version(
        repo_root / "CHANGELOG.md",
        r"^##\s+([\d.]+)",
        label="CHANGELOG.md",
    )
    iss_ver = _extract_version(
        repo_root / "installer/windows/LN2InventoryAgent.iss",
        r'#define MyAppVersion "([\d.]+)"',
        label="installer/windows/LN2InventoryAgent.iss",
    )

    expected_assets = _expected_assets(main_ver)
    platforms = latest_payload.get("platforms")
    if not isinstance(platforms, dict):
        print("[ERROR] latest.json 缺少 platforms 字段")
        return 1

    windows_ok, windows_asset, windows_url = _platform_entry_ok(
        platforms.get("windows"),
        expected_asset=expected_assets["windows"],
        version=main_ver,
    )
    macos_ok, macos_asset, macos_url = _platform_entry_ok(
        platforms.get("macos"),
        expected_asset=expected_assets["macos"],
        version=main_ver,
    )
    legacy_download_url = str(latest_payload.get("download_url", "")).strip()
    legacy_ok = legacy_download_url == windows_url and main_ver in legacy_download_url

    print("[版本号检查]")
    print(f"  version.py:             {main_ver}")
    print(f"  latest.json:            {latest_ver}")
    print(f"  CHANGELOG.md:           {changelog_ver}")
    print(f"  installer.iss:          {iss_ver}")
    print(f"  latest.download_url:    {legacy_download_url}")
    print(f"  platforms.windows:      {windows_asset} -> {windows_url}")
    print(f"  platforms.macos:        {macos_asset} -> {macos_url}")
    print()

    version_ok = main_ver == latest_ver == changelog_ver == iss_ver
    if version_ok and windows_ok and macos_ok and legacy_ok:
        print(f"[OK] 双平台版本元数据一致: {main_ver}")
        return 0

    print("[ERROR] 版本元数据不一致!")
    if not version_ok:
        if main_ver != latest_ver:
            print(f"  [WARN] version.py ({main_ver}) != latest.json ({latest_ver})")
        if main_ver != changelog_ver:
            print(f"  [WARN] version.py ({main_ver}) != CHANGELOG.md ({changelog_ver})")
        if main_ver != iss_ver:
            print(f"  [WARN] version.py ({main_ver}) != installer.iss ({iss_ver})")
    if not windows_ok:
        print(
            "  [WARN] latest.json.platforms.windows 与预期不一致，"
            f"期望 {expected_assets['windows']}"
        )
    if not macos_ok:
        print(
            "  [WARN] latest.json.platforms.macos 与预期不一致，"
            f"期望 {expected_assets['macos']}"
        )
    if not legacy_ok:
        print("  [WARN] latest.json.download_url 必须保留为 Windows 安装包链接以兼容旧客户端")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
