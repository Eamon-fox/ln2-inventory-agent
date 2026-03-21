#!/bin/bash
# SnowFox 发布脚本
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "🦊 SnowFox 发布脚本"
echo "=================="

# 检查是否有未提交的更改
if ! git diff-index --quiet HEAD --; then
    echo "❌ 存在未提交的更改，请先提交"
    exit 1
fi

# 读取当前版本（以 app_gui/version.py 为权威来源）
CURRENT_VERSION=$(python3 -c "import pathlib, re; content = pathlib.Path('app_gui/version.py').read_text(encoding='utf-8'); match = re.search(r'APP_VERSION[^=]*=\\s*[\\\"\\']([^\\\"\\']+)[\\\"\\']', content); print(match.group(1) if match else '')")
echo "📦 当前版本: $CURRENT_VERSION"
echo ""

# 提示用户输入新版本号
read -p "请输入新版本号 (如 1.3.4): " NEW_VERSION

if [ -z "$NEW_VERSION" ]; then
    echo "❌ 版本号不能为空"
    exit 1
fi

echo ""
echo "📝 将执行以下步骤:"
echo "  1. 更新 app_gui/version.py 中的 APP_VERSION"
echo "  2. 更新 installer/windows/LN2InventoryAgent.iss 的默认版本"
echo "  3. 更新 latest.json"
echo "  4. 提醒你更新 CHANGELOG.md"
echo "  5. 从 CHANGELOG 生成更新说明产物"
echo "  6. 构建安装包"
echo "  7. 上传 OSS（安装包 / latest.json / CHANGELOG.md）"
echo "  8. 在 OSS 上传完成后同步网站"
echo ""

read -p "确认发布 v$NEW_VERSION? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 已取消"
    exit 1
fi

# 1. 更新 version.py 中的版本号
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

# 2. 更新安装器默认版本
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

# 3. 更新 latest.json
echo "3️⃣  更新 latest.json..."
python3 -c "
import json
with open('latest.json', 'r+') as f:
    data = json.load(f)
    data['version'] = '$NEW_VERSION'
    data['download_url'] = 'https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-$NEW_VERSION.exe'
    f.seek(0)
    json.dump(data, f, indent=2)
    f.truncate()
"

# 4. 提醒更新 CHANGELOG
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

# 5. 生成更新说明产物
echo ""
echo "5️⃣  从 CHANGELOG 生成更新说明产物..."
python3 scripts/render_release_artifacts.py --version "$NEW_VERSION"

# 6. 构建安装包
echo ""
echo "6️⃣  构建安装包..."
echo "   提示: Windows 用户请在 Windows 上运行:"
echo "   cd ~/snowfox && installer/windows/build_installer.bat"
echo ""
read -p "是否已在 Windows 上构建完成? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "⚠️  跳过构建步骤"
fi

# 7. 上传 OSS
echo ""
echo "7️⃣  上传 OSS（完成后才能同步网站）"
echo "   至少需要上传以下对象:"
echo "   - dist/installer/SnowFox-Setup-$NEW_VERSION.exe"
echo "   - latest.json"
echo "   - CHANGELOG.md"
echo ""
echo "   示例命令:"
echo "   python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py upload-file dist/installer/SnowFox-Setup-$NEW_VERSION.exe --bucket snowfox-release"
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

# 8. 同步到网站
if [[ "$OSS_UPLOADED" == true ]]; then
    echo ""
    echo "8️⃣  同步版本到网站..."
    ./scripts/sync-website.sh
fi

# 9. Git 提交
echo ""
echo "9️⃣  创建 Git 提交..."
git add -A
git commit -m "chore: release v$NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"

echo ""
echo "✅ 发布准备完成!"
echo ""
echo "下一步:"
if [[ "$OSS_UPLOADED" != true ]]; then
    echo "  1. 先上传 OSS: 安装包 / latest.json / CHANGELOG.md"
    echo "  2. 上传完成后运行: ./scripts/sync-website.sh"
    echo "  3. 推送到 GitHub: git push && git push --tags"
    echo "  4. 在 GitHub 创建 Release"
else
    echo "  1. 推送到 GitHub: git push && git push --tags"
    echo "  2. 在 GitHub 创建 Release"
fi
echo ""
