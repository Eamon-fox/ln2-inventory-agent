# LN2 Import Validation Rules

The generated file **must** be `migrate/output/ln2_inventory.yaml`.

## Required structure

- Top-level keys must be exactly: `meta`, `inventory`.
- Data model is tube-level: each `inventory[]` item is one physical tube.

## Required record fields

- `id`: unique positive integer.
- `box`: positive integer within configured box layout.
- `stored_at`: date in `YYYY-MM-DD`. Legacy input alias `frozen_at` may be accepted on read, but canonical migration output should use `stored_at`.
- Do not assume any built-in business field beyond the structural inventory fields. A field like `cell_line` is only required when it is explicitly declared as required by the effective schema.
- For any field with `options` defined (in `meta.custom_fields` or legacy `meta.cell_line_options`), non-empty values must be in that options list.

## Position rules

- `position` may be integer or null.
- If `position` is null, record must include valid takeout history in `storage_events`.
- Active records must not conflict on `(box, position)`. Any active-position conflict is a blocking failure.
- If one source row contains multiple positions (for example `1,2,3`), split it into multiple tube-level records (one inventory item per position).

## Metadata rules

- `meta.custom_fields` is optional.
- If present, each item should be a structured object with `key` (identifier-style) and `type` (for example `str`, `int`, `float`, `date`).
- `meta.custom_fields` must not reuse structural keys (`id`, `box`, `position`, `stored_at`, `storage_events`). Note: `cell_line` and `note` are default custom fields and may appear in `meta.custom_fields`.
- Optional keys such as `label`, `required`, and `default` are allowed.
- `meta.box_layout.box_tags` is optional. If provided, each key must map to a declared box number and each value must be a non-empty single-line tag (<= 80 chars).

## Date rules

- `stored_at` and event dates must be `YYYY-MM-DD`.
- If a source date is an Excel serial number (for example `45072`), convert it to `YYYY-MM-DD` before writing output.
- Future dates are invalid.

## Ambiguity rules

- Do not invent missing records, dates, positions, or metadata.
- If source material is ambiguous for required fields, ask clarifying questions before finalizing output.

## Recommended workflow

1. Read source files staged in `migrate/inputs/`.
2. Follow `agent_skills/migration/references/runbook_en.md` in order.
3. Run checks from `agent_skills/migration/assets/acceptance_checklist_en.md`.
4. Produce final YAML at `migrate/output/ln2_inventory.yaml` only after blocking checks pass.

## Example outputs

- Minimal reference: `migration_assets/examples/valid_inventory_min.yaml`
- Full reference: `migration_assets/examples/valid_inventory_full.yaml`
