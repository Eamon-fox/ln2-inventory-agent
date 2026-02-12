# LN2 Inventory Agent - 项目架构分析

> **文档版本**: 1.0
> **生成日期**: 2026-02-12
> **项目路径**: `/analysis4/fanym/projects/personal/ln2-inventory-agent`

---

## 1. 项目概述

LN2 Inventory Agent 是一个液氮罐库存管理系统，支持 CLI、GUI 和 AI Agent 三种交互模式。系统采用分层架构设计，数据存储在 YAML 文件中，所有操作都通过验证脚本完成，无需手动编辑 YAML。

### 1.1 核心特性

- **增删查改**: 添加/查询/搜索冷冻细胞系记录
- **操作记录**: 记录解冻/取出事件（单条或批量），支持审计追踪
- **位置管理**: 冲突检测、空位查找、智能位置推荐
- **统计分析**: 每盒占用率、细胞系分布、ASCII 网格可视化
- **备份回滚**: 自动时间戳备份，一键恢复
- **审计日志**: JSONL 格式记录所有修改
- **可配置性**: 盒数、网格大小、位置范围、细胞系白名单等均通过 JSON 配置
- **统一工具 API**: CLI、GUI 和 AI Agent 运行时共享
- **GUI 界面**: `app_gui/` 中的桌面应用骨架
- **ReAct 运行时**: `agent/` 中的 DeepSeek 原生解析器或模拟模式

---

## 2. 目录结构

```
ln2-inventory-agent/
├── lib/              # 共享库（配置、YAML 操作、验证）
├── agent/            # ReAct 运行时 + 工具分发器 + LLM 适配器
├── app_gui/          # 桌面 GUI 骨架
├── scripts/          # 15 个 CLI 脚本（查询、修改、工具）
├── tests/            # 单元测试（pytest）
├── references/       # 示例文件和文档
├── demo/             # 演示数据
├── SKILL.md          # Claude Code skill 定义
└── README.md         # 项目说明
```

---

## 3. 分层架构

系统采用清晰的分层架构，自下而上分为四层：

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   CLI (13)   │  │   GUI        │  │   AI Agent       │  │
│  │   scripts/   │  │   app_gui/   │  │   agent/         │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Tool API Layer                          │
│                    lib/tool_api.py                           │
│              (统一的 13 个工具函数接口)                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Business Logic Layer                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌─────────┐  │
│  │ yaml_ops   │ │ validators │ │ operations │ │ thaw_   │  │
│  │            │ │            │ │            │ │ parser  │  │
│  └────────────┘ └────────────┘ └────────────┘ └─────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     Configuration Layer                      │
│                      lib/config.py                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 核心模块详解

### 4.1 lib/ 核心库层

#### 4.1.1 config.py - 配置管理

**职责**:
- 管理运行时配置，采用分层优先级系统
- 处理配置加载、合并和验证
- 提供路径解析，支持不同部署场景（PyInstaller vs 开发模式）
- 导出标准化常量供其他模块使用

**关键函数**:

| 函数 | 功能 |
|------|------|
| `_get_app_dir()` | 检测应用目录（PyInstaller 或开发模式） |
| `_default_yaml_path()` | 确定默认 YAML 库存路径 |
| `_merge_dict()` | 递归合并配置字典 |
| `_load_external_config()` | 从环境变量加载用户特定 JSON 配置 |
| `_build_runtime_config()` | 构建最终运行时配置 |

**导出常量**:
- `YAML_PATH`: 库存文件路径
- `PYTHON_PATH`: Python 解释器路径
- `SCRIPTS_DIR`: 脚本目录
- 安全阈值、范围配置等

#### 4.1.2 yaml_ops.py - YAML 文件操作

**职责**:
- 处理所有 YAML 文件 I/O 操作（加载、写入、备份）
- 管理库存完整性验证（写入前）
- 提供备份和回滚功能
- 实现所有操作的审计日志记录
- 计算占用率和统计信息用于容量警告

**关键函数**:

