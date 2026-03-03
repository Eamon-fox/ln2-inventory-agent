# LN2 Migration Runtime Workspace

`migrate/` is a **runtime sandbox** only.

Use it for per-run data:
- `inputs/*` (staged source files)
- `normalized/*` (auto-generated CSV/schema assets from XLSX pre-conversion)
- `output/*` (conversion outputs and reports)

Do not store static migration guidance here.

Static guidance moved to:
- `migration_assets/templates/*`
- `migration_assets/schema/*`
- `migration_assets/examples/*`
- `validate_migration_output` tool (writes `migrate/output/validation_report.json`)

Required output contract stays unchanged:
- Output YAML path: `migrate/output/ln2_inventory.yaml`
- Top-level keys: `meta`, `inventory`
- Data model: tube-level (`inventory[]` item = one physical tube)


---

This sandbox is mainly used for the “migration” task. However, if you’re not in migration mode, you can still use it to store some temporary intermediate scripts or files. But regardless of the mode, please clean up this space promptly after you’re done.

