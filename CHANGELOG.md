# Changelog

## 1.3.5 - 2026-03-19

### Changed
- Bumped application version metadata from 1.3.4 to 1.3.5.
- Rebuilt the Windows installer and synchronized release manifest fields for the current repository snapshot.

## 1.3.4 - 2026-03-18

### Added
- Batch add API (`tool_batch_add_entries`) for single-cycle bulk execution.
- Activity indicator with pulsing dot, elapsed timer, and tool name display during agent processing.
- Markdown rendering in agent question dialogs.
- Context compressor module: sliding-window + summarization replaces hard truncation for bulk operations.
- Backup file validation before rollback with alternative backup suggestions on failure.
- Unified `PlanItem` TypedDict and `PlanItemPayload` as single source of truth for plan item structure.
- Shared validation primitives module (`lib/validation_primitives.py`) consolidating record validation logic.
- Single source of truth for version constants (`app_gui/version.py`).

### Changed
- "Clear" button in AI panel renamed to "New Chat", now resets both UI display and agent context with confirmation dialog.
- Global custom-field schema remains the only supported model; datasets using legacy `meta.box_fields` are now rejected.
- Tool registry now derives `WRITE_TOOLS`, `MIGRATION_TOOL_NAMES`, and `VALID_PLAN_ACTIONS` from `TOOL_CONTRACTS` metadata flags.
- Dataset path normalization and combo builder extracted to shared helpers in `lib/inventory_paths.py`.
- Batch plan execution optimized from 10+ seconds to ~1 second for 100+ operations.

### Fixed
- Context truncation too aggressive during bulk add operations, causing LLM to lose earlier tool results.
- User interruption causing inconsistent conversation history (orphaned tool-call/result groups).
- Rollback failures on certain backup points due to missing pre-validation.
- Conflict detection during migration misleadingly reporting batch-internal conflicts as existing-inventory conflicts.
- Baseline `TestColorPalette` test assertions updated to match current theme implementation.
- PyInstaller spec now reads version from `app_gui/version.py` with type-annotation-aware regex.

## 1.3.3 - 2026-03-05

### Added
- Added segmented toggles for operation mode and overview view mode.
- Added overview row context menu actions with shared cell logic and AI slot-context handoff.

### Changed
- Streamlined overview and home toolbar layout by removing redundant labels/buttons.
- Refactored Manage Boxes into a single-page dialog flow.
- Simplified overview advanced filters and improved operation confirm/status visibility.
- Consolidated migration UX in AI panel and enforced migration-mode panel behavior.
- Improved tooltip wrapping/spacing and adjusted overview cell visual tone mapping.

### Fixed
- Fixed plan card action bar placement and styling regressions.
- Fixed missing i18n strings for AI migration exit flow.
- Fixed regression tests for bash availability and updated UI expectation coverage.

## 1.3.2 - 2026-03-04
- Settings custom-field edits now include service-layer backup and audit persistence.