| 函数 | 功能 |
|------|------|
| `load_yaml()` | 安全加载 YAML，带错误处理 |
| `write_yaml()` | 原子写入操作，含验证、备份、审计 |
| `create_yaml_backup()` | 时间戳备份，可配置保留策略 |
| `list_yaml_backups()` | 列出可用备份（按修改时间排序） |
| `rollback_yaml()` | 从备份恢复，带回滚前快照 |
| `compute_occupancy()` | 计算每盒占用位置 |
| `append_audit_event()` | 记录带完整上下文的审计事件 |

#### 4.1.3 validators.py - 数据验证

**职责**:
- 验证单个库存记录和完整库存文档
- 提供日期验证和规范化工具
- 检查重复 ID 和位置冲突
| 验证操作类型和位置范围
| 格式化验证错误供用户消费

**关键函数**:

| 函数 | 功能 |
|------|------|
| `validate_date()` / `parse_date()` | 日期处理工具 |
| `validate_box()` / `validate_position()` | 字段验证 |
| `parse_positions()` | 解析位置字符串（支持范围和列表） |
| `has_depletion_history()` | 检查记录是否完全消耗 |
| `validate_record()` | 验证单个库存记录 |
| `check_duplicate_ids()` / `check_position_conflicts()` | 跨记录验证 |
| `validate_inventory()` | 完整文档验证 |

#### 4.1.4 operations.py - 核心业务逻辑

**职责**:
- 提供基础记录操作
| 处理位置冲突检查
| 管理 ID 生成
| 实现简单 CRUD 操作

**关键函数**:

| 函数 | 功能 |
|------|------|
| `find_record_by_id()` | 通过 ID 定位记录 |
| `check_position_conflicts()` | 识别位置重叠 |
| `get_next_id()` | 生成下一个可用记录 ID |

#### 4.1.5 thaw_parser.py - 解冻事件处理

**职责**:
| 规范化和解析解冻/取出/丢弃事件
| 处理中英文操作别名
| 从记录中提取事件历史
| 确定活跃位置

**关键函数**:

| 函数 | 功能 |
|------|------|
| `normalize_action()` | 规范化操作为标准形式 |
| `extract_events()` | 从记录中提取结构化事件 |
| `extract_thaw_positions()` | 获取所有已消耗位置 |
| `is_position_active()` | 检查位置是否仍可用 |
| `format_positions()` | 格式化位置列表供显示 |

**数据结构**:
- `ACTION_ALIAS`: 中文到英文操作的映射字典
- `ACTION_LABEL`: 显示标签字典

#### 4.1.6 tool_api.py - 统一工具 API（核心模块）

**职责**:
- 提供 CLI、GUI 和 AI Agent 共享的统一 API
| 实现所有高级操作，带一致的错误处理
| 管理所有操作的审计追踪和上下文
| 提供批操作和复杂场景支持
| 提供查询和搜索能力

**13 个工具函数**:

| 类别 | 函数 | 功能 |
|------|------|------|
| **增删改** | `tool_add_entry()` | 添加新库存记录 |
| | `tool_record_thaw()` | 记录单次解冻/取出/丢弃/移动操作 |
| | `tool_batch_thaw()` | 批量操作，支持复杂场景 |
| | `tool_rollback()` | 从备份恢复 |
| **查询** | `tool_query_inventory()` | 按字段过滤查询记录 |
| | `tool_search_records()` | 模糊/精确/关键词搜索 |
| | `tool_list_empty_positions()` | 查找空位 |
| | `tool_recent_frozen()` | 查询最近记录 |
| | `tool_query_thaw_events()` | 查询解冻事件 |
| | `tool_collect_timeline()` | 生成时间线数据 |
| | `tool_get_raw_entries()` | 检索原始 YAML 条目 |
| **工具** | `tool_recommend_positions()` | 为新样本推荐位置 |
| | `tool_generate_stats()` | 生成库存统计 |

**标准结果格式**:
```python
{
    "ok": bool,
    "result": {...},
    "error_code": str,
    "message": str
}
```

### 4.2 agent/ AI Agent 层

#### 4.2.1 llm_client.py - LLM 客户端接口

**职责**:
- 提供 LLM 交互的抽象接口
- 处理 DeepSeek API 集成，支持流式传输
- 实现用于测试的回退/模拟客户端
| 管理身份验证和 API 密钥加载
| 规范化不同 LLM 提供商的响应

**关键类**:

