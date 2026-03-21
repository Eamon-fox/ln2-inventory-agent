# Migration Workflow

Use this workflow when converting staged source files into LN2 inventory YAML.

## Sequence

1. Read [prompt_en.md](prompt_en.md) for the task framing.
2. Follow [runbook_en.md](runbook_en.md) in order.
3. Keep `migrate/output/migration_checklist.md` updated from the checklist template.
4. Read shared references for structural fields, schema context, validation rules, and confirmation policy when needed.
5. Resume from existing schema/checklist/output artifacts when they are already present and still valid.

## Output Contract

- Final YAML path: `migrate/output/ln2_inventory.yaml`
- Top-level keys: `meta`, `inventory`
- Data model: one `inventory[]` item per physical tube
- Whole-file passthrough: use `fs_copy` when source YAML is already valid and the approved mapping is identity
