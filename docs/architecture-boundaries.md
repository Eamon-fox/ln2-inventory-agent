# Architecture Boundaries

This document defines practical dependency rules for the desktop app.

## Layering

1. `app_gui/ui/*`
2. `app_gui/main.py` and `app_gui/main_window_flows.py`
3. `app_gui/application/*`
4. `lib/domain/*`
5. `lib/*` infrastructure modules

Direction is top-down only.

## Rules

- `lib/domain/*` must stay framework-free:
  - no `PySide6` imports
  - no GUI widget/state dependencies
- `app_gui/ui/*` should not call write-validation infra directly:
  - do not import `lib.tool_api_write*`
  - do not import `lib.tool_api_write_validation`
- write-side workflows should be coordinated by application use cases.

## Current use-case entrypoints

- `DatasetUseCase.switch_dataset` (`app_gui/application/use_cases.py`)
  - validates and normalizes target path
  - persists active dataset in config
  - emits `DatasetSwitched` event through `EventBus`
  - `MainWindow` consumes `DatasetSwitched` to refresh UI hooks and emit status notice
- `MigrationModeUseCase.set_mode`
  - publishes `MigrationModeChanged`
  - UI applies lock/badge/banner via event handler
- `PlanExecutionUseCase.report_operation_completed`
  - publishes `OperationExecuted`
  - main window refresh flow consumes the event
- `PlanRunUseCase.execute`
  - executes staged plan items via a single application entrypoint
  - normalizes tool-run rows for UI/result rendering

## OperationsPanel boundary (Phase 4)

Contract tests define two explicit boundary lists for `OperationsPanel`:

- `OPERATIONS_PANEL_PUBLIC_API`
  - stable entrypoints used by `main.py`, main flows, and cross-panel wiring
  - additions/removals are architecture-level changes, not local refactors
- `OPERATIONS_PANEL_ALIAS_ALLOWLIST`
  - class-level `_ops_*` bridge aliases kept for compatibility and tests
  - new aliases are forbidden unless explicitly reviewed and allowlisted

The contract suite enforces both:

- every `OPERATIONS_PANEL_PUBLIC_API` symbol must be an explicit `OperationsPanel` method
- every class-level `_ops_*` bridge alias must be in `OPERATIONS_PANEL_ALIAS_ALLOWLIST`

## OperationsPanel cleanup (Phase 5)

Private bridge aliases that were removed from `OperationsPanel` must stay removed.
Contract tests now guard this by scanning integration tests for direct calls such as:

- `panel._lookup_record(...)`
- `panel._refresh_takeout_record_context(...)`
- `panel._refresh_move_record_context(...)`
- `panel._rebuild_custom_add_fields(...)`
- `panel._handle_response(...)`
- `panel._get_selected_plan_rows(...)`
- `panel._enable_undo(...)`
- `panel._build_print_grid_state(...)`

If these names are needed internally, call helper-module functions directly instead of re-adding class-level aliases.

Alias bridge budget is capped by contract test:

- `_ops_*` class-level bridge aliases on `OperationsPanel` must stay at `0`

## Event model

Domain events are defined under `lib/domain/events.py`.
Application event dispatch uses `app_gui/application/event_bus.py`.

Event handlers must be idempotent and non-blocking where possible.