| 类 | 功能 |
|------|------|
| `LLMClient` (ABC) | 定义标准接口的抽象基类 |
| `DeepSeekLLMClient` | DeepSeek API 主实现 |
| `MockLLMClient` | 测试用的回退实现 |

**关键方法**:
- `chat()`: 同步聊天补全
- `stream_chat()`: 流式响应生成器
- `complete()`: 纯文本便捷包装器

#### 4.2.2 react_agent.py - ReAct 循环实现

**职责**:
- 核心 ReAct Agent 协调器
| 管理对话状态和历史
| 处理工具执行协调
| 实现逐步推理循环
| 提供用于实时反馈的事件流

**ReAct 循环流程**:

```
1. 步骤开始 → 发出步骤初始化事件
2. 模型响应 → 收集并解析 LLM 响应
3. 工具执行 → 并行执行多个工具（通过 ThreadPoolExecutor）
4. 观察处理 → 工具结果添加到对话
5. 终止条件 → 最大步数 / 直接答案 / 空响应重试
```

**终止条件**:
- 达到最大步数（默认 8）
| 提供直接答案
| 空响应时强制重试

#### 4.2.3 tool_runner.py - 工具分发器

**职责**:
- 统一接口到所有 LN2 库存操作
| 处理工具规范生成
| 输入验证和规范化
| 写入操作的暂存，供人工批准
| 带上下文提示的错误处理

**13 个可用工具**:

| 类别 | 工具 |
|------|------|
| 查询 | `query_inventory`, `search_records`, `get_raw_entries` |
| 位置管理 | `list_empty_positions`, `recommend_positions` |
| 操作 | `add_entry`, `record_thaw`, `batch_thaw` |
| 历史 | `query_thaw_events`, `collect_timeline`, `recent_frozen` |
| 系统 | `generate_stats`, `rollback` |

**分发过程**:
1. 工具名称验证
2. 输入参数规范化
3. 模式验证
4. 通过 lib/ API 执行工具
5. 带提示的错误处理

**计划暂存（人机协作）**:
当配置 `_plan_sink` 时，写入操作被暂存：
- `add_entry`, `record_thaw`, `batch_thaw` 被拦截
- 转换为 PlanItem 对象
- 通过 `validate_plan_item()` 验证
| 向用户返回摘要消息
| 实际执行推迟到 GUI 批准

#### 4.2.4 run_agent.py - CLI 入口点

**职责**:
- Agent 的命令行接口
| 配置解析和验证
| 主协调设置
| JSON 结果格式化

**配置选项**:
- `--yaml`: 库存 YAML 文件路径
- `--model`: DeepSeek 模型 ID
- `--max-steps`: 最大 ReAct 步数
- `--actor-id`: 审计日志标识符
- `--mock`: 禁用真实 LLM 调用

### 4.3 app_gui/ GUI 层

#### 4.3.1 整体架构

GUI 使用 PySide6（Qt6 for Python）构建，采用模块化架构，职责清晰分离。应用提供三面板布局，实现全面的库存管理能力。

