"""Unit tests for the migration-mode write guard decorator (no Qt dependency)."""

import unittest

from app_gui.ui.write_guards import guard_write_action


@guard_write_action
def _write_action(self, *args, **kwargs):
    self.calls.append((args, kwargs))
    return "executed"


class _PanelBase:
    def __init__(self):
        self.calls = []


class _GuardedPanel(_PanelBase):
    def __init__(self, locked):
        super().__init__()
        self._locked = locked
        self.guard_calls = 0

    def _guard_write_action_by_migration_mode(self):
        self.guard_calls += 1
        return self._locked


class _PanelWithoutGuard(_PanelBase):
    pass


class TestGuardWriteAction(unittest.TestCase):
    def test_blocked_guard_skips_body_and_returns_none(self):
        panel = _GuardedPanel(locked=True)
        result = _write_action(panel, 1, key="value")
        self.assertIsNone(result)
        self.assertEqual(panel.calls, [])
        self.assertEqual(panel.guard_calls, 1)

    def test_unblocked_guard_runs_body_and_preserves_return_value(self):
        panel = _GuardedPanel(locked=False)
        result = _write_action(panel, 1, key="value")
        self.assertEqual(result, "executed")
        self.assertEqual(panel.calls, [((1,), {"key": "value"})])
        self.assertEqual(panel.guard_calls, 1)

    def test_missing_guard_method_is_tolerated(self):
        panel = _PanelWithoutGuard()
        result = _write_action(panel)
        self.assertEqual(result, "executed")
        self.assertEqual(panel.calls, [((), {})])

    def test_truthy_non_bool_guard_result_blocks(self):
        panel = _GuardedPanel(locked="locked")
        self.assertIsNone(_write_action(panel))
        self.assertEqual(panel.calls, [])

    def test_wrapper_preserves_function_metadata(self):
        self.assertEqual(_write_action.__name__, "_write_action")


if __name__ == "__main__":
    unittest.main()
