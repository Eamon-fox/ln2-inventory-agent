# LN2 Import Runbook (English)

Follow every phase in order. Do not skip validation.

## Phase 1 - Read task context

1. List and inspect all source files currently present in `migrate/inputs/`.
2. Confirm required output path: `migrate/output/ln2_inventory.yaml`.
3. Track execution progress in `migrate/output/migration_checklist.md` throughout this run.
4. Scope reminder: work ONLY within `migrate/inputs/`, `migrate/normalized/`, and `migrate/output/`. Do not read from `inventories/` unless the user explicitly requests a comparison with an existing dataset.

## Phase 2 - Inspect source structure

1. Inspect each listed source file.
2. Identify how required fields map to YAML fields (`id`, `box`, `position`, `frozen_at`).
3. Run quick prechecks before transformation:
   - required-field coverage (`box`, `position`, `frozen_at`; also `cell_line` when marked required)
   - for any field with `options` in `meta.custom_fields` (including `cell_line`), values match the declared options
   - duplicate active locations on `(box, position)`
   - date parseability and future-date risks
   - custom-field metadata shape (`meta.custom_fields` entries use `key` + `type`)
   - custom fields do not collide with structural keys (`id`, `box`, `position`, `frozen_at`, `thaw_events`)
4. Record unresolved ambiguities before transformation.

## Phase 3 - Design field mapping

1. Propose recommended `meta` profile:
   - `box_layout.rows`, `box_layout.cols`
   - `box_layout.indexing` (`numeric` or `alphanumeric`)
   - `box_layout.box_count` or `box_numbers`
   - optional `box_layout.box_tags` when source provides per-box labels (rack/shelf/layer names)
2. Propose field policy:
   - fixed required fields (`id`, `box`, `position`, `frozen_at`); `cell_line` and other custom fields are required only when their field definition says so
   - optional/custom fields that can be agreed with user
3. Present the mapping/schema proposal to user and request explicit approval.
4. If user requests changes, revise the proposal and confirm again before conversion.
5. Write and lock the approved plan to `migrate/output/expected_schema.json` before record conversion.
6. Note assumptions explicitly.

## Phase 4 - Transform data

1. Convert source records into tube-level `inventory[]` records.
2. Normalize dates to `YYYY-MM-DD`.
3. Keep source traceability for uncertain conversions.

## Phase 5 - Validate draft output

1. Run `validate` with `path` set to `migrate/output/ln2_inventory.yaml` (tool call only; do not run `migration_assets/validate.py`).
2. Run all checks in `agent_skills/migration/assets/acceptance_checklist_en.md`.
3. Review the returned validation report and fix blockers. For migration readiness, both errors and warnings are blocking.
4. If validation reports blockers, do not deliver final output.
5. If a blocker cannot be resolved from source data, stop and request clarification.

## Phase 6 - Finalize delivery

1. Write final YAML to `migrate/output/ln2_inventory.yaml`.
2. Keep the locked `migrate/output/expected_schema.json` with your final mapping plan.
3. Record the latest validation status in `migrate/output/migration_checklist.md`.
4. Optionally write `migrate/output/conversion_report.md` with assumptions and unresolved blockers.
