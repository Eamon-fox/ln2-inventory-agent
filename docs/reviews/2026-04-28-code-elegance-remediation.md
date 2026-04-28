# 2026-04-28 Code Elegance Review / Remediation

## Task Ownership
- Primary modules: `inventory_core`, `agent_runtime`, `gui_application`, `gui_presentation`.
- Shared chokepoints: `lib/tool_registry.py` capability metadata consumers, staged plan state consumed across agent/GUI.

## Contract Tightening Principles
- Tighten: truth-source ownership for edit rules and plan validation state.
- Keep loose: internal helper names, batch implementation details, test fixture setup.
- Hard contract decision: no machine-readable contract block change is required. The remediation does not add a new stable cross-module execution API, dependency direction, or public Tool API surface.
- Soft documentation decision: module docs should make clear that staged plan validation state is carried by `PlanStore` helpers, not by ad hoc `_validation_*` dict keys.

## Findings

### R1. Bulk capability metadata can drift from execution truth
- Severity: P2
- Modules: `inventory_core`, `gui_application`
- Shared chokepoint: yes, `lib/tool_registry.py` is the source for tool capability metadata.
- Paths: `lib/bulk_operations.py`, `lib/tool_registry.py`, `app_gui/plan_executor.py`
- Initial issue: `BulkOperationRequest` / `BulkOperationResult` advertised an execution contract but executor only consumed capability metadata.
- Target: Make `lib.bulk_operations` explicit metadata derived from registry-backed descriptors, not a second execution contract.
- Contract docs: no hard contract change required; this narrows implementation to the existing registry truth source.
- Status: completed
- Change record: `lib.bulk_operations` now exposes registry-derived diagnostic capability metadata only; unused execution request/result contracts were removed, and write batch capabilities are checked against `lib.tool_registry` descriptors.

### R2. Batch edit duplicates single-edit business rules
- Severity: P2
- Modules: `inventory_core`
- Shared chokepoint: no
- Paths: `lib/tool_api_impl/write_edit_entry.py`, `lib/tool_api_impl/write_batch_edit.py`
- Initial issue: single edit and batch edit each implemented normalization, editable-field resolution, option validation, candidate mutation, validation, and audit construction.
- Target: Extract one edit-entry core service and make single and batch write paths call it.
- Contract docs: no hard contract change required; behavior is intended to remain compatible.
- Status: completed
- Change record: extracted `lib/tool_api_impl/edit_entry_core.py`; both `tool_edit_entry` and `tool_batch_edit_entries` call the same normalization, editable-field, value validation, candidate mutation, validation, response, and audit-detail path.

### R3. Validation state is an implicit cross-module dict contract
- Severity: P2
- Modules: `agent_runtime`, `gui_application`, `gui_presentation`
- Shared chokepoint: staged plan state
- Paths: `lib/plan_store.py`, `agent/tool_runner_staging.py`, `app_gui/ui/operations_panel_plan_store.py`, `app_gui/ui/operations_panel_plan_table.py`
- Initial issue: `_validation_status` and related underscore keys were written/read directly across modules.
- Target: Add explicit PlanStore validation-state API and route agent/GUI reads through it.
- Contract docs: no hard contract change required; this makes an existing transient internal payload explicit without changing module dependencies.
- Status: completed
- Change record: `PlanStore` now owns explicit validation-state helpers and stores transient state under `validation`; agent staging and GUI presentation read/write through that API instead of hard-coded underscore fields.

### R4. Plan tests lock private batch-edit wiring
- Severity: P3
- Modules: `gui_application`, `inventory_core`
- Shared chokepoint: no
- Paths: `tests/integration/plan/test_plan_executor.py`
- Initial issue: tests patched `app_gui.plan_executor_actions._write_adapter.batch_edit_entries`, which pins a private implementation path.
- Target: Assert behavior through public plan execution and adapter-level tests, not private executor wiring.
- Contract docs: no hard contract change required.
- Status: completed
- Change record: plan executor tests now assert public behavior through `run_plan` and persisted YAML state instead of patching `app_gui.plan_executor_actions._write_adapter.batch_edit_entries`.

## Final Verification
- Focused tests:
  - `python -m pytest -q tests/unit/test_batch_edit.py tests/integration/plan/test_plan_store.py tests/integration/plan/test_plan_executor.py tests/contract/test_tool_contracts_single_source.py` -> passed, 109 tests + 26 subtests.
  - `python -m pytest -q tests/unit/test_tool_api_write_adapter.py tests/contract/test_architecture_dependencies.py` -> passed, 13 tests + 5 subtests.
  - `python -m pytest -q tests/integration/gui/test_gui_panels_plan_flows.py` -> passed, 50 tests.
- Broader tests:
  - `python -m pytest -q tests/integration/plan` -> passed, 198 tests.
  - `python -m pytest -q tests/contract` -> passed, 86 tests + 115 subtests.
  - `python -m pytest -q tests/unit` -> passed, 455 tests + 7 subtests.
  - `python -m pytest -q tests/integration/gui` -> passed, 566 tests + 56 subtests.
  - `python -m pytest -q tests/integration/inventory` -> passed, 346 tests.
  - Initial `python -m pytest -q tests/integration/agent/test_agent_missing.py tests/integration/agent/test_agent_tool_runner.py` -> 160 passed, 1 unrelated shell boundary failure: `AgentToolRunnerTests.test_shell_rejects_cd_outside_repo_and_keeps_previous_workdir` expected `workdir_out_of_scope`, got `terminal_nonzero_exit`.
- Follow-up shell boundary fix:
  - The known agent shell workdir failure was fixed by preflighting simple `cd` / `chdir` / `Set-Location` chains before terminal execution, while keeping the post-exec cwd scope check as a fallback.
  - `python -m pytest -q tests/integration/agent/test_agent_tool_runner.py -k "shell_rejects_cd_outside_repo or shell_nonzero_exit_still_updates_current_workdir or shell_persists_current_workdir_between_calls or shell_allows_cd_chain_inside_repo"` -> passed, 4 tests.
  - `python -m pytest -q tests/integration/agent/test_agent_tool_runner.py` -> passed, 100 tests.
  - `python -m pytest -q tests/integration/agent/test_agent_missing.py tests/integration/agent/test_agent_tool_runner.py` -> passed, 162 tests.
- Docs backfill status: completed.
