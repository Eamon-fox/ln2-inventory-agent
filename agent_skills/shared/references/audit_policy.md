# Audit And Confirmation Policy

Keep high-impact actions explicit and user-visible.

## Migration

- Ask for `target_dataset_name` before import.
- Ask for explicit `CONFIRM_IMPORT` before calling `import_migration_output`.
- Keep `migrate/output/validation_report.json` fresh before import.

## Current Inventory Repair

- Prefer visible tool calls over silent file reads.
- Keep repair intent, validation, and final write steps explicit.
- Respect backup and audit expectations before modifying managed inventory data.
