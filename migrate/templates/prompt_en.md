# Task: Convert source materials to LN2 inventory YAML

You are given raw source files under `inputs/`.

Authoritative context:
- Treat `manifest.json` as the source of truth.
- Enumerate input files from `manifest.json` -> `source_files`.
- Final output path is exactly `output/ln2_inventory.yaml`.

Hard requirements:
- Keep one inventory item per physical tube (tube-level model).
- Do not invent records, fields, dates, or positions.
- Use `null` only when allowed by `schema/validation_rules.md`.
- Keep active tubes unique on `(box, position)`.
- Ensure every inventory record has non-empty `cell_line`; use `"Unknown"` only when the source truly cannot provide it.
- If required fields are ambiguous, ask clarifying questions before final output.
- If clarification is unavailable, write blockers in `output/conversion_report.md` and avoid fake completion.

Execution discipline:
1. Follow `templates/runbook_en.md` step by step.
2. Complete all blocking checks in `templates/acceptance_checklist_en.md`.
3. Deliver final YAML only after all blocking checks pass.
