# Test Runbook

This runbook documents common local test commands and troubleshooting steps.

## Prerequisites

1) Install project dependencies:

    python -m pip install -r requirements.txt

2) If needed, install the test runner in your environment:

    python -m pip install pytest

## Common Commands

Run all tests:

    pytest -q

Run one file:

    pytest -q tests/test_tool_api.py

Run focused subsets:

    pytest -q tests/test_agent_tool_runner.py tests/test_react_agent.py
    pytest -q tests/test_plan_model.py tests/test_plan_executor.py
    pytest -q tests/test_gui_panels.py tests/test_main_window_flows.py

Collect-only (discovery check):

    pytest --collect-only -q

Stop on first failure:

    pytest -q -x

## GUI Test Notes

- GUI tests require PySide6.
- If PySide6 is missing, GUI-focused files may fail to import.
- Install it with:

    python -m pip install PySide6

## Troubleshooting

1) Import error for local modules:
   - Run from repository root.
   - Verify current interpreter points to the intended environment.

2) pytest command not found:
   - Use python -m pytest instead of pytest.

3) Flaky local state:
   - Re-run a single failing test first.
   - Then run the smallest relevant file subset before full suite.

## Maintenance

If run commands or required dependencies change, update this file in the same PR.
