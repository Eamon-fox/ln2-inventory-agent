# Task: Convert source materials to LN2 inventory YAML

You are given raw source files under `migrate/inputs/`.

Authoritative context:
- Treat files currently present in `migrate/inputs/` as the source of truth.
- Final output path is exactly `migrate/output/ln2_inventory.yaml`.

Hard requirements:
- Keep one inventory item per physical tube (tube-level model).
- Do not invent records, fields, dates, or positions.
- Use `null` only when allowed by `migration_assets/schema/validation_rules.md`.
- Keep active tubes unique on `(box, position)`.
- When `cell_line` is configured as required, ensure every inventory record has non-empty `cell_line`; use `"Unknown"` only when the source truly cannot provide it.
- For any field with `options` defined (including `cell_line`), ensure non-empty values are in the declared options list.
- Keep `meta.custom_fields` strictly non-structural (`id`, `box`, `position`, `frozen_at`, `thaw_events` must not appear there). Note: `cell_line` and `note` are default custom fields and belong in `meta.custom_fields`.
- If source data includes per-box labels (rack/shelf/layer), map them to optional `meta.box_layout.box_tags` using box-number keys.
- If required fields are ambiguous, ask clarifying questions before final output.
- If clarification is unavailable, write blockers in `migrate/output/conversion_report.md` and avoid fake completion.
- Before row-level conversion, propose the session schema and field mapping plan, get explicit user approval, then lock it in `migrate/output/expected_schema.json`.
- If user requests mapping changes, update the proposal and re-confirm before conversion.

Execution discipline:
1. Follow `migration_assets/templates/runbook_en.md` step by step.
2. Complete all blocking checks in `migration_assets/templates/acceptance_checklist_en.md`.
3. Keep `migrate/output/migration_checklist.md` updated as live progress (check items as you complete them).
4. After precheck, ask user to confirm the field mapping/schema plan before locking `migrate/output/expected_schema.json`.
5. Deliver final YAML only after all blocking checks pass.
