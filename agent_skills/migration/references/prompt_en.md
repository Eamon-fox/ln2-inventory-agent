# Task: Convert source materials to LN2 inventory YAML

You are given staged source files under `migrate/inputs/`.

Authoritative context:

- Treat files currently present in `migrate/inputs/` as the source of truth.
- Final output path is exactly `migrate/output/ln2_inventory.yaml`.

Hard requirements:

- Keep one inventory item per physical tube.
- Do not invent records, fields, dates, or positions.
- Use `null` only when allowed by `agent_skills/shared/references/validation_contract.md`.
- Keep active tubes unique on `(box, position)`.
- When `cell_line` is configured as required, ensure every inventory record has non-empty `cell_line`; use `"Unknown"` only when the source truly cannot provide it.
- For any field with `options` defined, ensure non-empty values are in the declared options list.
- Keep `meta.custom_fields` strictly non-structural; read `agent_skills/shared/references/structural_fields.md` when needed.
- If source data includes per-box labels, map them to optional `meta.box_layout.box_tags`.
- If required fields are ambiguous, ask clarifying questions before final output.
- Before row-level conversion, propose the session schema and field mapping plan, get explicit user approval, then lock it in `migrate/output/expected_schema.json`.

Execution discipline:

1. Follow `agent_skills/migration/references/runbook_en.md` step by step.
2. Complete all blocking checks in `agent_skills/migration/assets/acceptance_checklist_en.md`.
3. Keep `migrate/output/migration_checklist.md` updated as live progress.
4. Use repo-relative paths consistently across file tools and shell commands; when you mean the migration workspace, spell paths as `migrate/...`.
5. After precheck, ask user to confirm the field mapping/schema plan before locking `migrate/output/expected_schema.json`.
6. Deliver final YAML only after blocking checks pass.
