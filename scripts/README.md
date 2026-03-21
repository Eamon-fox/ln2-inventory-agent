# SnowFox 发布脚本

本目录维护发版过程中会直接执行的脚本。当前正式流程的关键目标有三个：

- 保证桌面应用版本元数据一致
- 保证 GitHub Release、自动更新说明、网站最新版说明三处从同一份变更记录派生
- 在 OSS 上传完成后，把网站服务器上的 `latest.json` 和 `dist/` 同步到同一版本

## 当前推荐脚本

### `release.sh`

交互式正式发版脚本。

职责：

1. 更新 `app_gui/version.py`
2. 更新 `installer/windows/LN2InventoryAgent.iss`
3. 更新 `latest.json`
4. 提醒手动补齐 `CHANGELOG.md`
5. 从 `CHANGELOG.md` 生成更新说明产物
6. 提示完成 Windows 安装包构建
7. 提示上传 OSS 资产
8. 在确认 OSS 已上传后调用 `sync-website.sh`
9. 创建 Git 提交和 tag

使用：

```bash
cd ~/code/snowfox
./scripts/release.sh
```

### `sync-website.sh`

从 MacBook 通过 SSH 同步网站版本。

职责：

1. 把当前仓库的 `latest.json` 复制到网站服务器 `/var/www/snowfox.bio/latest.json`
2. 在网站服务器执行 `node scripts/build.js`
3. 校验服务器 `dist/latest.json` 的版本号与本地一致

使用：

```bash
cd ~/code/snowfox
./scripts/sync-website.sh
```

默认它会连接 SSH 别名 `ecs` 并操作 `/var/www/snowfox.bio`。如有需要，可以覆盖：

```bash
WEBSITE_HOST=ecs WEBSITE_DIR=/var/www/snowfox.bio ./scripts/sync-website.sh
```

### `render_release_artifacts.py`

从 `CHANGELOG.md` 顶部条目生成发布说明产物。

职责：

1. 读取 `CHANGELOG.md` 顶部版本条目
2. 更新 `latest.json.release_notes`
3. 生成 `docs/releases/v<version>-github-release.md`

这意味着以下三处内容保持同源：

- GitHub Release 页面正文
- 软件自动更新提示
- 网站下载页的“最新版”说明

使用：

```bash
cd ~/code/snowfox
python3 scripts/render_release_artifacts.py --version 1.3.6
```

## 旧脚本状态

### `sync_website_version.py`

旧版网站模板注入脚本。当前下载页已经改成运行时读取网站服务器本地的 `/latest.json`，不再依赖这个脚本更新 HTML 片段。

### `update_history_versions.py`

旧版历史版本列表生成脚本。当前下载页历史版本来自 OSS 上的 `CHANGELOG.md` 运行时解析，不再依赖这个脚本预生成列表。

这两个 Python 脚本暂时保留，但不再是正式发版流程的一部分。

## 正式发版顺序

### 方式一：使用 `release.sh`

```bash
cd ~/code/snowfox
./scripts/release.sh
```

推荐顺序：

1. 更新版本文件与 `CHANGELOG.md`
2. 运行 `python3 scripts/render_release_artifacts.py --version <version>`
3. 在 Windows 构建 `dist/installer/SnowFox-Setup-<version>.exe`
4. 上传 OSS 对象
5. 运行 `./scripts/sync-website.sh`
6. 用 `docs/releases/v<version>-github-release.md` 填 GitHub Release 页面
7. 推送 GitHub 并创建 Release

### 方式二：手动执行

1. 更新版本文件

```bash
# app_gui/version.py
APP_VERSION = "1.3.6"

# installer/windows/LN2InventoryAgent.iss
#define MyAppVersion "1.3.6"

# latest.json
{
  "version": "1.3.6",
  "download_url": "https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-1.3.6.exe",
  "release_notes": "..."
}
```

2. 更新 `CHANGELOG.md`

