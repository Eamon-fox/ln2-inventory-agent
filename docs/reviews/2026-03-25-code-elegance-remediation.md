# 2026-03-25 代码优雅性整改记录

本文档是本轮 `search_records` / 本地 Open API 契约收口整改的唯一记录。

## 任务归属

- 主要模块：`inventory_core`
- 次要模块：`gui_application`
- 共享瓶颈点：`lib/tool_registry.py`

## 契约收口原则

- 该紧的地方：
  - `search_records` 的对外语义说明必须与真实执行逻辑一致。
  - 本地 Open API 的 `dataset_schema` / `response_shapes` 必须从 `inventory_core` 共享来源导出，不能继续在 GUI 层手写镜像。
  - 中英文 local API skill template 必须指向同一套能力探测流程。
- 该松的地方：
  - 共享 helper 的具体命名和内部拆分。
  - 本地 Open API capability payload 的内部组装方式，只要对外字段保持稳定即可。

## 问题清单

### R1. 本地 Open API 在 GUI 层手写 `dataset_schema` / `response_shapes`

- 严重程度：高
- 模块归属：`inventory_core` + `gui_application`
- 共享瓶颈点：否
- 相关路径：
  - `app_gui/application/open_api/service.py`
  - `lib/tool_api_impl/read_ops.py`
  - `lib/overview_table_query.py`
- 初始问题：
  - `/api/v1/capabilities` 里新增的 `dataset_schema` / `response_shapes` 完全在 GUI 层手写。
  - 真实返回结构和字段语义却分别来自 `tool_search_records()`、`query_overview_table()` 以及有效字段推导逻辑。
  - 后续只要核心查询结果变动，就需要同时改 GUI 层说明，形成第二真相源。
- 整改目标：
  - 把公开查询契约 helper 收口到 `inventory_core`。
  - GUI 本地 Open API 只消费共享 helper，不再维护独立镜像。
- 契约文档：
  - 无需先更新
  - 本轮不改变外部稳定入口，只修复真相源归属
- 实施状态：已完成
- 修改记录：
  - 新增 `lib/inventory_query_contracts.py`，把公开 `dataset_schema` / `response_shapes` 组装逻辑收口到 `inventory_core`。
  - `app_gui/application/open_api/service.py` 改为直接复用共享 helper，不再在 GUI 层手写查询返回结构说明。
- 回归测试：
  - `python -m pytest -q tests/integration/gui/test_local_open_api.py`
- 现状：
  - 本地 Open API 已经只消费共享查询契约 helper，GUI 层不再维护一份独立镜像。
- 跨模块风险：
  - 若后续又在 GUI 层直接手写查询结果结构说明，会重新引入第二真相源。

### R2. `search_records` 共享 contract 文案与真实搜索语义漂移

- 严重程度：高
- 模块归属：`inventory_core`
- 共享瓶颈点：是，`lib/tool_registry.py`
- 相关路径：
  - `lib/tool_registry.py`
  - `lib/tool_api_impl/read_ops.py`
  - `app_gui/application/open_api/service.py`
- 初始问题：
  - `search_records.mode` 已经支持 `keywords`，并且真实语义区分了 separator-normalized 的 `fuzzy` / `keywords` / `exact`。
  - 但共享 tool contract 仍只写了泛化的 “Search strategy.”，新语义只出现在本地 Open API 说明里。
- 整改目标：
  - 把搜索语义说明抽成共享文本，由 `tool_registry` 和本地 Open API 共同复用。
  - 保证 Agent / GUI / Local API 对外描述一致。
- 契约文档：
  - 无需先更新
  - 本轮只修复共享 contract 文案漂移
- 实施状态：已完成
- 修改记录：
  - `lib/tool_registry.py` 改为复用共享搜索语义说明。
  - `lib/tool_api_impl/read_ops.py` 复用共享 `SEARCH_MODE_VALUES`，减少执行层与 contract 层的枚举漂移。
- 回归测试：
  - `python -m pytest -q tests/contract/test_tool_contracts_single_source.py`
  - `python -m pytest -q tests/integration/agent/test_agent_tool_runner.py -k search_records`
- 现状：
  - `search_records` 的共享 contract、Agent schema 来源和本地 Open API 说明现在使用同一套搜索语义文本。
- 跨模块风险：
  - 共享瓶颈点文案若再次手工复制到其他入口，会继续制造 contract drift。

### R3. 中文 local API skill template 仍停留在旧流程

- 严重程度：中
- 模块归属：`gui_application`
- 共享瓶颈点：否
- 相关路径：
  - `app_gui/assets/local_api_skill_template.en.md`
  - `app_gui/assets/local_api_skill_template.zh-CN.md`
  - `app_gui/ui/dialogs/settings_dialog.py`
- 初始问题：
  - 英文模板已经改成先读 `/api/v1/capabilities`、再读 `dataset_schema` / `response_shapes`。
  - 中文模板仍是旧工作流，Settings 对话框按语言读取模板时会把错误指导暴露给中文用户。
- 整改目标：
  - 让中英文模板遵循同一工作流，并通过现有动态 route reference 渲染输出。
- 契约文档：
  - 无需先更新
  - 本轮不改模板注入机制，只修正模板骨架内容
- 实施状态：已完成
- 修改记录：
  - `app_gui/assets/local_api_skill_template.zh-CN.md` 已同步到与英文模板一致的 capability-first 工作流。
  - 新增中文模板断言，确保 Settings 对话框暴露的内容不会再回退到旧流程。
- 回归测试：
  - `python -m pytest -q tests/unit/test_local_api_skill_template.py`
  - `python -m pytest -q tests/integration/gui/test_gui_panels_ops_settings.py -k local_api_skill_template`
- 现状：
  - 中英文 local API skill template 现在都要求先读 `/api/v1/capabilities`，再消费 `dataset_schema` / `response_shapes`。
- 跨模块风险：
  - 若仅更新英文模板而忽略其他语言，设置面板会持续暴露多入口不一致。

## 执行顺序

1. 先修复 R1，把本地 Open API 能力说明收口到 `inventory_core` 共享 helper。
2. 再修复 R2，让 `search_records` 共享 contract 和本地 Open API 复用同一套语义文案。
3. 最后修复 R3，并补齐中英文模板相关测试。
4. 回填本记录并执行最小回归集。

## 最终验收

- 最小测试命令：
  - `python -m pytest -q tests/contract/test_tool_contracts_single_source.py`
  - `python -m pytest -q tests/integration/gui/test_local_open_api.py tests/unit/test_local_api_skill_template.py`
  - `python -m pytest -q tests/integration/gui/test_gui_panels_ops_settings.py -k local_api_skill_template`
  - `python -m pytest -q tests/integration/agent/test_agent_tool_runner.py -k search_records`
- 最终结果：
  - `python -m pytest -q tests/contract/test_tool_contracts_single_source.py` -> `32 passed, 19 subtests passed`
  - `python -m pytest -q tests/integration/gui/test_local_open_api.py tests/unit/test_local_api_skill_template.py` -> `18 passed`
  - `python -m pytest -q tests/integration/gui/test_gui_panels_ops_settings.py -k local_api_skill_template` -> `3 passed, 108 deselected`
  - `python -m pytest -q tests/integration/agent/test_agent_tool_runner.py -k search_records` -> `12 passed, 85 deselected`
  - `git diff --check` -> 通过（仅有 Git CRLF 提示，无 diff 格式错误）
- 文档回填状态：已回填
