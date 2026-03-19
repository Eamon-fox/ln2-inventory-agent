---
name: migration
description: Convert staged legacy source files in `migrate/inputs/` into LN2 inventory YAML at `migrate/output/ln2_inventory.yaml`, validate the result, and import it as a new managed dataset. Use when the user is running migration onboarding or asks to transform external source materials into LN2 inventory format.
---

# Migration

Follow this skill when handling staged migration inputs.

## Core Workflow

1. Inspect source files staged in `migrate/inputs/`.
2. Keep live progress in `migrate/output/migration_checklist.md`.
3. Propose the field mapping and schema plan before conversion.
4. Ask for explicit approval before locking `migrate/output/expected_schema.json`.
5. Write final output to `migrate/output/ln2_inventory.yaml`.
6. Run `validate` with `path` set to `migrate/output/ln2_inventory.yaml` before any import.
7. Import only after collecting `target_dataset_name` and explicit `CONFIRM_IMPORT`.

## Read Next As Needed

- Workflow overview: [references/workflow.md](references/workflow.md)
- Prompt framing: [references/prompt_en.md](references/prompt_en.md)
- Detailed runbook: [references/runbook_en.md](references/runbook_en.md)
- Shared structural fields: [../shared/references/structural_fields.md](../shared/references/structural_fields.md)
- Shared schema context: [../shared/references/schema_context.md](../shared/references/schema_context.md)
- Shared validation contract: [../shared/references/validation_contract.md](../shared/references/validation_contract.md)
- Shared audit and confirmation policy: [../shared/references/audit_policy.md](../shared/references/audit_policy.md)

## Non-Negotiables

- Do not invent records, dates, positions, or metadata.
- Do not bypass `validate(path="migrate/output/ln2_inventory.yaml")`.
- Do not import before explicit human confirmation.
