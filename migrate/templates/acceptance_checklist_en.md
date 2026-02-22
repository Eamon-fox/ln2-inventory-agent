# LN2 Import Acceptance Checklist (English)

Use this checklist before final delivery. Any failed blocking check means output is not ready.

## Blocking checks

- [ ] Output file path is exactly `output/ln2_inventory.yaml`.
- [ ] Top-level keys are exactly `meta` and `inventory`.
- [ ] `meta.box_layout.rows` and `meta.box_layout.cols` are positive integers.
- [ ] Every inventory record has required fields: `id`, `box`, `frozen_at`.
- [ ] Every inventory record has non-empty `cell_line` (`"Unknown"` is acceptable only when source value is truly unavailable).
- [ ] `id` values are unique positive integers.
- [ ] Active tubes do not conflict on `(box, position)`.
- [ ] `frozen_at` and thaw-event dates use `YYYY-MM-DD` and are not future dates.
- [ ] `position` is integer or `null`; `null` is only used when rules allow it.
- [ ] `meta.custom_fields`, if present, uses structured objects with `key` + `type` (optional `label` / `required` / `default`).
- [ ] No invented records or fabricated values were introduced.
- [ ] No unresolved ambiguity remains for required fields.

## Recommended report content (optional)

- Mapping summary from source fields to output fields.
- Assumptions made during conversion.
- Any non-blocking caveats for downstream review.