```
┌─────────────────────────────────────────────────────────────┐
│                    QMainWindow (main.py)                     │
│  ┌──────────────────┬──────────────────┬──────────────────┐  │
│  │  Overview Panel  │ Operations Panel │    AI Panel      │  │
│  │  (overview_panel)│(operations_panel)│    (ai_panel)    │  │
│  │                  │                  │                  │  │
│  │  网格可视化       │  表单/操作        │  聊天界面        │  │
│  │  悬停详情        │  计划管理         │  实时进度        │  │
│  │  多选操作        │  批处理          │  历史记录        │  │
│  └──────────────────┴──────────────────┴──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

#### 4.3.2 main.py - 主应用

**职责**:
- 初始化主应用窗口
| 管理应用配置（从 QSettings 迁移到统一 YAML 配置）
| 处理顶层 UI 设置，包括分割器布局
| 协调面板间通信
| 提供 YAML 路径和 actor ID 配置的设置对话框

**关键类**:
- `MainWindow`: 继承自 QMainWindow 的主应用窗口

**事件处理**:
| 数据集选择的快速启动对话框
| 配置的设置对话框
| 通过 Qt 信号的面板协调
| 窗口几何持久化

#### 4.3.3 gui_config.py - GUI 配置

**职责**:
| 统一配置管理系统
| 在 `~/.ln2agent/config.yaml` 中管理 GUI 设置
| 提供默认值回退
| 处理从旧版 QSettings 存储的迁移
| 存储 AI 模型设置、YAML 路径和 actor ID

**关键函数**:
- `load_gui_config()`: 带默认值的加载配置
- `save_gui_config()`: 将配置持久化到 YAML

#### 4.3.4 tool_bridge.py - 工具桥接

**职责**:
| GUI 面向统一工具 API 的适配器
| 在工具调用上加盖 GUI 元数据（actor 上下文）
| 为 GUI 操作提供简化接口
| 处理 AI Agent 执行
| 将 GUI 字段名映射到 API 参数

**GuiToolBridge 方法**:

| 方法 | 功能 |
|------|------|
| `query_inventory` | 查询操作 |
| `add_entry` | 添加记录 |
| `record_thaw` | 单次解冻操作 |
| `batch_thaw` | 批量解冻 |
| `generate_stats` | 生成统计 |
| `collect_timeline` | 收集时间线 |
| `run_agent_query` | 执行 AI 查询 |

**响应格式**:
```python
{
    "ok": bool,
    "message": str,
    "result": {...}
}
```

#### 4.3.5 plan_model.py - 计划模型

**职责**:
| 统一操作计划验证和渲染
| 验证操作计划项
| 生成可打印的操作表单（HTML 格式）
| 确保批操作的数据完整性

**关键函数**:
- `validate_plan_item()`: 严格规则验证单个操作
- `render_operation_sheet()`: 生成分组 HTML 输出供打印

**验证规则**:
| 支持操作: takeout, thaw, discard, move, add
| 验证盒号、位置和记录 ID
| 确保移动操作有有效目标
| add 操作需要 parent_cell_line 和 short_name

#### 4.3.6 UI 面板

**Overview Panel (overview_panel.py)**

**职责**:
| 带网格显示的可视化库存概览
| 悬停时显示记录详情
| 提供过滤和搜索能力
| 支持多选操作

**关键组件**:
- `CellButton`: 带双击支持的自定义 QPushButton
| 盒可视化的网格布局
| 过滤控件（关键词、盒、细胞系、显示空位）
| 汇总统计卡片
| 批操作的选择工具栏

**信号**:
- `plan_items_requested`: 发送选定项到操作面板
- `request_prefill`: 用记录数据预填充表单
- `data_loaded`: 更新操作面板缓存

**Operations Panel (operations_panel.py)**

**职责**:
| 手动操作和计划管理
| 为所有库存操作提供表单
| 管理计划暂存和执行
| 带去重处理批操作
| 提供带备份管理的撤销功能

**操作模式**:

| 模式 | 功能 |
|------|------|
| Add Entry | 创建新记录 |
| Thaw/Takeout/Discard | 单/批操作 |
| Move | 盒内或跨盒重定位记录 |
| Plan | 暂存和执行多个操作 |
| Query | 搜索和导出库存 |
| Rollback | 从备份恢复 |
| Audit | 查看操作历史 |

**特性**:
| 计划去重和验证
| 批操作回退（批 → 单独）
| 带自动过期备份的撤销功能
| 导出能力（CSV, HTML 操作表单）
| 上下文相关记录信息显示

**AI Panel (ai_panel.py)**

**职责**:
| AI 驱动的库存管理助手
| 提供库存的自然语言接口
| 实时显示 agent 执行进度
| 显示带 markdown 渲染的流式响应
| 管理 agent 历史和快速提示

**特性**:
| **流式响应**: 带 markdown 渲染的实时更新
| **进度追踪**: 逐步工具执行显示
| **快速提示**: 预定义的常用操作
| **历史管理**: 维护对话历史
| **审计集成**: 显示完整执行结果

#### 4.3.7 workers.py - 异步操作

**职责**:
| 在独立线程中运行 AI Agent，防止 UI 冻结
| 通过 Qt 信号处理进度报告
| 管理 agent 输出的计划暂存

**AgentRunWorker**:
| Worker 对象，用于基于线程的执行
| 处理异常处理和响应格式化

**事件流**:
1. Worker 在新线程启动
2. 进度事件通过信号发出
3. 计划项通过 `plan_sink` 回调暂存
4. 完成时返回结果
5. 线程自动清理

### 4.4 scripts/ CLI 脚本层

#### 4.4.1 脚本分类

**数据修改脚本**:
| `add_entry.py`: 添加新记录
| `record_thaw.py`: 记录单次操作
| `batch_thaw.py`: 记录批操作

**查询脚本**:
| `query_inventory.py`: 通用库存查询
| `query_recent.py`: 最近活动查询
| `query_thaw.py`: 解冻事件查询
| `search.py`: 全局模糊搜索
| `smart_search.py`: 智能搜索
| `timeline.py`: 历史时间线

**工具脚本**:
| `stats.py`: 统计和可视化
| `recommend_position.py`: 位置推荐
| `check_conflicts.py`: 冲突检测
| `validate.py`: 数据验证
| `rollback.py`: 备份/恢复
| `show_raw.py`: 原始数据显示

#### 4.4.2 CLI 模式

所有脚本遵循一致的模式:

**参数解析**:
| 所有脚本使用 `argparse` 配合 `RawDescriptionHelpFormatter`
| 必需参数清晰标记
| 广泛的 epilog 部分包含使用示例
| 一致的参数命名约定

**错误处理**:
| 带表情符号指示符的统一错误消息（❌ 表示错误，✅ 表示成功）
| 带上下文的详细错误消息
| 返回码（0 表示成功，1 表示错误）

**输出格式**:
| 使用 `=` 分隔符的重要部分
| 对齐列的表格数据
| 带 `--dry-run` 标志的预览模式支持
| Verbose/compact 输出选项

### 4.5 tests/ 测试层

#### 4.5.1 测试组织

```
tests/
├── lib/                    # 核心库功能
│   ├── test_config.py      # 配置管理
│   ├── test_yaml_ops.py    # 数据持久化
│   ├── test_validate.py    # 记录验证
│   ├── test_validators.py  # 验证工具
│   ├── test_thaw_parser.py # 事件处理
│   └── test_tool_api.py   # 业务逻辑（+ 不变量）
├── agent/                  # AI 和工具
│   ├── test_llm_client.py  # LLM 集成
│   ├── test_react_agent.py # AI agent
│   └── test_agent_tool_runner.py # 工具执行
└── app_gui/                # GUI 组件
    ├── test_gui_tool_bridge.py   # 后端桥接
    ├── test_gui_bridge.py        # 主集成
    ├── test_gui_config.py        # 配置
    ├── test_gui_panels.py        # Qt 面板
    ├── test_plan_model.py        # 计划模型
    └── test_tool_api_invariants.py # API 不变量
