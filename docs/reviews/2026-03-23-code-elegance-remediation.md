# 2026-03-23 代码优雅性整改记录

本文档是本轮代码优雅性整改的唯一问题记录文档。

用途：

1. 先落档本轮审查发现
2. 明确本轮是否需要先改契约文档
3. 再按优先级逐项整改
4. 每完成一项整改，回填修改记录、最小回归测试与当前现状

## 任务归属

- 主要模块：`gui_application`、`agent_runtime`
- 次要影响：`inventory_core`
- 共享瓶颈点：`app_gui/main_window_flows.py`、`app_gui/main.py`

## 契约收口原则

本轮按以下原则收口：

1. 继续复用已有硬契约，不新增实现细节级门禁
2. 已有契约已覆盖的边界，不再通过聊天约定补丁式维持
3. 该紧的地方：
   - 本地 Open API 对外参数面与真实执行语义一致
   - 共享瓶颈点只保留薄装配或兼容导出
   - agent runtime 的运行时元数据按工具聚合，避免散落多张并行表
4. 该松的地方：
   - flow 类的具体拆分文件名
   - runtime metadata 内部表达方式

## 问题清单

### R6. Local Open API 外部模板与真实 route contract 再次分叉

- 严重程度：高
- 模块归属：`gui_application`
- 共享瓶颈点：否
- 相关路径：
  - `app_gui/application/open_api/contracts.py`
  - `app_gui/assets/local_api_skill_template.en.md`
  - `app_gui/assets/local_api_skill_template.zh-CN.md`
  - `app_gui/ui/dialogs/settings_dialog.py`
  - `lib/tool_registry.py`

初始问题：

- `/api/v1/inventory/search` 的本地 Open API route contract 未反映核心层已支持的 `keywords` 模式
- Settings 中可复制的 local API skill template 继续手写维护 API Reference，已经漏掉 `case_sensitive`、`summary_only` 等真实参数面

整改目标：

- route contract 与核心搜索模式保持一致
- local API skill template 改为“静态骨架 + 基于 route contract 动态生成的 API 参考”，不再手写复制路由参数面

契约文档：

- 无需先更新
- 现有硬契约已明确要求 route params 与有效 handler contract 一致

实施状态：已完成

修改记录：

- `app_gui/application/open_api/contracts.py` 现在从 `lib.tool_registry.TOOL_CONTRACTS["search_records"]` 读取 `mode` 的 accepted values，避免本地 Open API 再手写一份过时枚举。
- 新增 `app_gui/application/open_api/skill_template.py`，把 local API skill template 的路由参数面改为从 `LOCAL_OPEN_API_ROUTE_SPECS` 动态渲染。
- `app_gui/ui/dialogs/settings_dialog.py` 不再直接把静态 markdown 原样展示给用户，而是在读取模板骨架后注入动态 route reference。
- 中英文本地模板 `app_gui/assets/local_api_skill_template.*.md` 现在只保留静态骨架，`## API Reference / ## API 说明` 里的路由参考不再手写维护。
- 补充 `tests/unit/test_local_api_skill_template.py`，并增强 `tests/integration/gui/test_local_open_api.py` 与 `tests/integration/gui/test_gui_panels_ops_settings.py`，覆盖 `keywords`、`case_sensitive`、`summary_only` 与动态模板渲染。

回归测试：

- 计划命令：
  - `python -m pytest -q tests/unit/test_local_api_skill_template.py tests/integration/gui/test_gui_panels_ops_settings.py tests/integration/gui/test_local_open_api.py`
- 实际执行：
  - 未执行 pytest。仓库要求使用 repo-local `.venv`，当前工作区不存在 `.venv\Scripts\python.exe`。
  - 已执行 `git diff --check`，通过。

现状：

- Settings 中可复制的 local API skill template 不再手写路由参数面，已经改成从 route contract 动态生成。
- `/api/v1/capabilities` 与外部 skill template 现在都会反映 `search_records` 的 `keywords` 模式。
- 本轮没有新增顶层契约；只是把现有契约要求真正落实到代码路径上。

跨模块风险：

- 若未来继续新增本地 Open API 路由，但不经过 `LOCAL_OPEN_API_ROUTE_SPECS`，仍会重新引入第二真相源。
### R7. agent runtime 元数据拆散在多张并行表里

- 严重程度：中
- 模块归属：`agent_runtime`
- 共享瓶颈点：否
- 相关路径：
  - `agent/tool_runtime_registry.py`
  - `agent/tool_runner.py`

初始问题：

- 一个工具的 schema enrich、guard、hint、status formatter、hooks 被分散到多张 map
- 新增或调整一个工具的运行时语义时，容易变成散弹式修改

整改目标：

- 把 agent runtime 的自定义元数据收口为按工具聚合的一份覆盖表
- 保留当前对外行为与测试语义，不把运行时特例回流到共享注册表

契约文档：

- 无需先更新
- 本轮只调整 `agent_runtime` 内部实现表达，不改变稳定入口

实施状态：已完成

修改记录：

- `agent/tool_runtime_registry.py` 新增 `ToolRuntimeOverride`，把原来分散在 layout/schema/guard/hint/status formatter/hooks/stage_guard 多张平行表里的元数据按工具聚合到 `_TOOL_RUNTIME_OVERRIDES`。
- `build_tool_runtime_specs()` 现在从单一 override 表读取运行时特例，不再跨多张 map 逐项拼装。
- 保持 `ToolRuntimeSpec`、`build_tool_runtime_specs()` 和 `AgentToolRunner` 的对外行为不变，未把运行时特例回流到 `lib/tool_registry.py`。
- 补充 `tests/unit/test_tool_runtime_registry.py`，显式锁定 `rollback` 仍然同时拥有 `input_guard` 和 `stage_guard`。

