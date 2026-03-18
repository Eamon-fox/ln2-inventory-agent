# Current Inventory Repair Notes

This skill is for the live managed dataset, not `migrate/output/ln2_inventory.yaml`.

## Focus Areas

- Broken or inconsistent field definitions
- Record keys that no longer match effective schema
- Box layout or structural metadata mismatches
- Cases where the user wants to inspect the YAML-level source of a current-data problem

## Guardrails

- Do not assume migration-specific context is available.
- Read shared schema context before deciding which fields are structural or custom.
- Keep repair tool calls visible to the user.
