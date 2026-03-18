# LN2 Import Runbook (English)

Follow every phase in order. Do not skip validation.

## Phase 1 - Read task context

1. List and inspect all source files currently present in `migrate/inputs/`.
2. Confirm required output path: `migrate/output/ln2_inventory.yaml`.
3. Track execution progress in `migrate/output/migration_checklist.md` throughout this run.
4. Use repo-relative paths consistently across file tools and shell commands; when you mean the migration workspace, spell paths as `migrate/...`.

## Phase 2 - Inspect source structure

1. Inspect each listed source file.
2. Identify how required fields map to YAML fields (`id`, `box`, `position`, `frozen_at`).
3. Run quick prechecks before transformation:
   - required-field coverage (`box`, `position`, `frozen_at`; also `cell_line` when marked required)
   - option-list conformity for declared fields
   - duplicate active locations on `(box, position)`
   - date parseability and future-date risks
   - custom-field metadata shape
   - structural-key collision checks
4. Record unresolved ambiguities before transformation.

## Phase 3 - Design field mapping

1. Propose recommended `meta` profile and custom-field policy.
2. Present the mapping/schema proposal to user and request explicit approval.
3. If user requests changes, revise the proposal and confirm again before conversion.
4. Write and lock the approved plan to `migrate/output/expected_schema.json` before record conversion.
5. Note assumptions explicitly.

## Phase 4 - Transform data

1. Convert source records into tube-level `inventory[]` records.
2. Normalize dates to `YYYY-MM-DD`.
3. Keep source traceability for uncertain conversions.

## Phase 5 - Validate draft output

1. Run `validate_migration_output` as a tool call.
2. Run all checks in `agent_skills/migration/assets/acceptance_checklist_en.md`.
3. Review `migrate/output/validation_report.json` and fix blockers.
4. If validation fails, do not deliver final output.
5. If a blocker cannot be resolved from source data, stop and request clarification.

## Phase 6 - Finalize delivery

1. Write final YAML to `migrate/output/ln2_inventory.yaml`.
2. Keep the locked `migrate/output/expected_schema.json`.
3. Keep the latest `migrate/output/validation_report.json`.
4. Optionally write `migrate/output/conversion_report.md` with assumptions and unresolved blockers.
