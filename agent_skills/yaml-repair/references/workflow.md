# YAML Repair Workflow

Use this workflow when the active managed inventory has YAML, schema, or structural data problems.

## Sequence

1. Start by running `validate` on the current repo-relative inventory YAML.
2. Inspect the current inventory and reproduce the issue with explicit tools.
3. Read shared schema references before changing field structure assumptions.
4. Keep repair actions visible and explain why each change is needed.
5. Prefer validation-first repair steps over speculative edits.

## Scope

- Current managed inventory under `inventories/<dataset>/inventory.yaml`
- Schema and field-structure issues
- Current-data integrity issues that require YAML-level analysis