```

#### 4.5.2 测试类别

**单元测试**（主要关注）:
| 单个组件的隔离测试
| API 边界验证
| 错误处理和边缘情况
| 配置验证

**集成测试**:
| 组件交互测试
| 数据流验证
| 审计追踪一致性

**回归测试**:
| 计划去重和执行回退
| GUI 行为保持
| 跨盒移动功能

**GUI 测试**:
| 带 PySide6 的 Qt 面板行为
| 事件驱动的交互测试
| 信号发射验证

---

## 5. 数据模型

### 5.1 YAML 库存结构

```yaml
inventory:
  - id: 1
    parent_cell_line: "K562"
    short_name: "reporter-1"
    box: 1
    positions: [1, 2, 3]
    frozen_at: "2024-01-01"
    thaw_events:
      - date: "2024-01-15"
        action: "取出"
        positions: [1]
    plasmid_name: "pLX304-GFP"
    note: "Test plasmid"
meta:
  box_layout:
    rows: 9
    cols: 9
```

### 5.2 审计事件结构

```json
{
  "action": "取出",
  "timestamp": "2024-01-15T10:30:00",
  "source": "cli",
  "actor_id": "user1",
  "session_id": "abc123",
  "trace_id": "def456",
  "details": {...}
}
```

### 5.3 计划项结构

```python
PlanItem {
    "action": str,      # takeout, thaw, discard, move, add
    "box": int,
    "position": int,
    "record_id": Optional[int],
    "to_box": Optional[int],      # for move
    "to_position": Optional[int], # for move
    "parent_cell_line": Optional[str],  # for add
    "short_name": Optional[str],        # for add
    "positions": Optional[List[int]],   # for add
    "frozen_at": Optional[str],         # for add
}
```

---

## 6. 设计模式

| 模式 | 应用位置 | 描述 |
|------|----------|------|
| **外观模式** | `tool_api.py` | 为复杂子系统提供简化的统一接口 |
| **策略模式** | `tool_search_records()` | 不同的搜索模式（模糊、精确、关键词） |
| **模板方法** | 所有写入操作 | 通用的审计流程 |
| **工厂模式** | `tool_recommend_positions()` | 位置推荐策略 |
| **观察者模式** | 审计日志 | 追踪所有状态变化 |
| **验证模式** | 多层验证 | 从简单到复杂检查 |
| **命令模式** | 每个工具函数 | 代表不同操作的命令 |
| **适配器模式** | `tool_bridge.py` | GUI 到工具 API 的适配 |

---

## 7. 数据流

### 7.1 查询流程

```
用户输入 → 表现层（CLI/GUI/AI） → Tool API → lib/ → 数据库 → 响应 → 表现层更新
```

### 7.2 写入流程

```
用户输入 → 表现层 → Tool API → 验证 → 备份 → 写入 → 审计日志 → 响应
```

### 7.3 Agent 工作流程

```
用户查询 → Agent 运行时 → LLM 调用 → 工具调用分发 → 执行 → 观察反馈 → 循环 → 最终答案
```

### 7.4 GUI 面板通信

```
Overview Panel → Operations Panel:
- plan_items_requested (多选操作)
- request_prefill (记录详情)
- data_loaded (缓存更新)