```markdown
## 1.3.6 - 2026-03-21

### Added
- ...

### Changed
- ...

### Fixed
- ...
```

3. 从 `CHANGELOG.md` 生成发布说明产物

```bash
python3 scripts/render_release_artifacts.py --version 1.3.6
```

4. 运行一致性检查

```bash
python3 scripts/validate_version.py
```

5. 在 Windows 构建安装包

```bat
installer\windows\build_installer.bat
```

6. 上传 OSS

必须先上传安装包，再上传 `latest.json`，并同步上传 `CHANGELOG.md`，否则网站历史版本和更新说明会滞后。

```bash
python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py \
  upload-file dist/installer/SnowFox-Setup-1.3.6.exe --bucket snowfox-release

python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py \
  upload-file latest.json --bucket snowfox-release

python3 ~/.agents/skills/aliyun-oss-upload/scripts/oss_upload.py \
  upload-file CHANGELOG.md --bucket snowfox-release
```

7. 同步网站

```bash
./scripts/sync-website.sh
```

8. 用 `docs/releases/v1.3.6-github-release.md` 作为 GitHub Release 正文

9. 提交和推送

```bash
git add -A
git commit -m "chore: release v1.3.6"
git tag -a "v1.3.6" -m "Release v1.3.6"
git push
git push --tags
```

## 网站同步机制

当前网站实际服务目录是 Linux 服务器上的 `/var/www/snowfox.bio/dist`。

同步时要区分两层：

- 源文件层：`/var/www/snowfox.bio/latest.json`
- 对外服务层：`/var/www/snowfox.bio/dist/latest.json`

`sync-website.sh` 做的是：

1. 从 MacBook 把开发仓库中的 `latest.json` 拷到服务器源目录
2. 在服务器端重跑 `node scripts/build.js`
3. 让新的 `latest.json` 进入 `dist/`

所以网站不会自动因为 OSS 更新而刷新 `dist/`。每次正式发版后，只要版本要对外展示，就需要执行一次网站同步。

## 发布说明唯一真相源

当前约定：

- `CHANGELOG.md` 顶部条目是发布说明唯一真相源
- `render_release_artifacts.py` 从它生成 `latest.json.release_notes`
- GitHub Release 正文文件也由它生成

不要手工分别维护 GitHub Release、`latest.json.release_notes` 和网站最新版说明。

## 文件关系

```text
~/code/snowfox/
├── app_gui/version.py
├── installer/windows/LN2InventoryAgent.iss
├── latest.json
├── CHANGELOG.md
└── scripts/
    ├── release.sh
    ├── render_release_artifacts.py
    ├── sync-website.sh
    └── validate_version.py

网站服务器 ecs:/var/www/snowfox.bio/
├── latest.json
├── scripts/build.js
└── dist/
    └── latest.json
```

## 常见问题

### 网站已经显示新版本，但下载打不开

通常说明网站同步早于 OSS 安装包上传。

处理：

1. 先确认 `SnowFox-Setup-<version>.exe` 已在 `snowfox-release` 中可访问
2. 再重新运行 `./scripts/sync-website.sh`

### 下载页历史版本没更新

当前历史版本来自 OSS 上的 `CHANGELOG.md`。

处理：

1. 确认 `CHANGELOG.md` 已上传到 `snowfox-release`
2. 确认顶部条目格式是 `## <version> - <date>`

### 网站同步脚本报 SSH 或路径错误

处理：

1. 确认 Mac 上 `ssh ecs` 可连通
2. 确认服务器目录 `/var/www/snowfox.bio` 存在
3. 确认服务器上 `node scripts/build.js` 可执行

### GitHub Release、自动更新说明、网站最新版说明不一致

通常说明 `latest.json.release_notes` 或 GitHub Release 正文被手工改过，没有重新从 `CHANGELOG.md` 生成。

处理：

```bash
python3 scripts/render_release_artifacts.py --version <version>
```
