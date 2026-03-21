#!/usr/bin/env python3
"""从 CHANGELOG.md 顶部条目生成 latest.json.release_notes 与 GitHub Release 文档。"""

from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path


SECTION_LABELS = {
    "Added": "新增",
    "Changed": "改进",
    "Fixed": "修复",
}
PLATFORM_LABELS = {
    "windows": "Windows",
    "macos": "macOS",
}


def parse_latest_release(changelog_path: Path) -> dict[str, object]:
    content = changelog_path.read_text(encoding="utf-8")
    match = re.search(r"^##\s+(\d+\.\d+\.\d+)\s+-\s+(\d{4}-\d{2}-\d{2})\s*$", content, re.MULTILINE)
    if not match:
        raise SystemExit("未在 CHANGELOG.md 顶部找到版本标题，期望格式: ## <version> - <date>")

    version = match.group(1)
    release_date = match.group(2)
    start = match.end()
    next_match = re.search(r"^##\s+\d+\.\d+\.\d+\s+-\s+\d{4}-\d{2}-\d{2}\s*$", content[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(content)
    body = content[start:end].strip()

    sections: "OrderedDict[str, list[str]]" = OrderedDict()
    current_section = None

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section_match = re.match(r"^###\s+(.+?)\s*$", line)
        if section_match:
            current_section = section_match.group(1)
            sections.setdefault(current_section, [])
            continue

        if line.startswith("- "):
            if current_section is None:
                current_section = "Changed"
                sections.setdefault(current_section, [])
            sections[current_section].append(line[2:].strip())
            continue

        if current_section is None:
            current_section = "Changed"
            sections.setdefault(current_section, [])
        sections[current_section].append(line)

    if not sections:
        raise SystemExit("CHANGELOG.md 顶部条目没有可用内容")

    return {
        "version": version,
        "release_date": release_date,
        "sections": sections,
    }


def build_release_notes(version: str, sections: "OrderedDict[str, list[str]]") -> str:
    lines = [f"SnowFox {version} 更新内容："]
    for section_name, items in sections.items():
        if not items:
            continue
        label = SECTION_LABELS.get(section_name, section_name)
        lines.append(label)
        lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def collect_download_entries(latest_payload: dict[str, object]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    platforms = latest_payload.get("platforms")
    if isinstance(platforms, dict):
        for platform_key in ("windows", "macos"):
            value = platforms.get(platform_key)
            if not isinstance(value, dict):
                continue
            download_url = str(value.get("download_url", "")).strip()
            if not download_url:
                continue
            entries.append((PLATFORM_LABELS.get(platform_key, platform_key), download_url))
    if entries:
        return entries

    legacy_url = str(latest_payload.get("download_url", "")).strip()
    if legacy_url:
        return [(PLATFORM_LABELS["windows"], legacy_url)]
    return []


def build_github_release(
    version: str,
    release_date: str,
    download_entries: list[tuple[str, str]],
    sections: "OrderedDict[str, list[str]]",
) -> str:
    lines = [
        f"# SnowFox v{version}",
        "",
        f"发布日期：{release_date}",
        "",
        "> 本文由 `scripts/render_release_artifacts.py` 从 `CHANGELOG.md` 自动生成。",
        "",
        "## 下载",
        "",
    ]

    if download_entries:
        lines.extend(f"- {label} 安装包：`{url}`" for label, url in download_entries)
        lines.append("")

    lines.extend([
        "## 本次更新",
        "",
    ])

    for section_name, items in sections.items():
        if not items:
            continue
        label = SECTION_LABELS.get(section_name, section_name)
        lines.append(f"### {label}")
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="期望版本号，用于校验 CHANGELOG 与 latest.json 是否一致")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    changelog_path = repo_root / "CHANGELOG.md"
    latest_json_path = repo_root / "latest.json"
    docs_release_dir = repo_root / "docs" / "releases"

    release = parse_latest_release(changelog_path)
    version = str(release["version"])
    release_date = str(release["release_date"])
    sections = release["sections"]

    if args.version and args.version != version:
        raise SystemExit(f"CHANGELOG 顶部版本是 {version}，与期望版本 {args.version} 不一致")

    latest_payload = json.loads(latest_json_path.read_text(encoding="utf-8"))
    latest_version = str(latest_payload.get("version", "")).strip()
    if latest_version != version:
        raise SystemExit(f"latest.json 版本是 {latest_version}，与 CHANGELOG 顶部版本 {version} 不一致")

    platforms = latest_payload.get("platforms")
    if isinstance(platforms, dict):
        windows_payload = platforms.get("windows")
        if isinstance(windows_payload, dict):
            windows_url = str(windows_payload.get("download_url", "")).strip()
            if windows_url:
                latest_payload["download_url"] = windows_url

    latest_payload["release_notes"] = build_release_notes(version, sections)
    latest_json_path.write_text(
        json.dumps(latest_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    docs_release_dir.mkdir(parents=True, exist_ok=True)
    github_release_path = docs_release_dir / f"v{version}-github-release.md"
    github_release_path.write_text(
        build_github_release(version, release_date, collect_download_entries(latest_payload), sections),
        encoding="utf-8",
    )

    print(f"[OK] 已更新 latest.json.release_notes -> v{version}")
    print(f"[OK] 已生成 GitHub Release 文档 -> {github_release_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
