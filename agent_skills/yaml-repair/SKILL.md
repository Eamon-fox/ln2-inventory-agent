---
name: yaml-repair
description: Diagnose and repair current managed inventory YAML and schema-related issues for the active dataset. Use when the user is working on the current inventory, wants bottom-layer YAML inspection, or needs schema-aware repair guidance instead of migration onboarding.
---

# YAML Repair

Follow this skill when the issue is in the current managed inventory rather than staged migration inputs.

## Core Workflow

1. Inspect the active inventory YAML and the evidence around the failure.
2. Decide whether the problem is field/schema, record structure, or data-history integrity.
3. Prefer schema-aware, validation-first repair steps.
4. Keep repair actions explicit and user-visible.

## Read Next As Needed

- Workflow overview: [references/workflow.md](references/workflow.md)
- Current inventory repair notes: [references/current_inventory_repair.md](references/current_inventory_repair.md)
- Shared structural fields: [../shared/references/structural_fields.md](../shared/references/structural_fields.md)
- Shared schema context: [../shared/references/schema_context.md](../shared/references/schema_context.md)
- Shared validation contract: [../shared/references/validation_contract.md](../shared/references/validation_contract.md)
- Shared audit and confirmation policy: [../shared/references/audit_policy.md](../shared/references/audit_policy.md)

## Non-Negotiables

- Treat `inventories/<dataset>/inventory.yaml` as managed data.
- Keep repair steps and tool usage explicit.
- Respect backup and audit expectations before any final write.
