# 修改 Agent 前必读

适用模块：

- `agent_runtime`

当一个需求主要影响推理循环、上下文压缩、工具调用、工具恢复、问题确认流或模型调用行为时，先读本文档。

本文属于软约束，描述默认执行路径。必要时可以偏离，但不得违反硬约束。

## 先判断是不是纯 Agent 任务

以下情况通常属于纯 `agent_runtime`：

- 改 ReAct 循环
- 改历史一致性与上下文压缩
- 改工具 hooks
- 改工具调用恢复策略
- 改 question/confirmation 流程

以下情况不是纯 Agent 任务：

- 新增工具
- 修改工具参数契约
- 修改统一工具返回格式
- 改 GUI 侧桥接方法签名

这些都会命中共享瓶颈点或核心层边界。

## 开工顺序

1. 先读 `docs/modules/12-智能体运行时.md`
2. 判断是否会改 `lib/tool_registry.py`、`app_gui/tool_bridge.py`
3. 如果会改这些共享文件，先按跨模块任务拆分
4. 先改 agent 内部行为
5. 最后才改工具注册、桥接和外部暴露面

## 推荐拆分法

### 纯 Agent 行为优化

1. 改 `agent/react_agent.py`
2. 改 `agent/tool_runner*.py`
3. 改 hooks、guidance、validation
4. 跑 agent 测试

### Agent 接入新工具或新参数

1. 核心层先定工具真相
2. 单独一个人改 `lib/tool_registry.py`
3. Agent 再适配调度与提示
4. GUI 侧如有桥接需要，再单独适配

## 明确禁止

1. 不要在 prompt 或 runtime 里发明核心层不承认的新字段别名。
2. 不要把业务规则藏在 prompt 里替代代码规则。
3. 不要复制 `inventory_core` 的工具契约。
4. 不要依赖 GUI 私有实现。
5. 不要直接写 YAML 绕过统一 Tool API。

## 高冲突文件

- `lib/tool_registry.py`
- `app_gui/tool_bridge.py`

如果动到这些文件，就不是单纯的 Agent 调整。

## 最小测试集

- `pytest -q tests/integration/agent`
- `pytest -q tests/unit/test_tool_hooks.py`

如果改了工具契约或注册：

- `pytest -q tests/contract/test_tool_contracts_single_source.py`

## 完成标准

1. Agent 仍然服从核心层工具契约
2. 没有新增“仅 agent 知道”的业务规则
3. 历史与工具消息边界保持一致
4. 若改了工具暴露面，已同步更新文档与相关测试
