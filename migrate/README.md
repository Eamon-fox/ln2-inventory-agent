# LN2 Migration Runtime Workspace

`migrate/` is a **runtime sandbox** only.

Use it for per-run data:
- `inputs/*` (staged source files)
- `normalized/*` (auto-generated CSV/schema assets from XLSX pre-conversion)
- `output/*` (conversion outputs and reports)

Do not store static migration guidance here.

Static guidance moved to:
- `agent_skills/migration/SKILL.md`
- `agent_skills/migration/references/*`
- `agent_skills/migration/assets/*`
- `agent_skills/shared/references/*`
- `validate` tool on repo-relative YAML paths such as `migrate/output/ln2_inventory.yaml`

Required output contract stays unchanged:
- Output YAML path: `migrate/output/ln2_inventory.yaml`
- Top-level keys: `meta`, `inventory`
- Data model: tube-level (`inventory[]` item = one physical tube)

Path convention:
- File tools and shell commands should both use repo-relative paths.
- When you mean the migration workspace, spell paths explicitly as `migrate/...`.


---

This sandbox is mainly used for the “migration” task. However, if you’re not in migration mode, you can still use it to store some temporary intermediate scripts or files. But regardless of the mode, please clean up this space promptly after you’re done.

---

本目录仅保留运行时活代码 `path_context.py`（被 `app_gui/migration_workspace.py` 及
`tests/integration/migration/test_path_context.py` 引用）与工作区占位目录
`inputs/` / `normalized/` / `output/`。历史一次性 ad-hoc 数据迁移脚本已于
2026-04-18 统一清理，详见 `docs/reviews/2026-04-18-code-elegance.md`。