Operations Panel → Overview Panel:
- operation_completed (刷新触发)

AI Panel → Operations Panel:
- plan_items_staged (agent 生成的操作)
- operation_completed (刷新触发)
```

---

## 8. 错误处理

### 8.1 LLM 流失败

| 回退到 plain payload 解析
| 向回调发出错误事件
| 优雅降级到纯文本

### 8.2 工具执行错误

| 基于错误代码的上下文提示
| 必需/可选参数提示
| 验证错误消息

### 8.3 达到最大步数

| 强制直接答案请求
| 使用对话摘要
| 清晰的错误消息

### 8.4 工具验证

| 执行前的输入规范化
| 复杂类型的模式验证
| 带错误报告的类型强制转换

---

## 9. 高级特性

### 9.1 计划暂存

| 写入操作可暂存供批准
| 转换为 PlanItem 对象
| 人机协作工作流支持

### 9.2 跨盒移动

| 支持跨盒移动记录
| 带盒级定位的批操作
| 移动内的位置映射

### 9.3 流式事件

| 执行期间的实时反馈
| 事件类型: step_start, tool_start, tool_end, final 等
| 跨事件的 trace ID 关联

### 9.4 多语言支持

| 中英文操作名称
| 双语错误消息
| 本地化搜索模式

---

## 10. 安全与审计

### 10.1 审计日志

| 所有操作记录完整上下文
| JSONL 格式以便解析
| 包含 actor、session、trace ID

### 10.2 备份机制

| 写入前自动时间戳备份
| 可配置保留策略
| 一键回滚功能

### 10.3 验证层次

1. **输入验证**: 每个工具函数首先验证输入参数
2. **业务逻辑验证**: Operations 模块检查业务规则
3. **数据完整性验证**: 写入前的完整文档验证
4. **位置冲突检查**: 确保无双重占用
5. **审计追踪**: 跨所有操作维护审计上下文

---

## 11. 部署选项

### 11.1 开发模式

```bash
python scripts/stats.py --visual
```

### 11.2 CLI 模式

```bash
python agent/run_agent.py "query K562 records" --yaml ln2_inventory.yaml
```

### 11.3 GUI 模式

```bash
pip install PySide6
python app_gui/main.py
```

### 11.4 Windows EXE 打包

```bash
pip install pyinstaller
pyinstaller ln2_inventory.spec
# 输出: dist/LN2InventoryAgent/
```

### 11.5 Setup 安装包

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\windows\LN2InventoryAgent.iss
# 输出: dist/installer/LN2InventoryAgent-Setup-<version>.exe
```

---

## 12. 关键架构原则

