# LN2 Import Runbook (English)

Follow every phase in order. Do not skip validation.

## Phase 1 - Read task context

1. Open `manifest.json`.
2. Build the exact source file list from `source_files`.
3. Confirm required output path: `output/ln2_inventory.yaml`.

## Phase 2 - Inspect source structure

1. Inspect each listed source file.
2. Identify how required fields map to YAML fields (`id`, `box`, `position`, `frozen_at`).
3. Run quick prechecks before transformation:
   - required-field coverage (`box`, `position`, `frozen_at`, `cell_line`)
   - duplicate active locations on `(box, position)`
   - date parseability and future-date risks
   - custom-field metadata shape (`meta.custom_fields` entries use `key` + `type`)
4. Record unresolved ambiguities before transformation.

## Phase 3 - Design field mapping

1. Define deterministic mapping rules for required fields.
2. Define mapping for optional/custom fields without inventing values.
3. Note assumptions explicitly.

## Phase 4 - Transform data

1. Convert source records into tube-level `inventory[]` records.
2. Normalize dates to `YYYY-MM-DD`.
3. Keep source traceability for uncertain conversions.

## Phase 5 - Validate draft output

1. Run all checks in `templates/acceptance_checklist_en.md`.
2. Fix blocking issues before final delivery.
3. If a blocker cannot be resolved from source data, stop and request clarification.

## Phase 6 - Finalize delivery

1. Write final YAML to `output/ln2_inventory.yaml`.
2. Optionally write `output/conversion_report.md` with assumptions and unresolved blockers.
