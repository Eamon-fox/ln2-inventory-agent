# ln2-inventory

[English](README.md) | [简体中文](README.zh-CN.md)

> 先说明：这个项目本质上是 **Claude Code 的 agent skill**（见 `SKILL.md`），同时也可以独立作为 Python CLI 工具运行。

用于管理液氮罐库存的命令行工具。支持记录冻存细胞样本、复苏/取出操作以及多盒位点占用情况。

数据保存在单个 YAML 文件中，所有操作都通过带校验的脚本完成，不需要手动改 YAML。

## 功能

- **新增 / 查询 / 搜索** 冻存记录
- **记录复苏/取出**（单条或批量），并写入审计日志
- **位点管理**：冲突检测、空位查询、智能推荐位点
- **统计分析**：按盒占用率、细胞系分布、ASCII 网格可视化
- **备份与回滚**：自动时间戳备份，一键恢复
- **审计日志**：所有修改写入 JSONL
- **完全可配置**：盒子数量、网格大小、位置范围、细胞系白名单均可通过 JSON 配置
- **统一 Tool API**：CLI、GUI、AI agent 共用一套工具接口
- **GUI 起步版**：`app_gui/` 提供桌面端查询/新增/取出面板
- **ReAct 运行时**：`agent/` 提供 AI agent 循环与工具调度

## 快速开始

```bash
# 1. 安装依赖
pip install pyyaml

# 2. 初始化样例数据（也可以从空文件开始）
cp references/ln2_inventory.sample.yaml ln2_inventory.yaml

# 3. 运行几个命令试用
python scripts/stats.py --visual
python scripts/smart_search.py "K562" --keywords
python scripts/query_inventory.py --empty --box 1
python scripts/recommend_position.py --count 3
```

## 使用示例

### 新增冻存记录

```bash
python scripts/add_entry.py \
  --parent-cell-line "K562" \
  --short-name "RTCB-dTAG-clone12" \
  --box 1 --positions "30,31" \
  --frozen-at "2026-01-08" \
  --plasmid-name "pGEMT-N-RTCB-dTAG" \
  --note "homozygous clone"
```

### 记录复苏 / 取出

```bash
# 单条
python scripts/record_thaw.py --id 5 --position 30 --date 2026-02-01

# 批量
python scripts/batch_thaw.py --entries "5:30,6:12" --date 2026-02-01 --action 复苏
```

### 查询

```bash
python scripts/smart_search.py "dTAG" --keywords --raw
python scripts/query_recent.py --frozen --days 30
python scripts/query_thaw.py --days 7
python scripts/timeline.py --days 30 --summary
```

### 备份与回滚

```bash
python scripts/rollback.py --list
python scripts/rollback.py  # 回滚到最新备份
```

## 配置

默认情况下，脚本会在当前目录查找 `ln2_inventory.yaml`。
如需自定义路径或参数，创建 JSON 配置文件并通过环境变量指定：

```bash
export LN2_CONFIG_FILE=/path/to/my_config.json
```

完整配置项见：[`references/ln2_config.sample.json`](references/ln2_config.sample.json)

- `yaml_path`：库存文件路径
- `schema.box_range`：盒子范围（默认 `[1, 5]`）
- `schema.position_range`：每盒位置范围（默认 `[1, 81]`，即 9x9）
- `schema.valid_cell_lines`：可选白名单（空列表表示允许任意细胞系）
- `schema.valid_actions`：复苏/取出动作类型
- `safety.*`：备份保留数、告警阈值等

## 作为 Claude Code Skill 使用

该项目也可以作为 [Claude Code](https://claude.ai/code) skill 使用。AI agent 集成说明见 [`SKILL.md`](SKILL.md)。

## GUI（M2 起步）

```bash
pip install PySide6
python app_gui/main.py
```

## ReAct Agent 运行时

```bash
# mock 模式（不调用外部模型）
python agent/run_agent.py "查询 K562 记录" --mock

# 真实模型模式（DeepSeek 原生解析）
export DEEPSEEK_API_KEY="<your-key>"
export DEEPSEEK_MODEL="deepseek-chat"
python agent/run_agent.py "把 ID 10 的位置 23 标记为取出，日期今天"
```

## 项目结构

```text
scripts/          # 15 个 CLI 脚本（查询、修改、工具）
lib/              # 公共库（配置、YAML 操作、校验）
agent/            # ReAct runtime、工具调度、LLM 适配
app_gui/          # 桌面 GUI 脚手架
tests/            # 单元测试（pytest）
references/       # 示例文件和文档
SKILL.md          # Claude Code skill 定义
```

## 环境要求

- Python 3.8+
- PyYAML
- 可选：PySide6（GUI）
- 可选：DEEPSEEK_API_KEY（真实模型 agent 模式）

## 许可证

MIT
