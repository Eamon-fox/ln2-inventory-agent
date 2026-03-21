# Task: Convert source materials to LN2 inventory YAML

You are given raw source files under `migrate/inputs/`.

Authoritative context:
- Treat files currently present in `migrate/inputs/` as the source of truth.
- Final output path is exactly `migrate/output/ln2_inventory.yaml`.

Scope boundary:
- Your working directories are ONLY `migrate/inputs/`, `migrate/normalized/`, and `migrate/output/`.
- Do NOT read from `inventories/` or any existing managed dataset during normal migration flow.
- Reading existing inventory is allowed ONLY when the user explicitly asks to "compare with existing dataset" or similar.
- Migration creates a NEW managed dataset. It never modifies, merges into, or deduplicates against an existing one.

Hard requirements:
- Keep one inventory item per physical tube (tube-level model).
- Do not invent records, fields, dates, or positions.
- Use `null` only when allowed by `agent_skills/shared/references/validation_contract.md`.
- Keep active tubes unique on `(box, position)`.
- Do not assume any built-in business field beyond the structural inventory fields. Treat fields like `cell_line` as ordinary custom fields that only exist when the approved schema declares them.
- For any field with `options` defined (including `cell_line`), ensure non-empty values are in the declared options list.
- Keep `meta.custom_fields` strictly non-structural (`id`, `box`, `position`, `stored_at`, `storage_events` must not appear there). Legacy input aliases like `frozen_at`/`thaw_events` may be accepted on read, but final migration output should use canonical structural names.
- If source data includes per-box labels (rack/shelf/layer), map them to optional `meta.box_layout.box_tags` using box-number keys.
- If required fields are ambiguous, ask clarifying questions before final output.
- If clarification is unavailable, write blockers in `migrate/output/conversion_report.md` and avoid fake completion.
- Before row-level conversion, propose the session schema and field mapping plan, get explicit user approval, then lock it in `migrate/output/expected_schema.json`.
- If user requests mapping changes, update the proposal and re-confirm before conversion.
- If the source file is already a valid LN2 YAML and the approved mapping is identity, materialize the final output with `fs_copy` instead of re-writing the whole file via `fs_write`.

Execution discipline:
1. Follow `agent_skills/migration/references/runbook_en.md` step by step.
2. Complete all blocking checks in `agent_skills/migration/assets/acceptance_checklist_en.md`.
3. Keep `migrate/output/migration_checklist.md` updated as live progress (check items as you complete them).
4. Prefer the inline `reference_documents` and `shared_reference_documents` returned by `use_skill`; only call `fs_read` for additional repo-relative files you still need.
5. If `migrate/output/expected_schema.json`, `migrate/output/migration_checklist.md`, or `migrate/output/ln2_inventory.yaml` already exist, inspect them first and resume from the highest valid completed stage instead of replaying the workflow from scratch.
6. After precheck, ask user to confirm the field mapping/schema plan before locking `migrate/output/expected_schema.json`.
7. Deliver final YAML only after all blocking checks pass.
