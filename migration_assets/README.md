# Migration Static Assets

This folder stores **immutable guidance assets** for migration workflows.

Why this folder exists:
- Keep static guidance out of the writable `migrate/` runtime sandbox.
- Reduce accidental edits during AI-assisted migration retries.
- Provide one stable source of truth for prompt/runbook/schema references.

Contents:
- `templates/*`: migration instructions, runbook, acceptance checklist.
- `schema/*`: schema/rule references used by migration guidance.
- `examples/*`: reference output examples.
- Validation runs through the `validate_migration_output` tool (which writes `migrate/output/validation_report.json`).

Runtime writable workspace stays in:
- `migrate/inputs/*`
- `migrate/output/*`

The app's import journey prompt should always reference:
- `migration_assets/templates/prompt_en.md`
- `migration_assets/schema/validation_rules.md`

Runtime note:
- At the start of each migration session, the app resets `migrate/output/migration_checklist.md`
  from `migration_assets/templates/acceptance_checklist_en.md` for live progress tracking.
