# Changelog

## 1.3.6 - 2026-03-21

### Added
- 首次启动现在会引导选择可写 `data-root`，库存数据固定存放在 `<data-root>/inventories/`，迁移工作区固定存放在 `<data-root>/migrate/`。
- 设置页支持迁移到新的 `data-root`，并在切换时保留当前数据集的相对路径。

### Changed
- 盒位展示统一改为“数字盒号优先，可选标签补充”的格式，Overview 网格、表格及其他展示入口保持同一套盒身份语义。
- GUI 配置改为保存在用户配置目录，并与安装目录中的可写库存数据解耦。
- 主题字体改为优先使用系统已安装的 UI 字体，减少不同平台上因缺字或字体不存在造成的界面观感偏差。

### Fixed
- 迁移工作区在缺少 `inputs`、`normalized` 或 `output` 目录时会自动重建，避免运行时因为目录缺失失败。
- Overview 表格排序对 location 和文本列使用稳定排序键，避免 Qt 原生排序过程中触发异常或错序。
- 盒标签较长时标题会截断、tooltip 保留完整内容，避免界面中标签覆盖掉稳定盒号信息。
- AI 迁移流程在源 YAML 已经符合目标 schema 时会直接复制文件，不再把整份大文件重新读出再写回，减少大库存迁移时的失败面。
- 导入迁移输出时会基于当前 `data-root` 解析 `migrate/output/ln2_inventory.yaml`，避免升级后仍错误回落到旧安装目录路径。
- 旧字段兼容链路保持可用，历史 `storage` / 日期 / `cell_line` 等字段在迁移、校验、回滚和升级后的受管路径下继续正常工作。

## 1.3.5 - 2026-03-20

### Added
- Overview 视图支持空位多选，便于一次规划多个新增位置。
- 设置页支持调整自定义字段顺序，操作表单与上下文展示会按 schema 顺序保持一致。
- 网站历史版本 list 现在会显示版本发布日期，并在悬停时展示该版本摘要。

### Changed
- 操作单打印流程改为系统打印预览对话框，不再依赖先打开浏览器中转。
- 打印版操作单网格样式重做，占位标签显示更完整，边框、标记和浅色打印效果更清晰。
- Overview 网格、表格状态色和行内图标进一步统一到同一套主题视觉语言。
- AI 会话运行时从 GUI bridge 中拆出独立 session service，设置变更后的 API Key 同步路径更明确。
- 发布脚本与文档统一改为以 `app_gui/version.py` 作为版本权威源，并明确同步安装器默认版本。

### Fixed
- 计划合并前会更早识别 “add 覆盖 add” 冲突，减少批量执行时的晚发现错误。
- 计划校验入口下沉到共享核心后，GUI 与 Agent 对同类计划的规则来源保持一致。
- 设置保存后，当前 AI 会话会立即刷新 API Key 配置，避免继续沿用旧会话参数。

## 1.3.4 - 2026-03-18

### Added
- Batch add API (`tool_batch_add_entries`) for single-cycle bulk execution.
- Activity indicator with pulsing dot, elapsed timer, and tool name display during agent processing.
- Markdown rendering in agent question dialogs.
- Context compressor module: sliding-window + summarization replaces hard truncation for bulk operations.
- Backup file validation before rollback with alternative backup suggestions on failure.
- Unified `PlanItem` TypedDict and `PlanItemPayload` as single source of truth for plan item structure.
- Shared validation primitives module (`lib/validation_primitives.py`) consolidating record validation logic.
- Single source of truth for version constants (`app_gui/version.py`).

### Changed
- "Clear" button in AI panel renamed to "New Chat", now resets both UI display and agent context with confirmation dialog.
- Global custom-field schema remains the only supported model; datasets using legacy `meta.box_fields` are now rejected.
- Tool registry now derives `WRITE_TOOLS`, `MIGRATION_TOOL_NAMES`, and `VALID_PLAN_ACTIONS` from `TOOL_CONTRACTS` metadata flags.
- Dataset path normalization and combo builder extracted to shared helpers in `lib/inventory_paths.py`.
- Batch plan execution optimized from 10+ seconds to ~1 second for 100+ operations.

### Fixed
- Context truncation too aggressive during bulk add operations, causing LLM to lose earlier tool results.
- User interruption causing inconsistent conversation history (orphaned tool-call/result groups).
- Rollback failures on certain backup points due to missing pre-validation.
- Conflict detection during migration misleadingly reporting batch-internal conflicts as existing-inventory conflicts.
- Baseline `TestColorPalette` test assertions updated to match current theme implementation.
- PyInstaller spec now reads version from `app_gui/version.py` with type-annotation-aware regex.

## 1.3.3 - 2026-03-05

### Added
- Added segmented toggles for operation mode and overview view mode.
- Added overview row context menu actions with shared cell logic and AI slot-context handoff.

### Changed
- Streamlined overview and home toolbar layout by removing redundant labels/buttons.
- Refactored Manage Boxes into a single-page dialog flow.
- Simplified overview advanced filters and improved operation confirm/status visibility.
- Consolidated migration UX in AI panel and enforced migration-mode panel behavior.
- Improved tooltip wrapping/spacing and adjusted overview cell visual tone mapping.

### Fixed
- Fixed plan card action bar placement and styling regressions.
- Fixed missing i18n strings for AI migration exit flow.
- Fixed regression tests for bash availability and updated UI expectation coverage.

## 1.3.2 - 2026-03-04
- Settings custom-field edits now include service-layer backup and audit persistence.
