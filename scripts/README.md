# SnowFox 发布脚本

自动化版本管理和网站同步工具集。

## 📦 脚本说明

### `sync_website_version.py`
从 `latest.json` 同步版本号到网站。

**功能：**
- 更新 `hero.html` 中的下载链接
- 更新 `download.html` 中的版本号和下载链接

**使用：**
```bash
cd ~/snowfox
python3 scripts/sync_website_version.py
```

---

### `update_history_versions.py`
从 `CHANGELOG.md` 自动提取历史版本并更新网站。

**功能：**
- 解析 `CHANGELOG.md` 提取版本号与发布日期
- 生成历史版本下载链接
- 更新 `download.html` 的历史版本列表
- 为历史版本项补充悬停摘要提示，方便快速查看版本变化

**使用：**
```bash
cd ~/snowfox
python3 scripts/update_history_versions.py
```

---

### `release.sh`
完整的发布流程脚本（交互式）。

**功能：**
1. 更新 `app_gui/version.py` 中的 `APP_VERSION`
2. 更新 `installer/windows/LN2InventoryAgent.iss` 的默认版本
3. 更新 `latest.json`
4. 提醒更新 `CHANGELOG.md`
5. 提示构建安装包
6. 同步版本到网站
7. 创建 Git 提交和标签

**使用：**
```bash
cd ~/snowfox
./scripts/release.sh
```

---

## 🚀 发布流程

### 方式一：使用 `release.sh`（推荐）

```bash
cd ~/snowfox
./scripts/release.sh
```

按提示输入新版本号，脚本会自动完成大部分工作。

### 方式二：手动发布

1. **更新版本号**
   ```bash
   # 编辑 app_gui/version.py
   APP_VERSION = "1.3.5"

   # 编辑 installer/windows/LN2InventoryAgent.iss
   #define MyAppVersion "1.3.5"
   
   # 编辑 latest.json
   {
     "version": "1.3.5",
     "download_url": "https://snowfox-release.oss-cn-beijing.aliyuncs.com/SnowFox-Setup-1.3.5.exe",
     "release_notes": "..."
   }
   ```

2. **更新 CHANGELOG.md**
   ```markdown
   ## 1.3.5 - 2026-03-20
   
   ### Added
   - 新功能...
   
   ### Changed
   - 改进...
   
   ### Fixed
   - 修复...
   ```

3. **构建安装包**（在 Windows 上）
   ```bash
   cd C:\path\to\snowfox
   installer\windows\build_installer.bat
   ```

4. **上传到 OSS**
   ```bash
   ossutil cp dist/installer/SnowFox-Setup-1.3.5.exe oss://snowfox-release/
   ```

5. **同步到网站**
   ```bash
   cd ~/snowfox
   python3 scripts/sync_website_version.py
   python3 scripts/update_history_versions.py
   ```

6. **提交和推送**
   ```bash
   git add -A
   git commit -m "chore: release v1.3.5"
   git tag v1.3.5
   git push && git push --tags
   ```

---

## 📋 文件依赖关系

```
~/snowfox/
├── app_gui/version.py     # APP_VERSION 权威来源
├── installer/windows/LN2InventoryAgent.iss  # Windows 安装器默认版本
├── latest.json            # 版本配置（单一数据源）
├── CHANGELOG.md           # 版本历史
└── scripts/
    ├── sync_website_version.py
    ├── update_history_versions.py
    └── release.sh

/var/www/snowfox.bio/
└── assets/partials/
    ├── hero.html          # 首页下载链接
    └── download.html      # 下载页面（最新版+历史版本）
```

---

## ⚙️ 配置要求

- Python 3.6+
- Git
- ossutil（用于上传到 OSS）
- Inno Setup 6（Windows 构建）

---

## 🔍 故障排查

### 问题：脚本提示 `latest.json` 不存在
**解决：** 确保在 `~/snowfox` 根目录运行脚本

### 问题：网站文件未更新
**解决：** 检查 `/var/www/snowfox.bio` 路径权限

### 问题：历史版本列表未更新
**解决：** 确保 `CHANGELOG.md` 格式正确（`## 1.3.3 - 2026-03-05`）

---

## 📝 注意事项

- 发布前确保所有测试通过
- 保持 `CHANGELOG.md` 格式一致
- 版本号遵循语义化版本规范（SemVer）
- 发布前可运行 `python3 scripts/validate_version.py` 检查版本一致性
- 发布后检查网站是否正常更新
