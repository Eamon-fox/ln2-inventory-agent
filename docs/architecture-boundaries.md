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

以下方法继续视为跨模块稳定入口，新增、删除或重命名都属于架构级变更：

- `apply_meta_update`
- `set_migration_mode_enabled`
- `update_records_cache`
- `set_prefill`
- `set_prefill_background`
- `set_add_prefill`
- `set_add_prefill_background`
- `add_plan_items`
- `execute_plan`
- `clear_plan`
- `reset_for_dataset_switch`
- `on_export_inventory_csv`
- `emit_external_operation_event`
- `print_plan`
- `print_last_executed`
- `on_undo_last`
- `remove_selected_plan_items`
- `on_plan_table_context_menu`

### 当前已移除的私有别名约束

以下私有桥接别名保持移除状态，不得在测试或跨模块调用中重新引入：

- `_lookup_record`
- `_refresh_takeout_record_context`
- `_refresh_move_record_context`
- `_rebuild_custom_add_fields`
- `_handle_response`
- `_get_selected_plan_rows`
- `_enable_undo`
- `_build_print_grid_state`

## 使用方式

如果你是 agent：

1. 先看 `../AGENTS.md`
2. 再看 `00-约束模型.md`
3. 再看 `01-系统架构总览.md`
4. 再看 `02-模块地图.md`
5. 最后把本文件当作历史兼容与补充边界说明
