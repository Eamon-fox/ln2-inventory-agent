# 2026-04-24 Code Elegance Remediation

## 任务归属 / 共享瓶颈点 / 契约收口原则

- 主要模块：`gui_application`、`agent_runtime`
- 次要影响：无
- 共享瓶颈点：本轮问题不要求修改硬契约列出的共享瓶颈文件；若后续触及 `app_gui/main.py` 或 `app_gui/tool_bridge.py`，需升级为跨模块变更。
- 契约收口原则：该紧的是 local Open API route contract 与实际 handler 的同源关系、agent runtime handler 绑定的单一落点、plan preflight/execute 语义一致性；该松的是模块内部文件拆分方式与 helper 命名。

## 问题清单

### R1. Local Open API service 过载

- 严重程度 / 模块归属 / 共享瓶颈点 / 相关路径：中 / `gui_application` / 否 / `app_gui/application/open_api/service.py`
- 初始问题 / 整改目标：`service.py` 同时承载 transport、请求解析、业务 handler、GUI handoff、stage plan 和服务生命周期；目标是保留 route contract，同模块内拆出 handler 与 HTTP server 职责。
- 契约文档：无需先更新；已有硬契约要求 local Open API route allowlist 与 handler contract 同源。
- 实施状态：已完成
- 修改记录：新增 `app_gui/application/open_api/http_service.py` 承载 loopback HTTP server lifecycle、request body parsing 与 JSON response transport；`app_gui/application/open_api/service.py` 收窄为 `LocalOpenApiController` 与 handler 业务逻辑，并保留 lazy `LocalOpenApiService` 兼容入口；`app_gui/application/open_api/__init__.py` 改为从新模块懒加载 service lifecycle。
- 回归测试：`python -m pytest -q tests/contract/test_local_open_api_boundary_contract.py tests/unit/test_local_api_skill_template.py tests/unit/test_tool_runtime_registry.py tests/unit/test_tool_api_write_adapter.py` 通过；`tests/integration/gui/test_local_open_api.py` 因当前解释器缺少 `PySide6` 在 collection 阶段阻断。
- 跨模块风险：低；route contract、controller handler 名称与对外 package 导出保持不变。

### R2. Agent handler facade 私有 re-export 面过宽

- 严重程度 / 模块归属 / 共享瓶颈点 / 相关路径：中 / `agent_runtime` / 否 / `agent/tool_runner_handlers.py`、`agent/tool_runner.py`
- 初始问题 / 整改目标：`tool_runner_handlers.py` 只把私有 `_run_*` helper 重新导出再由 runner 逐个绑定；目标是删除低价值 re-export 面，让 runner 直接绑定真实分组模块。
- 契约文档：无需先更新；只调整 `agent_runtime` 内部实现表达。
- 实施状态：已完成
- 修改记录：删除 `agent/tool_runner_handlers.py` 私有 re-export facade；`agent/tool_runner.py` 直接按 fileops/migration/plan/read/write 分组模块绑定 handler；`agent/tool_runtime_registry.py` 直接引用 rollback guard 的真实 write handler 模块。
- 回归测试：`python -m pytest -q tests/contract/test_tool_contracts_single_source.py tests/unit/test_tool_runtime_registry.py tests/integration/agent/test_agent_tool_runner.py` 执行到 135 passed，唯一失败为 `tests/contract/test_tool_contracts_single_source.py::ToolContractsSingleSourceTests::test_plan_model_uses_canonical_valid_actions` import GUI theme 时缺少 `PySide6`；`python -m pytest -q tests/contract/test_local_open_api_boundary_contract.py tests/unit/test_local_api_skill_template.py tests/unit/test_tool_runtime_registry.py tests/unit/test_tool_api_write_adapter.py` 通过。
- 跨模块风险：低；只删除无外部消费者的 agent runtime 内部 facade，`AgentToolRunner` 对外行为不变。

### R3. Plan preflight/execute 策略散落

- 严重程度 / 模块归属 / 共享瓶颈点 / 相关路径：中 / `gui_application` / 否 / `app_gui/plan_executor.py`、`app_gui/plan_executor_actions.py`
- 初始问题 / 整改目标：plan preflight/execute 维护独立的 batch fallback、report fanout、position conflict 映射和临时 YAML/cache choreography；目标是先收口重复 report/fallback 语义，降低后续策略抽取成本。
- 契约文档：无需先更新；本轮不改变稳定入口。
- 实施状态：已完成
- 修改记录：在 `app_gui/plan_executor_reports.py` 新增 `make_preblocked_item_report()` 与 `fanout_with_preblocked_items()`，统一 pre-blocked item 的 `validation_failed` / `position_conflict` 映射；`app_gui/plan_executor_actions.py` 的 batch add execute/preflight 路径复用该 helper，减少两套手写 fanout 分支。
- 回归测试：`python -m pytest -q tests/unit/test_tool_api_write_adapter.py` 通过；`tests/integration/plan` 与 `tests/unit/test_plan_item_desc.py` 因当前解释器缺少 `PySide6` 在 GUI/plan model import 阶段阻断；`python -m compileall -q app_gui agent lib` 通过。
- 跨模块风险：中低；本轮只先收口重复 report/fallback 语义，未改 `preflight_plan()` 的临时 YAML/cache 策略，后续若继续抽策略应单独做一轮。

## 最终验收

- 已通过：`python -m pytest -q tests/contract/test_local_open_api_boundary_contract.py tests/unit/test_local_api_skill_template.py tests/unit/test_tool_runtime_registry.py tests/unit/test_tool_api_write_adapter.py`
- 已通过：`python -m pytest -q tests/unit/test_tool_api_write_adapter.py`
- 已通过：`python -m compileall -q app_gui agent lib`
- 受阻：GUI/plan/部分 contract 集成测试需要 `PySide6`，当前解释器未安装，collection 阶段报 `ModuleNotFoundError: No module named 'PySide6'`。
- 文档回填状态：已回填。
