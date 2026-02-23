# LN2 Import Acceptance Checklist (English)

Use this checklist before final delivery. Any failed blocking check means output is not ready.
At migration start, this template is copied to `migrate/output/migration_checklist.md`; update that copied file as live progress during the session.

## Blocking checks

- [ ] Output file path is exactly `migrate/output/ln2_inventory.yaml`.
- [ ] Run `python migration_assets/validate.py --input migrate/output/ln2_inventory.yaml` and confirm exit code is 0.
- [ ] `migrate/output/expected_schema.json` exists and was finalized before record conversion.
- [ ] User explicitly approved the field mapping/schema plan after precheck and before conversion.
- [ ] Top-level keys are exactly `meta` and `inventory`.
- [ ] `meta.box_layout.rows` and `meta.box_layout.cols` are positive integers.
- [ ] If `meta.box_layout.box_tags` is present, each key maps to a declared box number and each tag is a non-empty single-line string (<= 80 chars).
- [ ] Every inventory record has required fields: `id`, `box`, `frozen_at`.
- [ ] Every inventory record has non-empty `cell_line` (`"Unknown"` is acceptable only when source value is truly unavailable).
- [ ] Every non-empty `cell_line` belongs to `meta.cell_line_options` (or default options when this list is absent).
- [ ] `id` values are unique positive integers.
- [ ] Active tubes do not conflict on `(box, position)`.
- [ ] `frozen_at` and thaw-event dates use `YYYY-MM-DD` and are not future dates.
- [ ] `position` is integer or `null`; `null` is only used when rules allow it.
- [ ] `meta.custom_fields`, if present, uses structured objects with `key` + `type` (optional `label` / `required` / `default`).
- [ ] `meta.custom_fields` keys do not collide with structural keys (`id`, `box`, `position`, `frozen_at`, `thaw_events`, `cell_line`, `note`).
- [ ] No invented records or fabricated values were introduced.
- [ ] No unresolved ambiguity remains for required fields.

## Recommended report content (optional)

- Mapping summary from source fields to output fields.
- Assumptions made during conversion.
- Any non-blocking caveats for downstream review.
