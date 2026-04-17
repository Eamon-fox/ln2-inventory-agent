# 架构边界兼容说明

本文件保留原路径，用于兼容既有引用。

新的权威架构文档拆分为：

1. `00-约束模型.md`
2. `01-系统架构总览.md`
3. `02-模块地图.md`
4. `03-共享瓶颈点.md`

## 仍然有效的核心边界

### 分层方向

当前桌面端仍遵循自上而下的依赖方向：

1. `app_gui/ui/*`
2. `app_gui/main.py` 与 `app_gui/main_window_flows.py`
3. `app_gui/application/*`
4. `lib/domain/*`
5. `lib/*`

### 继续生效的禁止项

- `lib/domain/*` 不得依赖 `PySide6`
- `lib/domain/*` 不得依赖 GUI widget 或 GUI 状态对象
- `app_gui/ui/*` 不得直接导入 `lib.tool_api_write*`
- `app_gui/ui/*` 不得直接导入 `lib.tool_api_write_validation`
- 写入工作流应由应用协调层统一编排，而不是散落在 UI 组件里

### 当前 GUI 应用层稳定入口

- `DatasetUseCase.switch_dataset`
- `MigrationModeUseCase.set_mode`
- `PlanExecutionUseCase.report_operation_completed`
- `PlanRunUseCase.execute`

### 当前 OperationsPanel 稳定公共方法

OperationsPanel / OverviewPanel / AIPanel 的跨模块稳定公共方法清单以
`docs/modules/10-界面展示层.md` 为准，本文件不再维护独立副本以避免第二真相源漂移。

### OperationsPanel 内部协作面

`OperationsPanel` 自身由 `app_gui/ui/operations_panel_*.py` 一组兄弟模块拆分实现。
以下下划线前缀名字是这组兄弟模块之间的内部协作 helper，允许被同一 OperationsPanel 包
内的兄弟模块以及 `tests/integration/gui/` 下的 GUI 集成测试消费：

- `_lookup_record`（定义：`operations_panel_context.py`）
- `_refresh_takeout_record_context`
- `_refresh_move_record_context`
- `_rebuild_custom_add_fields`
- `_handle_response`
- `_get_selected_plan_rows`
- `_enable_undo`
- `_build_print_grid_state`

它们不属于跨模块稳定入口：`app_gui/application/`、`agent/`、`lib/` 等外部模块不得直接
依赖这些名字。若未来决定彻底收敛这部分 helper，请先一并更新所有兄弟模块与测试的调用
点，再把本节改回硬性禁止。

## 使用方式

如果你是 agent：

1. 先看 `../AGENTS.md`
2. 再看 `00-约束模型.md`
3. 再看 `01-系统架构总览.md`
4. 再看 `02-模块地图.md`
5. 最后把本文件当作历史兼容与补充边界说明
