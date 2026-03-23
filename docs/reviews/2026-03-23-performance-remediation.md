# 2026-03-23 Performance Review / Remediation

## 任务归属
- 主要模块：`gui_application`、`agent_runtime`
- 热点入口：计划暂存 preflight、agent context checkpoint
- 资源类型：延迟、CPU、token 预算开销

## 基线
- 证据来源：现有性能测试、静态扫描、最小实测
- 当前指标：
  - `tests/integration/plan/test_batch_execute_performance.py`：`8 passed in 1.82s`
  - `preflight_plan(100 adds)`：`673.75ms` 平均
  - `run_plan(..., mode="execute")(100 adds)`：`211.73ms` 平均
  - `_cap_fold_messages_for_summary(100 synthetic messages)`：`389.10ms`
- 目标指标：
  - 降低 valid-path preflight 扇出开销，避免 100 条 add 仍然逐条 dry-run
  - 降低 checkpoint summary cap 的重复序列化开销
- 暂定区域：
  - [app_gui/plan_executor.py](/D:/github_repo/ln2-inventory-agent/app_gui/plan_executor.py)
  - [agent/context_checkpoint.py](/D:/github_repo/ln2-inventory-agent/agent/context_checkpoint.py)

## 问题清单

### P1. preflight valid-path 仍按逐条工具预检扇出
- 严重程度：高
- 热点路径：`OperationsPanel -> validate_stage_request -> preflight_plan -> run_plan(preflight) -> add/takeout preflight`
- 相关路径：
  - [app_gui/ui/operations_panel_plan_store.py](/D:/github_repo/ln2-inventory-agent/app_gui/ui/operations_panel_plan_store.py)
  - [lib/plan_gate.py](/D:/github_repo/ln2-inventory-agent/lib/plan_gate.py)
  - [app_gui/plan_executor.py](/D:/github_repo/ln2-inventory-agent/app_gui/plan_executor.py)

初始问题：

valid-path preflight 对 add/takeout 仍逐条调用 write-tool 预检，导致计划暂存变大时用户感知延迟明显上升。

现象：

同规模 `100` 条 add 下，`preflight_plan` 平均约 `673.75ms`，显著慢于 execute 路径的 `211.73ms`。

证据：

- `perf_probe.py` 已将 `preflight_plan` 标记为 suspected bottleneck
- `preflight_plan()` 每次创建临时 dataset，再走完整 `run_plan(preflight)`
- `_preflight_batch_add()`、`_execute_takeout(... mode='preflight')` 都存在逐条预检

整改目标：

优先压缩 valid-path fanout，保持错误语义尽量不变。

实施状态：已完成

修改记录：

- `app_gui.plan_executor._preflight_batch_add` 增加 valid-path batch fast path
- `app_gui.plan_executor._execute_takeout(... mode="preflight")` 增加 valid-path batch fast path
- 保留失败路径逐条定位，避免牺牲错误定位语义

复测结果：

- `preflight_plan(100 adds)`：`673.75ms -> 203.03ms`，下降约 `69.9%`
- `run_plan(..., mode="execute")(100 adds)`：`211.73ms -> 218.09ms`，基本持平
- 新增结构回归：
  - multi-add preflight success 必须走 batch fast path
  - multi-takeout preflight success 必须走 batch fast path

现状：

- valid-path preflight 已基本收敛到 execute 同量级
- 失败路径仍允许回退到更细粒度定位

残余风险：

- 失败路径若仍需要逐条定位，可能继续保留较高开销

### P2. checkpoint summary cap 反复重建大 JSON 载荷
- 严重程度：高
- 热点路径：`ReactAgent step -> checkpoint_context -> _cap_fold_messages_for_summary`
- 相关路径：
  - [agent/react_agent_runtime.py](/D:/github_repo/ln2-inventory-agent/agent/react_agent_runtime.py)
  - [agent/context_checkpoint.py](/D:/github_repo/ln2-inventory-agent/agent/context_checkpoint.py)

初始问题：

summary cap 在 fold 消息增长过程中反复重建完整 summary payload 并重新序列化，导致长会话下本地 CPU 开销偏高。

现象：

合成基准里 `_cap_fold_messages_for_summary(100 messages)` 约 `389.10ms`，明显高于同路径中的其它预算函数。

证据：

- `_cap_fold_messages_for_summary()` 在循环中反复 `build_summary_call_messages(... candidate)`
- `build_summary_call_messages()` 对 `fold_messages` 做整段 `json.dumps(...)`

整改目标：

把 summary cap 从线性重复重序列化改成更少次数的预算判断，并压缩 summary payload 的序列化体积。

实施状态：已完成

修改记录：

- `agent.context_checkpoint.build_summary_call_messages` 改为紧凑 JSON
- `_cap_fold_messages_for_summary` 改为二分搜索最大可容纳前缀，避免线性重建 summary payload

复测结果：

- `_cap_fold_messages_for_summary(100 synthetic messages)`：`389.10ms -> 15.74ms`
- `_cap_fold_messages_for_summary(400 synthetic messages)`：`369.61ms -> 31.76ms`
- 新增结构回归：
  - `64` 条消息下，summary cap 的 budget-check 次数受限为 `<= 8`

现状：

- summary cap 的主要 CPU 热点已显著下降
- 其余 token 估算函数仍为轻量启发式估算

残余风险：

- token 估算仍是启发式，不是 provider 官方 tokenizer

## 最终验收
- 最小 benchmark / profile 命令：
  - `.\.venv\Scripts\python.exe -m pytest -q tests/integration/plan/test_batch_execute_performance.py`
  - `.\.venv\Scripts\python.exe -m pytest -q tests/integration/plan/test_plan_executor.py tests/integration/agent/test_context_checkpoint.py`
- 更高层压测或回归命令：
  - `.\.venv\Scripts\python.exe -m pytest -q tests/integration/plan tests/integration/agent tests/contract`
- 测试结果：
  - `.\.venv\Scripts\python.exe -m pytest -q tests/integration/agent/test_context_checkpoint.py tests/integration/plan/test_plan_executor.py tests/integration/plan/test_batch_execute_performance.py`
    - `60 passed in 2.53s`
  - `.\.venv\Scripts\python.exe -m pytest -q tests/integration/plan tests/integration/agent tests/integration/gui tests/unit/test_tool_hooks.py`
    - `973 passed, 23 warnings, 56 subtests passed in 41.23s`
- 文档回填状态：
  - 已完成