回归测试：

- 计划命令：
  - `python -m pytest -q tests/unit/test_tool_runtime_registry.py tests/integration/agent/test_agent_tool_runner.py`
- 实际执行：
  - 未执行 pytest。仓库要求使用 repo-local `.venv`，当前工作区不存在 `.venv\Scripts\python.exe`。
  - 已执行 `git diff --check`，通过。

现状：

- agent runtime 的自定义元数据现在按工具聚合，新增或调整一个工具时不再需要在多张并行表之间来回同步。
- 当前改动没有改变运行时稳定入口，只是降低了后续散弹式修改面。

跨模块风险：

- 后续如果再新增单独的平行 map，而不是继续扩展 `_TOOL_RUNTIME_OVERRIDES`，会把问题重新引入。
### R8. ManageBoxesFlow 真实实现仍滞留在共享瓶颈点

- 严重程度：中
- 模块归属：`gui_application`
- 共享瓶颈点：是
- 相关路径：
  - `app_gui/main_window_flows.py`
  - `app_gui/main.py`

初始问题：

- `ManageBoxesFlow` 的真实实现仍在 `app_gui/main_window_flows.py`
- 后续 box-layout 流程继续演进时，仍然默认落在共享瓶颈文件

整改目标：

- 把 `ManageBoxesFlow` 的真实实现下沉到 `app_gui/application/`
- `app_gui/main_window_flows.py` 对该 flow 只保留兼容导出，不再承载实现细节

契约文档：

- 无需先更新
- 本轮不改变共享瓶颈点列表，只做实现下沉和兼容导出

实施状态：已完成

修改记录：

- 新增 `app_gui/application/manage_boxes_flow.py`，把 `ManageBoxesFlow` 与其异步确认 session 的真实实现下沉到 `gui_application` 拥有路径。
- `app_gui/main_window_flows.py` 不再持有 `ManageBoxesFlow` 的具体实现，只保留从应用层导出的兼容入口。
- `app_gui/main.py` 直接从 `app_gui.application.manage_boxes_flow` 装配 `ManageBoxesFlow`，避免继续把该 flow 的真实实现挂在共享瓶颈文件后面。
- 现有 `tests/integration/gui/test_main_window_flows.py` 仍可从旧路径导入 `ManageBoxesFlow`，兼容入口未被打断。

回归测试：

- 计划命令：
  - `python -m pytest -q tests/integration/gui/test_main_window_flows.py tests/integration/gui/test_main.py`
- 实际执行：
  - 未执行 pytest。仓库要求使用 repo-local `.venv`，当前工作区不存在 `.venv\Scripts\python.exe`。
  - 已执行 `git diff --check`，通过。

现状：

- `ManageBoxesFlow` 的真实实现已不在 `app_gui/main_window_flows.py`，共享瓶颈点对 box-layout 流程的承载明显变薄。
- 本轮没有继续拆 `StartupFlow` / `WindowStateFlow` / `SettingsFlow` / `DatasetFlow`；后续若这些 flow 继续膨胀，仍建议按同样方式下沉。

跨模块风险：

- `app_gui/main.py` 仍是共享瓶颈点；若后续继续把更多窗口级包装方法堆回主窗口类，需要再开新一轮收口。
## 执行顺序

1. 先修复 R6，并补 local API/template 相关回归测试
2. 再修复 R7，保持 agent runtime 对外行为不变
3. 最后修复 R8，把 flow 实现从共享瓶颈点下沉
4. 回填本记录文档并执行最小测试集

## 最终验收

- 最小测试命令：
  - `python -m pytest -q tests/unit/test_local_api_skill_template.py tests/integration/gui/test_gui_panels_ops_settings.py tests/integration/gui/test_local_open_api.py`
  - `python -m pytest -q tests/unit/test_tool_runtime_registry.py tests/integration/agent/test_agent_tool_runner.py`
  - `python -m pytest -q tests/integration/gui/test_main_window_flows.py tests/integration/gui/test_main.py`
- 最终结果：
  - pytest 未执行。仓库要求使用 repo-local `.venv`，当前工作区不存在 `.venv\Scripts\python.exe`。
  - `git diff --check` 已执行，通过。
- 文档回填状态：R6 / R7 / R8 已回填

## 2026-03-23 补充验收

- repo-local `.venv` 已创建，并在其中安装 `requirements.txt` 与 `pytest`。
- 已执行定向回归：
  - `python -m pytest -q tests/integration/gui/test_main_window_flows.py::test_manage_boxes_flow_prompt_request_uses_dialog_result`
  - 结果：`1 passed`
- 已执行全量测试：
  - `python -m pytest tests/`
  - 结果：`1805 passed, 23 warnings`
- R8 补充兼容修复：
  - `app_gui/main_window_flows.py` 现在保留一个仅覆盖 `prompt_request()` 的薄兼容导出。
  - 旧路径 `app_gui.main_window_flows.ManageBoxesDialog` 仍可被测试和补丁逻辑命中。
  - `ManageBoxesFlow` 的真实实现仍保留在 `app_gui/application/manage_boxes_flow.py`，没有回流到共享瓶颈点。
