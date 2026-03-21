# SnowFox 发布脚本

本目录维护正式发版时会直接执行的脚本。当前正式流程的目标已经收口为一套统一规则：

- 一个代码仓库
- 两个平台产物：Windows `.exe` 与 macOS `.pkg`
- 一个发布元数据入口：`latest.json`
- 一份发布说明真相源：`CHANGELOG.md` 顶部条目

## 当前推荐脚本

### `release.sh`

交互式正式发版脚本。

职责：

1. 更新 `app_gui/version.py`
2. 更新 `installer/windows/LN2InventoryAgent.iss`
3. 更新 `latest.json.version`
4. 维护 `latest.json.download_url` 兼容字段
5. 维护 `latest.json.platforms.windows` 与 `latest.json.platforms.macos`
6. 提醒补齐 `CHANGELOG.md`
7. 从 `CHANGELOG.md` 生成发布说明产物
8. 运行 `scripts/validate_version.py`
9. 提示确认 Windows / macOS 构建结果
10. 提示上传 OSS
11. 在确认 OSS 上传后调用 `sync-website.sh`
12. 创建 Git 提交和 tag

使用：

```bash
cd ~/code/snowfox
./scripts/release.sh
```

### `render_release_artifacts.py`

从 `CHANGELOG.md` 顶部条目生成发布说明产物。

职责：

1. 读取 `CHANGELOG.md` 顶部版本条目
2. 更新 `latest.json.release_notes`
3. 规范化 `latest.json.download_url` 为 Windows 兼容下载链接
4. 生成 `docs/releases/v<version>-github-release.md`

输出的 GitHub Release 下载区会自动列出：

- Windows 安装包
- macOS 安装包

使用：

```bash
cd ~/code/snowfox
python3 scripts/render_release_artifacts.py --version 1.3.6
```

### `validate_version.py`

验证正式发布前的版本元数据一致性。

当前检查项：

1. `app_gui/version.py`
2. `latest.json.version`
3. `CHANGELOG.md` 顶部版本
4. `installer/windows/LN2InventoryAgent.iss`
5. `latest.json.download_url` 是否仍指向 Windows 安装包
6. `latest.json.platforms.windows` 是否匹配 `SnowFox-Setup-<version>.exe`
7. `latest.json.platforms.macos` 是否匹配 `SnowFox-<version>-macOS.pkg`

使用：

```bash
cd ~/code/snowfox
python3 scripts/validate_version.py
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

## `latest.json` 约定

当前正式 schema：

```json
{
  "version": "1.3.6",
  "download_url": "https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-1.3.6.exe",
  "platforms": {
    "windows": {
      "download_url": "https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-1.3.6.exe",
      "asset_name": "SnowFox-Setup-1.3.6.exe",
      "auto_update": true
    },
    "macos": {
      "download_url": "https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-1.3.6-macOS.pkg",
      "asset_name": "SnowFox-1.3.6-macOS.pkg",
      "auto_update": false
    }
  },
  "release_notes": "..."
}
```

说明：

- `download_url` 是兼容字段，保留给旧版客户端，始终指向 Windows `.exe`
- 新版客户端优先读取 `platforms.<platform>.download_url`
- Windows 允许自动更新
- macOS 当前只提供正确的 `.pkg` 下载链接，不走内置静默安装

## 正式发版顺序

1. 更新版本文件与 `CHANGELOG.md`
2. 运行 `python3 scripts/render_release_artifacts.py --version <version>`
3. 运行 `python3 scripts/validate_version.py`
4. 在 Windows 构建 `dist/installer/SnowFox-Setup-<version>.exe`
5. 在 macOS 构建 `dist/installer/SnowFox-<version>-macOS.pkg`
6. 上传两个安装包、`latest.json`、`CHANGELOG.md`
7. 运行 `./scripts/sync-website.sh`
8. 用 `docs/releases/v<version>-github-release.md` 填 GitHub Release 页面
9. 提交、打 tag、推送

## 推荐操作方式

当前更推荐把正式发版理解成“一台主控机器编排两台构建机器”的流程，而不是分别手工登录两边各做一半。

推荐模式：

1. 选一台机器作为主控机，通常是当前正在维护仓库和发布元数据的机器
2. 在主控机完成版本号更新、`CHANGELOG.md` 更新、release artifacts 生成和版本校验
3. 主控机通过 SSH 去另一台异平台机器触发构建
4. 两个平台安装包都完成后，再统一上传 OSS、同步网站、创建 Release

当前建议：

- 如果你在 macOS 上发版，尽量由 macOS 机器作为主控机，并通过 SSH 到 Windows 机器构建 `.exe`
- 如果你在 Windows 上发版，尽量由 Windows 机器作为主控机，并通过 SSH 到 macOS 机器构建 `.pkg`

这样做的好处：

- 发布动作有单一操作入口，减少“这边改过版本、那边忘了更新”的风险
- 两个平台产物更容易对应到同一批版本元数据
- OSS 上传、网站同步和 GitHub Release 可以在同一台主控机上统一收口

注意：

- 这是当前推荐流程，不代表 `release.sh` 已经自动实现跨机构建
- 目前仓库里的正式脚本仍然需要你自己准备好 SSH 调用或远端执行命令
- 后续如果要把这条建议变成真正自动化能力，再在脚本层补远端编排

## 发布说明唯一真相源

当前约定：

- `CHANGELOG.md` 顶部条目是发布说明唯一真相源
- `render_release_artifacts.py` 从它生成 `latest.json.release_notes`
- GitHub Release 正文文件也由它生成

不要手工分别维护 GitHub Release、`latest.json.release_notes` 和网站最新版说明。

## 旧脚本状态

### `sync_website_version.py`

旧版网站模板注入脚本。当前下载页已经改成运行时读取网站服务器本地的 `/latest.json`，不再依赖这个脚本更新 HTML 片段。

### `update_history_versions.py`

旧版历史版本列表生成脚本。当前下载页历史版本来自 OSS 上的 `CHANGELOG.md` 运行时解析，不再依赖这个脚本预生成列表。

这两个 Python 脚本暂时保留，但不再是正式发版流程的一部分。
