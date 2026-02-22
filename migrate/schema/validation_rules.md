# LN2 Import Validation Rules

The generated file **must** be `output/ln2_inventory.yaml`.

## Required structure

- Top-level keys must be exactly: `meta`, `inventory`.
- Data model is tube-level: each `inventory[]` item is one physical tube.

## Required record fields

- `id`: unique positive integer.
- `box`: positive integer within configured box layout.
- `frozen_at`: date in `YYYY-MM-DD`.
- To pass strict import mode in this app, include non-empty `cell_line` for every record. If source value is unknown, use `"Unknown"`.

## Position rules

- `position` may be integer or null.
- If `position` is null, record must include valid takeout history in `thaw_events`.
- Active records must not conflict on `(box, position)`. Any active-position conflict is a blocking failure.
- If one source row contains multiple positions (for example `1,2,3`), split it into multiple tube-level records (one inventory item per position).

## Metadata rules

- `meta.custom_fields` is optional.
- If present, each item should be a structured object with `key` (identifier-style) and `type` (for example `str`, `int`, `float`, `date`).
- Optional keys such as `label`, `required`, and `default` are allowed.

## Date rules

- `frozen_at` and thaw-event dates must be `YYYY-MM-DD`.
- If a source date is an Excel serial number (for example `45072`), convert it to `YYYY-MM-DD` before writing output.
- Future dates are invalid.

## Ambiguity rules

- Do not invent missing records, dates, positions, or metadata.
- If source material is ambiguous for required fields, ask clarifying questions before finalizing output.

## Recommended workflow for external agent

1. Read `manifest.json` and parse files listed in `source_files`.
2. Follow `templates/runbook_en.md` in order.
3. Run checks from `templates/acceptance_checklist_en.md`.
4. Produce final YAML at `output/ln2_inventory.yaml` only after blocking checks pass.

## Example outputs

- Minimal reference: `examples/valid_inventory_min.yaml`
- Full reference: `examples/valid_inventory_full.yaml`
