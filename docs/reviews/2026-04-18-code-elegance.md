# 2026-04-18 代码优雅性审查与整改记录

本轮审查目标：面向全仓扫描冗余 / 死代码，并以文档为中心做契约漂移检查——docs/ 每一句话是否都能在代码里落地。

## 任务归属

- 主要模块：文档契约（docs/）
- 次要模块：`gui_presentation`（`app_gui/ui/operations_panel*`）、`migration_import`（`migrate/`）
- 共享瓶颈点：`docs/architecture-boundaries.md`（历史兼容契约页）

## 契约收口原则

- 该紧：docs/ 中对"已移除 / 不得使用"的硬性断言；对稳定公共方法的列表；模块拥有路径。
- 该松：`migrate/` 下一次性脚本的命名、内部组织、是否归档。

## 问题清单

### R1. `docs/architecture-boundaries.md` §"已移除的私有别名约束" 与代码漂移

- 严重程度：高
- 模块归属：`gui_presentation`
- 共享瓶颈点：是（`docs/architecture-boundaries.md`）
- 相关路径：
  - `docs/architecture-boundaries.md:62-74`
  - `app_gui/ui/operations_panel_context.py`（`_lookup_record` 定义）
  - `app_gui/ui/operations_panel_staging.py`、`operations_panel_forms.py`、`operations_panel_plan_toolbar.py`、`operations_panel_actions.py`、`operations_panel_execution.py`、`operations_panel_results.py`（消费者）
  - `tests/integration/gui/test_gui_panels_ops_settings.py`、`test_gui_panels_plan_flows.py`（测试消费者）
- 初始问题：
  - 文档断言 `_lookup_record` / `_refresh_takeout_record_context` / `_refresh_move_record_context` / `_rebuild_custom_add_fields` / `_handle_response` / `_get_selected_plan_rows` / `_enable_undo` / `_build_print_grid_state` 八个私有别名"保持移除状态，不得在测试或跨模块调用中重新引入"。
  - 实际代码：八个名字全部存在且在 `operations_panel_*` 兄弟模块与集成测试中被多处调用。`grep` 命中 13 个文件。
  - 文档以"已移除"包装一个并未成立的约束，会让 agent 读完直接得出错误结论：禁止在测试或兄弟模块里使用，进而做出不必要的重命名或绕行。
- 整改目标：
  - 以文档为中心：承认这些名字是 `OperationsPanel` 在 sibling-module 分拆后的内部协作面，允许兄弟模块与测试支持层消费；不属于跨模块稳定入口。
  - 不触碰代码实现，只把文档描述对齐到现实。
- 契约文档：
  - 需先更新 `docs/architecture-boundaries.md`
  - 本条目不改变任何运行时行为
- 实施状态：已完成
- 修改记录：
  - 将"已移除的私有别名约束"章节改写为"OperationsPanel 内部协作面"，明确这些名字是 operations_panel 模块拆分后的 sibling-module 协作 helper，允许兄弟模块与 GUI 集成测试消费，但不得跨模块（例如被 `app_gui/application/` 或 `agent/`）直接调用。
- 回归测试：
  - 本条目仅改文档，无代码测试回归需求。
- 跨模块风险：
  - 低。若后续真的决定再次移除这些私有别名，需要先更新所有兄弟模块与测试的调用点，再把本节回退为"禁止"态。

### R2. `docs/architecture-boundaries.md` OperationsPanel 稳定方法列表 与 `docs/modules/10-界面展示层.md` 不一致

- 严重程度：中
- 模块归属：`gui_presentation`
- 共享瓶颈点：是（两份契约文档）
- 相关路径：
  - `docs/architecture-boundaries.md:41-60`（18 项）
  - `docs/modules/10-界面展示层.md:26-52`（25 项，多出 `refresh_plan_store_view` / `OverviewPanel.bind_plan_store` / `OverviewPanel.refresh_plan_store_view` / `AIPanel.apply_runtime_settings` / `AIPanel.prepare_external_prompt` / `AIPanel.runtime_settings_snapshot` / `AIPanel.has_running_task`）
- 初始问题：
  - 模块地图里的公共入口清单是真相源；`architecture-boundaries.md` 的同名清单是历史镜像，已经落后。
  - 这是典型的"第二真相源"漂移：同一概念两份列表独立维护。
- 整改目标：
  - 按仓库既有分层（01–03 + 模块地图为权威），把 `architecture-boundaries.md` 改为只引用模块文档，不再复制公共方法清单。
- 契约文档：
  - 需先更新 `docs/architecture-boundaries.md`
- 实施状态：已完成
- 修改记录：
  - 删除 `architecture-boundaries.md` 里 OperationsPanel 公共方法硬编码清单，改为一段"以 `docs/modules/10-界面展示层.md` 为准"的引用。
- 回归测试：
  - 无代码测试；是文档级一致性。