1. **职责分离**: 每个模块有明确的职责
2. **单一职责**: 没有模块处理超过一个主要关注点
3. **依赖方向**: 高层模块依赖低层模块
4. **统一接口**: 所有操作遵循相同的结果格式
5. **审计追踪**: 记录所有操作的审计日志
6. **原子操作**: 写入是原子的，带备份能力
7. **错误弹性**: 通过信息性消息优雅处理失败
8. **可扩展性**: 模块化设计允许轻松扩展工具

---

## 13. 依赖关系图

```
                    ┌─────────────┐
                    │  scripts/   │
                    │  CLI Tools  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ tool_api.py │ ◄─────┐
                    └──────┬──────┘       │
                           │              │
        ┌──────────────────┼──────────────┼──────────────────┐
        │                  │              │                  │
┌───────▼────────┐ ┌──────▼──────┐ ┌─────▼─────┐ ┌─────────▼────────┐
│   yaml_ops.py   │ │ validators  │ │ operations│ │   thaw_parser    │
└───────┬────────┘ └─────────────┘ └───────────┘ └──────────────────┘
        │
┌───────▼────────┐
│   config.py    │
└────────────────┘

        ┌─────────────┐
        │  app_gui/   │
        └──────┬──────┘
               │
        ┌──────▼──────┐
        │tool_bridge  │ ─────┐
        └─────────────┘      │
                           ┌─▼─────────────┐
                           │  tool_api.py   │
                           └───────────────┘

        ┌─────────────┐
        │   agent/    │
        └──────┬──────┘
               │
        ┌──────▼──────┐
        │tool_runner  │ ─────┐
        └─────────────┘      │
                           ┌─▼─────────────┐
                           │  tool_api.py   │
                           └───────────────┘
```

---

## 附录

### A. 文件清单

#### lib/
- `__init__.py`
- `config.py` - 配置管理
- `yaml_ops.py` - YAML 操作
- `validators.py` - 验证规则
- `operations.py` - 业务逻辑
- `tool_api.py` - 统一 API
- `thaw_parser.py` - 事件解析

#### agent/
- `__init__.py`
- `run_agent.py` - CLI 入口
- `llm_client.py` - LLM 客户端
- `react_agent.py` - ReAct 循环
- `tool_runner.py` - 工具分发器

#### app_gui/
- `__init__.py`
- `main.py` - 主窗口
- `gui_config.py` - GUI 配置
- `tool_bridge.py` - 工具桥接
- `plan_model.py` - 计划模型
- `ui/__init__.py`
- `ui/theme.py` - 主题
- `ui/utils.py` - 工具
- `ui/workers.py` - 异步工作器
- `ui/overview_panel.py` - 概览面板
- `ui/operations_panel.py` - 操作面板
- `ui/ai_panel.py` - AI 面板

#### scripts/
- `add_entry.py` - 添加记录
- `record_thaw.py` - 单次解冻
- `batch_thaw.py` - 批量解冻
- `query_inventory.py` - 查询库存
- `query_recent.py` - 最近查询
- `query_thaw.py` - 解冻查询
- `search.py` - 搜索
- `smart_search.py` - 智能搜索
- `stats.py` - 统计
- `recommend_position.py` - 位置推荐
- `check_conflicts.py` - 冲突检查
- `validate.py` - 验证
- `rollback.py` - 回滚
- `show_raw.py` - 原始数据
- `timeline.py` - 时间线

#### tests/
- `test_config.py` - 配置测试
- `test_yaml_ops.py` - YAML 测试
- `test_validators.py` - 验证器测试
- `test_validate.py` - 验证测试
- `test_thaw_parser.py` - 解析器测试
- `test_tool_api.py` - API 测试
- `test_tool_api_invariants.py` - API 不变量测试
- `test_llm_client.py` - LLM 测试
- `test_react_agent.py` - Agent 测试
- `test_agent_tool_runner.py` - 工具运行器测试
- `test_gui_bridge.py` - GUI 桥接测试
- `test_gui_tool_bridge.py` - GUI 工具桥接测试
- `test_gui_config.py` - GUI 配置测试
- `test_gui_panels.py` - GUI 面板测试
- `test_plan_model.py` - 计划模型测试

---

*本文档由 Claude Code 自动生成于 2026-02-12*
