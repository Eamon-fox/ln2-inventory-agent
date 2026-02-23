# Test Index

Use this index as the primary navigation layer while test files remain flat.

## Agent

- test_agent_tool_runner.py - Agent tool dispatch, validation, schema exposure, and handler behavior.
- test_agent_missing.py - Agent edge cases and regression guards for missing data paths.
- test_react_agent.py - ReAct loop behavior, tool-calling integration, retry and finalization logic.
- test_llm_client.py - LLM client payload shaping and response normalization.
- test_terminal_tool.py - Terminal execution wrapper behavior and error handling.
- test_question_tool.py - Question tool flow and interaction formatting for agent workflows.

## GUI

- test_gui_panels.py - Main GUI panel behavior including overview, operations, and table state.
- test_gui_panels_new.py - Additional panel behavior and recent GUI interaction cases.
- test_gui_config.py - GUI config persistence, defaults, and migration behavior.
- test_gui_tool_bridge.py - GUI-to-tool bridge invocation and payload mapping.
- test_main_window_flows.py - End-to-end main window user flows.
- test_main.py - Application entrypoint and launch behavior.
- test_audit_dialog.py - Audit dialog rendering and interaction logic.
- test_overview_box_tags.py - Overview box tag display and update behavior.
- test_app_gui_missing2.py - GUI regressions around partial or missing data conditions.
- test_error_localizer.py - Error localization and message mapping behavior.
- test_event_compactor.py - Event compaction behavior used by GUI timelines.
- test_import_journey.py - Unified import flow behavior and failure handling.
- test_migration_workspace.py - Fixed migration workspace staging and path handling.

## Lib and Core

- test_tool_api.py - Primary Tool API behavior across read and write workflows.
- test_tool_api_extended2.py - Extended Tool API scenarios and edge cases.
- test_tool_api_invariants.py - Invariant checks for Tool API consistency.
- test_tool_api_cell_line_migration.py - Cell-line migration behavior via Tool API.
- test_yaml_ops.py - YAML load, write, audit, and backup behavior.
- test_config.py - Core config loading and overrides.
- test_validate.py - Validation entrypoint behavior.
- test_validators.py - Validator unit coverage for field and model checks.
- test_validators_conflict.py - Conflict detection behavior in validators.
- test_custom_fields.py - Custom-field schema, persistence, and query behavior.
- test_takeout_parser.py - Takeout parser behavior and normalization rules.
- test_inventory_paths.py - Inventory path resolution and file location behavior.
- test_position_fmt.py - Position conversion and formatting helpers.
- test_tool_status_formatter.py - Tool status formatting and output messaging.
- test_lib_missing.py - Library regression tests for missing or invalid input states.

## Plan and Staging

- test_plan_executor.py - Plan execution engine behavior and operation orchestration.
- test_plan_gate.py - Plan gate validation and blocking rules.
- test_plan_model.py - Plan model normalization and schema behavior.
- test_plan_outcome.py - Plan outcome shaping and result summaries.
- test_plan_preview.py - Preview generation for staged plan operations.
- test_plan_store.py - Plan store persistence and lifecycle operations.

## Import and Migrate

- test_import_acceptance.py - Acceptance-level import scenarios.
- test_migrate_cell_line_policy.py - Migration policy checks for cell-line constraints.

## Contracts and Hygiene

- test_tool_contracts_single_source.py - Ensures canonical tool contract source is used.
- test_i18n_hygiene.py - Translation key hygiene and coverage checks.

## Update Rule

When adding a new test file, add one line in the correct section above in the same PR.
