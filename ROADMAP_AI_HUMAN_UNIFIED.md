# ln2-inventory-agent 改造方向（AI + 人类共用工具）

## 1. 目标定义

把现有 `ln2-inventory` 从“脚本集合”升级为“可独立运行的软件”，并满足两条主线：

1. **基础功能（Human-first）**：人类通过 GUI（鼠标/键盘）完成查询、冻存、取出、回滚、统计等操作。
2. **扩展功能（AI-first）**：AI Agent 基于 ReAct 框架调用同一套工具完成同类操作。

核心要求：**AI 和人类必须共用同一套 Tool API，并产出同样格式的历史记录。**

---

## 2. 设计原则

- **单一事实来源**：YAML 仍是核心数据源；所有写操作统一走 `lib.yaml_ops.write_yaml`。
- **同一工具层**：GUI 不直接改 YAML，AI 也不直接改 YAML，二者都只能调用 Tool 层。
- **同一审计格式**：human/agent 写入同一个 `ln2_inventory_audit.jsonl`，字段结构一致。
- **先可用再智能**：先完成 GUI 基础流程，再接入 ReAct Agent。
- **可打包发布**：架构从一开始考虑 EXE 打包和本地离线运行。

---

## 3. 目标架构

```text
GUI (Human) ─┐
             ├── Application Service Layer ─── Unified Tool API ─── Domain/Validation ─── YAML + Audit
AI Agent ────┘            (Use Cases)              (same tools)         (existing lib/*)       (jsonl)
```

分层说明：

- **Domain/Validation 层**：复用现有 `lib/validators.py`、`lib/operations.py`、`lib/thaw_parser.py`。
- **Persistence 层**：复用现有 `lib/yaml_ops.py`（含 backup、rollback、audit、html snapshot）。
- **Unified Tool API 层（新增）**：把“查询/冻存/取出/回滚”等能力包装成统一函数接口。
- **Application Service 层（新增）**：协调入参、权限、错误处理、结果结构化输出。
- **UI 层（新增）**：桌面界面供人类操作。
- **Agent 层（新增）**：ReAct planner + tool executor，通过同一 Tool API 工作。

---

## 4. 统一 Tool API（关键）

建议将现有脚本能力抽象为稳定工具集合（示例）：

- `tool_query_inventory(...)`
- `tool_add_entry(...)`
- `tool_record_thaw(...)`
- `tool_batch_thaw(...)`
- `tool_recommend_position(...)`
- `tool_rollback(...)`
- `tool_timeline(...)`
- `tool_stats(...)`

约束：

- CLI 仅作为“薄封装”，最终调用这些工具。
- GUI 按钮点击最终调用这些工具。
- AI Agent 的 action 最终也调用这些工具。

这样可确保：业务逻辑只维护一份，避免 GUI/AI 两套实现分叉。

---

## 5. 历史记录统一规范（Human 与 Agent 同格式）

当前 `write_yaml` 已产出统一审计字段（如 `timestamp`、`action`、`source`、`before/after/delta`、`changed_ids`）。

在保持兼容前提下，建议扩展以下字段到每条审计事件：

- `actor_type`: `"human" | "agent"`
- `actor_id`: GUI 用户名 / agent 名称
- `channel`: `"gui" | "cli" | "agent"`
- `session_id`: 一次 GUI 会话或一次 agent 任务 ID
- `trace_id`: 一次完整业务请求链路 ID
- `tool_name`: 触发的统一工具名（如 `tool_add_entry`）
- `tool_input`: 经过脱敏后的关键输入摘要
- `status`: `"success" | "failed"`
- `error`: 失败原因（可空）

注意：`action`、`source`、`details` 继续保留，避免破坏现有日志读取逻辑。

---

## 6. 功能范围拆分

### Phase A（基础功能，面向人类）

- GUI 查询：按细胞系、质粒、盒子、位置、关键词。
- GUI 冻存录入：新增记录、冲突检测、位置推荐。
- GUI 取出/复苏：单条与批量操作。
- GUI 统计页：盒子占用率、空位、近期操作。
- GUI 回滚：备份列表 + 一键回滚。
- 全流程写入统一审计日志。

### Phase B（扩展功能，面向 AI）

- 接入 ReAct Agent（Think -> Act -> Observe 循环）。
- Agent action 只能调用 Unified Tool API。
- Agent 每一步工具调用都落审计日志（同格式）。
- 支持“自然语言 -> 工具链执行 -> 可解释结果”。

---

## 7. ReAct Agent 方案（扩展）

Agent 最小组成：

- `Planner`：根据用户自然语言生成下一步 action。
- `Tool Executor`：执行统一工具并返回结构化 observation。
- `Memory`：短期会话记忆（本次任务上下文）。
- `Guardrails`：高风险操作确认（如批量删除/回滚）。

执行约束：

- Agent 禁止直接读写 YAML 文件。
- Agent 禁止绕开工具层调用底层 I/O。
- 失败时必须返回可解释错误 + 建议下一步。

---

## 8. EXE 打包方向

目标：Windows/macOS 上“下载即用”的本地应用。

建议路线：

- GUI：`PySide6` 或 `Tauri + Web UI`（二选一，先求稳可用）。
- 打包：`PyInstaller`（先单平台），后续补多平台 CI。
- 数据目录：默认用户目录下创建 `ln2_inventory.yaml`、备份目录、审计日志。
- 配置入口：GUI 设置页维护 `LN2_CONFIG_FILE` 对应参数。

---

## 9. 里程碑建议

### M1：工具层统一（必须先做）
- 把脚本公共逻辑收敛到 Unified Tool API。
- CLI 改为调用 Tool API，保证行为不变。
- 审计字段补齐 `actor_type/channel/session_id/trace_id`。

### M2：GUI MVP（基础可用）
- 完成查询、冻存、取出、统计、回滚五个页面。
- 完成同格式审计日志校验。

### M3：ReAct Agent 接入
- 完成 Agent -> Tool API 的调用闭环。
- 完成 agent 步骤级日志记录与可解释输出。

### M4：EXE 发布
- 本地打包、安装说明、示例数据、最小用户文档。

---

## 10. 验收标准

- 人类 GUI 与 AI Agent 执行同一操作，生成的日志字段结构一致。
- 任意写操作均可在审计日志中回溯“谁在何时通过哪个工具做了什么”。
- YAML 数据一致性、备份、回滚能力不下降。
- 打包后可离线运行基础功能（不依赖 Claude Skill 环境）。

---

## 11. 一句话定位

`ln2-inventory-agent` = **一个面向实验室库存管理的 AI-native 本地软件**：
人类和 AI 共用同一套工具，走同一套审计链路，先把基础操作做稳，再把智能能力做强。