- 跨模块风险：
  - 低。

### R3. `migrate/` 下一次性脚本无调用者、无测试、无文档——直接删除

- 严重程度：中
- 模块归属：`migration_import`
- 共享瓶颈点：否
- 相关路径（全部已删除）：
  - `migrate/analyze_storage.py`、`auto_add_multiple_positions.py`、`check_all_multiple_positions.py`、`check_missing_records.py`、`compare_excel_inventory.py`、`convert_plasmid_data.py`、`convert_plasmid.py`、`execute_add_operations.py`、`final_fix.py`、`fix_cell_line.py`、`fix_conflicts.py`、`fix_thaw_events.py`、`resolve_conflicts.py`、`simple_add_multiple_positions.py`、`smart_add_operations.py`、`update_type_field.py`
  - `migrate/fixed_inventory.yaml`（由 `fix_cell_line.py` 生成的一次性产物）
  - `migrate/inventory_backup.yaml`（无任何引用）
- 初始问题：
  - 16 个独立脚本 + 2 个陈旧 YAML 产物，没有任何 `import` / 测试 / 文档 / PyInstaller spec / CI 引用。
  - 用户澄清"必要的向后兼容"指旧版本用户的**升级路径**（YAML 格式、配置兼容），不包括手动 ad-hoc 脚本。因此不保留。
- 整改目标：
  - 直接删除；`migrate/path_context.py` 是该目录唯一仍被运行时消费的模块，保留。
- 契约文档：
  - 无需更新顶层契约；同步精简 `migrate/README.md`。
- 实施状态：已完成
- 修改记录：
  - 删除上述 18 个文件。
  - `migrate/README.md` 移除"历史 ad-hoc 脚本"长列表，改为一行指向本 review 的清理记录。
- 回归测试：
  - `python -m pytest tests/ -q`
- 跨模块风险：
  - 极低。这些脚本本就与运行时隔离。

### R4. `scripts/` 下旧版发布脚本已无消费者——直接删除

- 严重程度：低
- 模块归属：`release_packaging`
- 共享瓶颈点：否
- 相关路径（全部已删除）：
  - `scripts/sync_website_version.py`
  - `scripts/update_history_versions.py`
  - `scripts/provider_system_message_probe.py`
- 初始问题：
  - `sync_website_version.py` / `update_history_versions.py`：`scripts/README.md` 原文自述"不再是正式发版流程的一部分"，当前下载页改为运行时读取 `/latest.json` 与 OSS `CHANGELOG.md`；全仓 `rg` 仅命中自身与 README。
  - `provider_system_message_probe.py`：手工探针脚本，全仓零外部引用。
- 整改目标：
  - 直接删除；`scripts/README.md` 里"旧脚本状态"小节同步移除。
- 契约文档：
  - 无需更新顶层契约。
- 实施状态：已完成
- 修改记录：
  - 删除三个脚本。
  - `scripts/README.md` 移除"旧脚本状态"章节。
- 回归测试：
  - `python -m pytest tests/ -q`
- 跨模块风险：
  - 极低；`release.sh` / `render_release_artifacts.py` / `validate_version.py` 是当前发版真相源，未触碰。

## 未发现漂移的文档（抽检记录）

- `docs/01-系统架构总览.md`：机器可读契约 `<!-- contract:... -->` 的路径与稳定入口全部存在。
- `docs/02-模块地图.md`：6 个模块的拥有路径、核心文件、允许/禁止依赖全部可核对。
- `docs/modules/12-智能体运行时.md`：`AgentToolRunner._dispatch_handlers`、`agent/tool_runner.py` 等入口可达。
- `docs/modules/13-库存核心.md`：`ValidationMessage` / `extract_error_details` / `_validate_data_or_error` / `_collect_legacy_warnings` / `create_yaml_backup` / `.last_backup.json` / `LN2_STRICT_LEGACY_VALIDATION` / `LN2_BACKUP_THROTTLE_SECONDS` 全部对得上。
- `docs/modules/14-导入迁移.md`：`migrate/inputs`、`migrate/normalized`、`migrate/output` 目录均存在。
- `docs/modules/10-界面展示层.md`：Overview 增量渲染契约所指 `tests/integration/gui/test_gui_panels_data_views.OverviewTableViewTests` 以及 add preview 锁测试 `tests/unit/test_overview_panel_add_preview.py` 均已落地。
- `scripts/README.md`：诚实标注了 `sync_website_version.py` / `update_history_versions.py` 为历史脚本，不在当前发布流程。

## 最终验收

- 文档改动：
  - `docs/architecture-boundaries.md`（R1、R2）
  - `migrate/README.md`（R3）
  - `scripts/README.md`（R4）
- 代码改动：删除 21 个孤儿文件（16 migrate/*.py + 2 migrate/*.yaml + 3 scripts/*.py）。
- 测试命令：
  - `python -m pytest tests/ -q`
