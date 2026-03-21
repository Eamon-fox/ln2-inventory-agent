# Capability Boundaries

Use this reference to reject unsupported requests early instead of guessing and failing late.

## Refuse Early When A Boundary Is Documented

If a request is already known to be unsupported, say so directly. Do not keep probing tools just to discover the same boundary again.

## Current Hard Boundaries

- The Agent cannot add, remove, or rename inventory fields. Direct the user to `Settings > Manage Fields`.
- Inventory mutation tools are stage-only. The Agent cannot silently execute managed writes by itself.
- The local open API must not execute write tools and must not expose agent runtime.
- Managed inventory YAML is not a free-form scratch file. Do not bypass normal tool flows with silent direct edits.
- `manage_boxes` requires human confirmation.
- Switching numeric/alphanumeric positions must use the indexing mode workflow. Do not rewrite stored `inventory[].position` integers into strings like `A1`.
- `rollback` must use an explicit `backup_path` selected from audit timeline entries.
- During migration, operate inside `migrate/` and validate `migrate/output/ln2_inventory.yaml` before import.
- Agent file tools can read the repo broadly, but their write scope is `migrate/` only.

## Tool-Limit Examples

- Per-position metadata differences are not supported in a single `add_entry` call. Split into multiple staged operations when values differ by position.
- If the product has no documented GUI control, tool, or API for the requested action, answer that it is not currently supported.

## What To Say Instead

Prefer short boundary answers in this shape:

- what is not supported
- why it is outside the current product/runtime boundary
- the nearest supported workflow, if one exists

## Examples

- "Add a new field for me" -> not supported by Agent; use `Settings > Manage Fields`.
- "Turn on the local API" -> user action; use `Settings > Local API`.
- "Expose full Agent runtime over the local API" -> unsupported; local API is read-only plus GUI handoff only.
- "Directly patch the active managed inventory with fs_edit" -> not supported path; use normal tool workflows or explicit repair guidance instead.
- "Change positions from 1,2,3 to A1,A2,A3 by editing YAML" -> wrong approach; use `Settings > Data > Manage Boxes > Set position indexing`, which changes indexing mode without rewriting stored integer positions.
