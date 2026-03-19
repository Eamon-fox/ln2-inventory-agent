# LN2 Import Acceptance Checklist (English)

Use this checklist before final delivery. Any failed blocking check means output is not ready.
At migration start, this template is copied to `migrate/output/migration_checklist.md`; update that copied file as live progress during the session.

## Blocking checks

- [ ] Agent did NOT read from `inventories/` or any existing managed dataset (unless user explicitly requested comparison).
- [ ] Output file path is exactly `migrate/output/ln2_inventory.yaml`.
- [ ] Run `validate` with path `migrate/output/ln2_inventory.yaml` and confirm `error_count=0` plus `warning_count=0` (do not run `migration_assets/validate.py`).
- [ ] `migrate/output/expected_schema.json` exists and was finalized before record conversion.
- [ ] User explicitly approved the field mapping/schema plan after precheck and before conversion.
- [ ] Top-level keys are exactly `meta` and `inventory`.
- [ ] `meta.box_layout.rows` and `meta.box_layout.cols` are positive integers.
- [ ] If `meta.box_layout.box_tags` is present, each key maps to a declared box number and each tag is a non-empty single-line string (<= 80 chars).
- [ ] Every inventory record has required fields: `id`, `box`, `frozen_at`.
- [ ] When `cell_line` is required, every inventory record has non-empty `cell_line` (`"Unknown"` is acceptable only when source value is truly unavailable).
- [ ] For any field with `options` defined, non-empty values belong to the declared options list.
- [ ] `id` values are unique positive integers.
- [ ] Active tubes do not conflict on `(box, position)`.
- [ ] `frozen_at` and takeout-event dates use `YYYY-MM-DD` and are not future dates.
- [ ] `position` is integer or `null`; `null` is only used when rules allow it.
- [ ] `meta.custom_fields`, if present, uses structured objects with `key` + `type` (optional `label` / `required` / `default`).
- [ ] `meta.custom_fields` keys do not collide with structural keys (`id`, `box`, `position`, `frozen_at`, `thaw_events`).
- [ ] No invented records or fabricated values were introduced.
- [ ] No unresolved ambiguity remains for required fields.

## Recommended report content (optional)

- Mapping summary from source fields to output fields.
- Assumptions made during conversion.
- Any non-blocking caveats for downstream review.
