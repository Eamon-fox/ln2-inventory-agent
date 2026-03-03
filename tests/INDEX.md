# Test Index

测试按类型分三层：`unit/`（纯函数）、`integration/`（多模块协作）、`contract/`（一致性/卫生检查）。

## unit/ — 纯函数，无 I/O

- test_validators.py - Field and model validation rules. <!-- 字段与模型验证规则 -->
- test_validators_conflict.py - Conflict detection in plan items. <!-- 计划项冲突检测 -->
- test_validate.py - Validation entrypoint behavior. <!-- 验证入口行为 -->
- test_takeout_parser.py - Takeout parser normalization rules. <!-- 取出操作解析与别名标准化 -->
- test_position_fmt.py - Position conversion and formatting helpers. <!-- 位置格式化辅助函数 -->
- test_event_compactor.py - Event compaction for GUI timelines. <!-- GUI 时间线事件压缩 -->
- test_tool_status_formatter.py - Tool status output formatting. <!-- 工具状态消息格式化 -->
- test_config.py - Config loading, overrides, and defaults. <!-- 配置加载、覆盖与默认值 -->
- test_error_localizer.py - Error code to localized message mapping. <!-- 错误码到本地化消息的映射 -->

## integration/ — 多模块协作，读写真实文件

### inventory/ — 核心库存操作

- test_tool_api.py - Primary Tool API across read and write workflows. <!-- Tool API 全链路读写 -->
- test_tool_api_extended2.py - Extended Tool API edge cases. <!-- Tool API 扩展场景与边界 -->
- test_tool_api_invariants.py - Invariant checks for Tool API consistency. <!-- Tool API 一致性不变式 -->
- test_tool_api_cell_line_migration.py - Cell-line migration via Tool API. <!-- 通过 Tool API 进行 cell_line 字段迁移 -->
- test_yaml_ops.py - YAML load, write, audit, and backup behavior. <!-- YAML 读写、审计日志与备份 -->
- test_custom_fields.py - Custom-field schema, persistence, and query. <!-- 自定义字段的模式、持久化与查询 -->
- test_inventory_paths.py - Inventory path resolution and file locations. <!-- 库存路径解析与文件定位 -->
- test_lib_missing.py - Library regression tests for missing/invalid inputs. <!-- 缺失或无效输入的回归测试 -->

### plan/ — 计划暂存与执行

- test_plan_model.py - Plan model normalization and schema behavior. <!-- 计划项模型标准化与结构验证 -->
- test_plan_store.py - Plan store persistence and lifecycle. <!-- 计划存储的持久化与生命周期 -->
- test_plan_gate.py - Plan gate preflight validation and blocking rules. <!-- 计划门控预检与阻塞规则 -->
- test_plan_executor.py - Plan execution engine and operation orchestration. <!-- 计划执行引擎与操作编排 -->
- test_plan_preview.py - Preview generation for staged plan operations. <!-- 已暂存计划的预览生成 -->
- test_plan_outcome.py - Plan outcome shaping and result summaries. <!-- 计划执行结果汇总 -->

### agent/ — AI Agent 与工具调度

- test_react_agent.py - ReAct loop, tool-calling, retry, and finalization. <!-- ReAct 循环、工具调用、重试与结束 -->
- test_agent_tool_runner.py - Tool dispatch, validation, and handler behavior. <!-- 工具分发、验证与处理器行为 -->
- test_agent_missing.py - Agent edge cases and regression guards. <!-- Agent 边界情况与回归防护 -->
- test_llm_client.py - LLM client payload shaping and response normalization. <!-- LLM 客户端请求构造与响应标准化 -->
- test_question_tool.py - Question tool flow for agent workflows. <!-- Agent 用户询问工具的交互流程 -->
- test_terminal_tool.py - Terminal execution wrapper and error handling. <!-- 终端命令执行包装与错误处理 -->
- test_file_ops_client.py - File operations client and in-process service calls. <!-- 文件操作客户端与进程内服务调用 -->

### gui/ — GUI 面板与主窗口

- test_gui_panels_ops_settings.py - Operations + settings panel behavior split from legacy monolith. <!-- Operations 与 Settings 面板行为（由原超大文件拆分） -->
- test_gui_panels_overview.py - Overview panel interactions and marker rendering split from legacy monolith. <!-- Overview 面板交互与标记渲染（由原超大文件拆分） -->
- test_gui_panels_ai.py - AI panel streaming + event-feed behavior split from legacy monolith. <!-- AI 面板流式输出与事件流行为（由原超大文件拆分） -->
- test_gui_panels_plan_flows.py - Plan dedup/fallback/undo/print/preflight regressions split from legacy monolith. <!-- Plan 去重/回退/撤销/打印/预检回归（由原超大文件拆分） -->
- test_gui_panels_data_views.py - Cell-line dropdown + overview data-view behavior split from legacy monolith. <!-- Cell-line 下拉与 Overview 数据视图行为（由原超大文件拆分） -->
- test_gui_panels_new.py - Additional panel and recent interaction cases. <!-- 面板补充测试与最新交互场景 -->
- test_gui_config.py - GUI config persistence, defaults, and migration. <!-- GUI 配置持久化、默认值与迁移 -->
- test_gui_tool_bridge.py - GUI-to-tool bridge invocation and payload mapping. <!-- GUI 到工具桥接的调用与参数映射 -->
- test_main_window_flows.py - End-to-end main window user flows. <!-- 主窗口端到端用户流程 -->
- test_main.py - Application entrypoint and launch behavior. <!-- 应用入口与启动行为 -->
- test_audit_dialog.py - Audit dialog rendering and interaction logic. <!-- 审计日志对话框渲染与交互 -->
- test_overview_box_tags.py - Overview box tag display and update. <!-- 概览网格 box 标签显示与更新 -->
- test_app_gui_missing2.py - GUI regressions for partial/missing data. <!-- 数据缺失或不完整时的 GUI 回归测试 -->
- test_dataset_session.py - Dataset session switching and path refresh. <!-- 数据集会话切换与路径刷新 -->
- test_main_ui_scale_policy.py - UI scaling policy and 4K detection. <!-- UI 缩放策略与 4K 显示器检测 -->

### migration/ — 数据导入与迁移

- test_import_acceptance.py - Acceptance-level import scenarios. <!-- 导入流程的验收测试场景 -->
- test_import_journey.py - Unified import flow and failure handling. <!-- 统一导入流程与失败处理 -->
- test_migration_workspace.py - Migration workspace staging and path handling. <!-- 迁移工作区暂存与路径管理 -->
- test_migration_assets_templates.py - Migration prompt and runbook templates. <!-- 迁移提示词与运行手册模板 -->
- test_migrate_cell_line_policy.py - Cell-line migration policy checks. <!-- cell_line 迁移策略检查 -->
- test_xlsx_preconvert.py - XLSX to YAML pre-conversion and asset generation. <!-- XLSX 到 YAML 的预转换与资源生成 -->

## contract/ — 一致性检查，上线前门控

- test_tool_contracts_single_source.py - Canonical tool contract source enforcement. <!-- 工具契约单一来源执行检查 -->
- test_i18n_hygiene.py - Translation key hygiene and coverage. <!-- 翻译键卫生与中英文覆盖完整性 -->
- test_path_policy.py - Path escape and security policy enforcement. <!-- 路径逃逸与安全策略执行 -->
- test_installer_windows_script.py - Windows installer script config preservation. <!-- Windows 安装脚本配置保留检查 -->

## 新增测试规则

添加测试文件时，在同一 PR 的对应分组下补充一行。
