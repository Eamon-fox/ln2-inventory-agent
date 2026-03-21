#!/bin/bash
# SnowFox 发布脚本
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OSS_BASE_URL="https://snowfox-release.oss-cn-beijing.aliyuncs.com"

echo "🦊 SnowFox 发布脚本"
echo "=================="

if ! git diff-index --quiet HEAD --; then
    echo "❌ 存在未提交的更改，请先提交"
    exit 1
fi

CURRENT_VERSION="$(python3 -c "import pathlib, re; content = pathlib.Path('app_gui/version.py').read_text(encoding='utf-8'); match = re.search(r'APP_VERSION[^=]*=\\s*[\\\"\\']([^\\\"\\']+)[\\\"\\']', content); print(match.group(1) if match else '')")"
echo "📦 当前版本: $CURRENT_VERSION"
echo ""

read -p "请输入新版本号 (如 1.3.6): " NEW_VERSION
if [[ -z "$NEW_VERSION" ]]; then
    echo "❌ 版本号不能为空"
    exit 1
fi

WINDOWS_ASSET="SnowFox-Setup-$NEW_VERSION.exe"
MACOS_ASSET="SnowFox-$NEW_VERSION-macOS.pkg"
WINDOWS_URL="$OSS_BASE_URL/$WINDOWS_ASSET"
MACOS_URL="$OSS_BASE_URL/$MACOS_ASSET"

echo ""
echo "📝 将执行以下步骤:"
echo "  1. 更新 app_gui/version.py 中的 APP_VERSION"
echo "  2. 更新 installer/windows/LN2InventoryAgent.iss 的默认版本"
echo "  3. 更新 latest.json（保留兼容 download_url + 双平台 platforms）"
echo "  4. 提醒你更新 CHANGELOG.md"
echo "  5. 从 CHANGELOG 生成更新说明产物"
echo "  6. 跑双平台版本一致性检查"
echo "  7. 构建 / 确认 Windows 与 macOS 安装包"
echo "  8. 上传 OSS（Windows / macOS / latest.json / CHANGELOG.md）"
echo "  9. 在 OSS 上传完成后同步网站"
echo ""

read -p "确认发布 v$NEW_VERSION? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 已取消"
    exit 1
fi

echo ""
echo "1️⃣  更新 version.py..."
python3 - <<PY
from pathlib import Path
import re

path = Path("app_gui/version.py")
content = path.read_text(encoding="utf-8")
updated = re.sub(
    r'(APP_VERSION[^=]*=\s*["\\\'])[^"\\\']+(["\\\'])',
    rf"\\g<1>{NEW_VERSION}\\2",
    content,
    count=1,
)
path.write_text(updated, encoding="utf-8")
PY

echo "2️⃣  更新 LN2InventoryAgent.iss..."
python3 - <<PY
from pathlib import Path
import re

path = Path("installer/windows/LN2InventoryAgent.iss")
content = path.read_text(encoding="utf-8")
updated = re.sub(
    r'(#define MyAppVersion ")\d+\.\d+\.\d+(")',
    rf"\\g<1>{NEW_VERSION}\\2",
    content,
    count=1,
)
path.write_text(updated, encoding="utf-8")
PY

echo "3️⃣  更新 latest.json..."
python3 - <<PY
import json
from pathlib import Path

path = Path("latest.json")
data = json.loads(path.read_text(encoding="utf-8"))
data["version"] = "${NEW_VERSION}"
data["download_url"] = "${WINDOWS_URL}"
platforms = data.get("platforms")
if not isinstance(platforms, dict):
    platforms = {}
data["platforms"] = platforms
platforms["windows"] = {
    "download_url": "${WINDOWS_URL}",
    "asset_name": "${WINDOWS_ASSET}",
    "auto_update": True,
}
platforms["macos"] = {
    "download_url": "${MACOS_URL}",
    "asset_name": "${MACOS_ASSET}",
    "auto_update": True,
}
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

echo ""
echo "4️⃣  请手动更新 CHANGELOG.md"
echo "   格式:"
echo ""
echo "## $NEW_VERSION - $(date +%Y-%m-%d)"
echo ""
echo "### Added"
echo "- ..."
echo ""
echo "### Changed"
echo "- ..."
echo ""
echo "### Fixed"
echo "- ..."
echo ""
read -p "已更新 CHANGELOG.md? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 请先更新 CHANGELOG.md"
    exit 1
fi

echo ""
echo "5️⃣  从 CHANGELOG 生成更新说明产物..."
python3 scripts/render_release_artifacts.py --version "$NEW_VERSION"

echo ""
echo "6️⃣  跑双平台版本一致性检查..."
python3 scripts/validate_version.py

echo ""
echo "7️⃣  构建 / 确认安装包..."
echo "   Windows:"
echo "   installer\\windows\\build_installer.bat"
echo "   期望产物: dist/installer/$WINDOWS_ASSET"
echo ""
echo "   macOS:"
echo "   bash installer/mac/build_pkg.sh"
echo "   期望产物: dist/installer/$MACOS_ASSET"
echo ""
read -p "是否已完成 Windows 安装包构建? [y/N] " -n 1 -r
echo
WINDOWS_BUILT=false
if [[ $REPLY =~ ^[Yy]$ ]]; then
    WINDOWS_BUILT=true
else
    echo "⚠️  Windows 安装包尚未确认。"
fi

read -p "是否已完成 macOS 安装包构建? [y/N] " -n 1 -r
echo
MACOS_BUILT=false
if [[ $REPLY =~ ^[Yy]$ ]]; then
    MACOS_BUILT=true
else
    echo "⚠️  macOS 安装包尚未确认。"
fi

echo ""
echo "8️⃣  上传 OSS（完成后才能同步网站）"
echo "   需要上传以下对象:"
echo "   - dist/installer/$WINDOWS_ASSET"
echo "   - dist/installer/$MACOS_ASSET"
echo "   - latest.json"
echo "   - CHANGELOG.md"
echo ""
echo "   推荐顺序:"
echo "   1. Windows 安装包"
echo "   2. macOS 安装包"
echo "   3. latest.json"
echo "   4. CHANGELOG.md"
echo ""
echo "   示例命令:"
echo "   python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py upload-file dist/installer/$WINDOWS_ASSET --bucket snowfox-release"
echo "   python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py upload-file dist/installer/$MACOS_ASSET --bucket snowfox-release"
echo "   python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py upload-file latest.json --bucket snowfox-release"
echo "   python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py upload-file CHANGELOG.md --bucket snowfox-release"
echo ""
read -p "是否已完成 OSS 上传? [y/N] " -n 1 -r
echo
OSS_UPLOADED=false
if [[ $REPLY =~ ^[Yy]$ ]]; then
    OSS_UPLOADED=true
else
    echo "⚠️  暂未同步网站。完成 OSS 上传后，请手动运行: ./scripts/sync-website.sh"
fi

if [[ "$OSS_UPLOADED" == true ]]; then
    echo ""
    echo "9️⃣  同步版本到网站..."
    ./scripts/sync-website.sh
fi

echo ""
echo "🔟  创建 Git 提交..."
git add -A
git commit -m "chore: release v$NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"

echo ""
echo "✅ 发布准备完成!"
echo ""
echo "构建确认:"
echo "  Windows: $WINDOWS_BUILT"
echo "  macOS:   $MACOS_BUILT"
echo ""
echo "下一步:"
if [[ "$OSS_UPLOADED" != true ]]; then
    echo "  1. 先上传 OSS: Windows 安装包 / macOS 安装包 / latest.json / CHANGELOG.md"
    echo "  2. 上传完成后运行: ./scripts/sync-website.sh"
    echo "  3. 推送到 GitHub: git push && git push --tags"
    echo "  4. 在 GitHub 创建 Release"
else
    echo "  1. 推送到 GitHub: git push && git push --tags"
    echo "  2. 在 GitHub 创建 Release"
fi
echo ""
