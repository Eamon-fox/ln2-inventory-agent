# ln2-inventory

[English](README.md) | [简体中文](README.zh-CN.md)

> 本项目首先是一个 **Claude Code agent skill**（见 `SKILL.md`），同时也可作为独立的 **桌面 GUI** 和 **Python 库** 使用。

液氮（LN2）冻存库存管理工具。数据存放在单一 YAML 文件中；所有写操作都会经过校验、自动备份，并写入追加式 JSONL 审计日志。

## 特性

- Tube 级数据模型（一个 `inventory[]` 记录 == 一支物理冻存管）
- 添加、查询、搜索
- 取出 / 复苏 / 扔掉 / 移动（单条与批量）
- 位置冲突检查、空位列表、占用统计
- 备份与回滚 + 审计日志
- 统一 Tool API（GUI 与 AI Copilot 共用）

## 快速开始

```bash
python -m pip install -r requirements.txt
cp references/ln2_inventory.sample.yaml ln2_inventory.yaml

# GUI（可选）
pip install PySide6
python app_gui/main.py

# 测试
pytest -q
```

## 配置

运行时配置是可选的。默认从当前工作目录读取 `ln2_inventory.yaml`。

如需自定义路径或 schema 范围：

```bash
export LN2_CONFIG_FILE=/path/to/my_config.json
```

可用配置项见 `references/ln2_config.sample.json`（`yaml_path`、`schema.box_range`、`schema.position_range`、`safety.*` 等）。

## AI Copilot（DeepSeek）

```bash
export DEEPSEEK_API_KEY="<your-key>"
export DEEPSEEK_MODEL="deepseek-chat"   # 可选
python agent/run_agent.py "把 ID 10 标记为今天取出"
```

## 打包（Windows EXE）

```bash
pip install pyinstaller
pyinstaller ln2_inventory.spec
```

Inno Setup 脚本：`installer/windows/LN2InventoryAgent.iss`

```bat
"C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" installer\\windows\\LN2InventoryAgent.iss
```

可选辅助脚本：`installer/windows/build_installer.bat`

## 项目结构

```
lib/              # 共享库（Tool API、YAML I/O、校验）
app_gui/          # 桌面 GUI（PySide6）
agent/            # ReAct 运行时与工具调度
tests/            # 单元测试（pytest）
references/       # 示例文件与文档
demo/             # 打包用 demo 数据集
installer/        # Windows 安装包资源（Inno Setup）
SKILL.md          # Claude Code skill 定义
```

## 依赖

- Python 3.8+
- PyYAML（`requirements.txt`）
- 可选：PySide6（GUI）
- 可选：`DEEPSEEK_API_KEY`（真实模型 AI Copilot）

## License

MIT
