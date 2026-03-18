# Validation Contract

Use validation rules as the final authority over generated or repaired YAML.

## Core Rules

- Top-level keys must be exactly `meta` and `inventory`.
- The data model is tube-level: one `inventory[]` item per physical tube.
- Active records must not conflict on `(box, position)`.
- `frozen_at` and event dates must use `YYYY-MM-DD` and must not be future dates.
- Required fields must be present and non-empty when policy says they are required.
- Declared options constrain non-empty values for their fields.
- `meta.custom_fields` must not collide with structural fields.

## Workflow Rules

- Migration outputs must pass `validate_migration_output` before import.
- Repair work should use validation-aware reasoning before any final write.
- Validation results outrank free-form prompt assumptions.
