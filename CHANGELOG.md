# Changelog

## 1.3.9 - 2026-03-22

### Added
- 本地 Open API 新增 `/api/v1/capabilities`，可显式返回 allowlist、校验模式、stage 允许动作和每个接口的参数说明，便于外部 Agent 先读能力再调用。
- 本地 Open API 新增只读 `/api/v1/gui/stage-plan`，可查看当前 GUI 暂存计划区而不改变已有 staged items。

### Changed
- `/inventory/stats` 现在支持 `summary_only=true` 轻量模式，便于外部 Agent 先读取摘要统计而不是默认拉取完整重字段。
- `/session/switch-dataset`、`/gui/prefill-*`、`/gui/stage-plan` 的返回语义现在更明确，会显式区分 GUI handoff、仅暂存和未执行写入等状态。
- 发布文档契约明确“完整正式发版”必须包含 GitHub Release，同步收口到同一份 release 文案来源。

### Fixed
- 本地 Open API 的错误返回现在带有更可操作的结构化信息，例如 `field`、`expected_type`、`accepted_values` 和 `example_request`，减少调用方猜参成本。
- 本地 Open API 的校验模式提示与实际实现保持一致，不再让调用方误以为存在未开放的 `full` 模式。

## 1.3.8 - 2026-03-22

### Added
- 本地 Open API 现在支持受控的只读查询与 validated inventory route，外部 Agent 可以在不开放写操作的前提下读取当前数据集内容并切换 API 会话上下文。
- 设置页新增内置 Skill 模板展示与一键复制入口，帮助用户把 SnowFox 的本地 API 接入外部 AI Agent。
- 新增内置 `snowfox-system` skill 契约与配套测试，用统一文档描述系统能力边界、字段语义和常见工作流。
- 管理盒位对话框新增盒索引方式设置，支持在数据集层配置数字或 Alpha-Numeric 盒位索引。
- macOS 安装包现在带有 SnowFox 应用图标资源。

### Changed
- 盒位索引展示统一走共享位置格式化逻辑，Overview、审计、导出、打印等展示面改为使用同一套索引语义。
- 本地 API 与设置页文案补全后，Agent 接入流程更偏向“先拉起 App、检测 API、再读取能力”的结构化引导。

### Fixed
- 修复 Alpha-Numeric 索引在 Overview 表格视图、CSV 导出、打印快照与 Plan 展示中的格式漂移，避免不同入口混用“冒号+数字”和字母数字索引。
- 修复相关 i18n 文案缺口，并补齐索引展示、API 帮助与 Skill 契约的回归测试覆盖。

## 1.3.7 - 2026-03-22

### Added
- Agent 长会话现在支持外部上下文检查点摘要模块：在接近模型上下文预算时，会用当前所选模型在全新上下文中生成继续工作所需的 checkpoint summary。
- 架构文档新增 agent 上下文检查点契约，明确摘要调用、恢复提示词和 GUI 会话态的边界。

### Changed
- AI 会话运行时改为按模型预算触发上下文 checkpoint，不再以固定 48 条消息作为主路径上的记忆压缩阈值。
- `zhipu` 与 `minimax` 的默认上下文预算上调到 200K，并通过 session `summary_state` 在同一轮会话内持续回传恢复。

### Fixed
- 导入、迁移等长流程在多轮工具调用后更不容易因为上下文过早压扁而丢失已完成步骤、关键路径和待办状态。
- New Chat 现在会同时清空 AI 会话的 checkpoint summary 状态，避免新会话误继承旧任务记忆。

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
