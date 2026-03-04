"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403

class ToolRunnerPlanSinkTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Test that AgentToolRunner stages write operations when plan_store is set."""

    def setUp(self):
        super().setUp()
        from lib.plan_store import PlanStore
        self.store = PlanStore()

    def _make_runner(self, yaml_path=None):
        from agent.tool_runner import AgentToolRunner
        target_yaml = yaml_path or self.fake_yaml_path
        return AgentToolRunner(
            yaml_path=target_yaml,
            plan_store=self.store,
        )

    def test_read_tool_not_intercepted(self):
        runner = self._make_runner()
        runner.run("query_inventory", {"cell": "K562"})
        # Should execute normally (may fail if YAML not found, but not staged)
        self.assertEqual(0, self.store.count())

    def test_add_entry_staged(self):
        runner = self._make_runner()
        result = runner.run("add_entry", {
            "box": 1,
            "positions": [30],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": "K562",
            },
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, self.store.count())
        item = self.store.list_items()[0]
        self.assertEqual("add", item["action"])
        self.assertEqual("ai", item["source"])
        self.assertEqual(1, item["box"])

    def test_takeout_staged(self):
        runner = self._make_runner()
        result = runner.run("takeout", {
            "entries": [
                {
                    "record_id": 5,
                    "from_box": 1,
                    "from_position": 10,
                }
            ],
            "date": "2026-02-10",
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, self.store.count())
        item = self.store.list_items()[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(5, item["record_id"])
        self.assertEqual(10, item["position"])

    def test_without_plan_sink_executes_normally(self):
        from agent.tool_runner import AgentToolRunner
        runner = AgentToolRunner(
            yaml_path=self.fake_yaml_path,
        )
        # Without plan_store, add_entry should attempt execution (may error but not stage)
        result = runner.run("add_entry", {
            "box": 1,
            "positions": [1],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": "K562",
            },
        })
        self.assertFalse(result.get("staged", False))
        self.assertEqual(0, self.store.count())

class _ConfigurableBridge(_FakeOperationsBridge):
    """Bridge that can be configured to fail specific calls."""

    def __init__(self):
        super().__init__()
        self.batch_should_fail = False
        self.record_takeout_fail_ids = set()
        self.record_takeout_calls = []
        self.batch_takeout_calls = []
        self.batch_move_calls = []

    def batch_takeout(self, yaml_path, **payload):
        self.batch_takeout_calls.append(payload)
        if self.batch_should_fail:
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": "Batch validation failed",
                "errors": ["mock error"],
            }
        return super().batch_takeout(yaml_path, **payload)

    def batch_move(self, yaml_path, **payload):
        self.batch_move_calls.append(payload)
        if self.batch_should_fail:
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": "批量 move 参数校验失败",
                "errors": ["mock move error"],
            }
        return super().batch_move(yaml_path, **payload)

    def record_takeout(self, yaml_path, **payload):
        self.record_takeout_calls.append(payload)
        rid = payload.get("record_id")
        if rid in self.record_takeout_fail_ids:
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": f"Record {rid} failed",
            }
        return super().record_takeout(yaml_path, **payload)

class _RollbackAwareBridge(_ConfigurableBridge):
    """Configurable bridge with rollback tracking and per-record backups."""

    def __init__(self):
        super().__init__()
        self.rollback_called = False
        self.rollback_backup_path = None

    def record_takeout(self, yaml_path, **payload):
        response = super().record_takeout(yaml_path, **payload)
        if response.get("ok"):
            rid = payload.get("record_id")
            response = dict(response)
            response["backup_path"] = f"/tmp/bak_{rid}.yaml"
        return response

    def rollback(self, yaml_path, backup_path=None, execution_mode=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        _ = execution_mode
        return {"ok": True, "message": "Rolled back", "backup_path": backup_path}

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PlanDedupRegressionTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Regression: add_plan_items should deduplicate by stable item identity."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    def test_duplicate_item_replaces_existing(self):
        """Staging same (action, record_id, position) should replace, not append."""
        panel = self._new_panel()
        item1 = _make_move_item(record_id=4, position=5, to_position=10)
        item2 = _make_move_item(record_id=4, position=5, to_position=20)  # same key, diff target

        panel.add_plan_items([item1])
        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual(10, panel.plan_items[0]["to_position"])

        panel.add_plan_items([item2])
        self.assertEqual(1, len(panel.plan_items))  # still 1, not 2
        self.assertEqual(20, panel.plan_items[0]["to_position"])  # updated

    def test_different_positions_are_not_deduped(self):
        """Items with different positions should NOT be considered duplicates."""
        panel = self._new_panel()
        item1 = _make_move_item(record_id=4, position=5, to_position=10)
        item2 = _make_move_item(record_id=4, position=6, to_position=11)

        panel.add_plan_items([item1, item2])
        self.assertEqual(2, len(panel.plan_items))

    def test_different_actions_are_not_deduped(self):
        """Same record+position but different action should NOT be deduped."""
        panel = self._new_panel()
        move_item = _make_move_item(record_id=4, position=5, to_position=10)
        takeout_item = _make_takeout_item(record_id=4, position=5)

        panel.add_plan_items([move_item, takeout_item])
        self.assertEqual(2, len(panel.plan_items))

    def test_same_display_position_different_box_are_not_deduped(self):
        """Same position in different boxes should coexist in staged plan."""
        panel = self._new_panel()
        add_box1 = _make_add_item(box=1, position=1, short_name="add-b1-a1")
        add_box2 = _make_add_item(box=2, position=1, short_name="add-b2-a1")

        panel.add_plan_items([add_box1])
        panel.add_plan_items([add_box2])

        self.assertEqual(2, len(panel.plan_items))
        self.assertEqual([1, 2], sorted(int(item.get("box")) for item in panel.plan_items))

    def test_mass_restage_same_items_no_growth(self):
        """Simulates AI re-staging 10 items - plan should not grow past 10."""
        panel = self._new_panel()
        items = [_make_move_item(record_id=i, position=i, to_position=i + 10) for i in range(1, 11)]

        panel.add_plan_items(items)
        self.assertEqual(10, len(panel.plan_items))

        # AI re-stages same 10 items (possibly with tweaked targets)
        items_v2 = [_make_move_item(record_id=i, position=i, to_position=i + 20) for i in range(1, 11)]
        panel.add_plan_items(items_v2)
        self.assertEqual(10, len(panel.plan_items))  # no duplicates

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecutePlanFallbackRegressionTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Regression: batch failure should fallback to individual execution."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: self.fake_yaml_path)
        return panel

    def test_move_batch_fails_falls_back_to_individual(self):
        """When batch_move fails for moves, items are marked blocked (no individual fallback)."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1, to_box=1),
            _make_move_item(record_id=2, position=10, to_position=2, to_box=1),
        ]
        panel.add_plan_items(items)
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # batch_move called once (failed), no individual fallback
        self.assertEqual(1, len(bridge.batch_move_calls))
        self.assertEqual(0, len(bridge.record_takeout_calls))
        # Plan preserved on failure
        self.assertEqual(2, len(panel.plan_items))

    def test_move_individual_fallback_partial_failure_preserves_entire_plan(self):
        """When 1 of 3 individual moves fails, entire plan should be preserved for retry."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {2}  # record_id=2 will fail
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # Entire plan should be preserved (all 3 items)
        self.assertEqual(3, len(panel.plan_items))
        preserved_ids = sorted([item["record_id"] for item in panel.plan_items])
        self.assertEqual([1, 2, 3], preserved_ids)

    def test_takeout_batch_fails_falls_back_to_individual(self):
        """Phase 3: batch failure for takeout marks items blocked (no individual fallback)."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # batch failed, no individual fallback; plan preserved
        self.assertEqual(0, len(bridge.record_takeout_calls))
        self.assertEqual(2, len(panel.plan_items))

    def test_batch_success_no_fallback(self):
        """When batch_move succeeds, no individual fallback should be triggered."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = False  # batch succeeds
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # move batch called once, no individual calls
        self.assertEqual(1, len(bridge.batch_move_calls))
        self.assertEqual(0, len(bridge.record_takeout_calls))
        self.assertEqual(0, len(panel.plan_items))

    def test_phases_continue_after_earlier_failure_preserves_plan(self):
        """Phase 3 should execute even if Phase 2 had failures, but plan is preserved on failure."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {1}  # move for record_id=1 fails
        panel = self._new_panel(bridge)

        # Phase 2 item (move) + Phase 3 item (takeout)
        move = _make_move_item(record_id=1, position=5, to_position=1)
        takeout = _make_takeout_item(record_id=3, position=20)
        panel.add_plan_items([move, takeout])
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # On failure, entire plan is preserved
        self.assertEqual(2, len(panel.plan_items))
        actions = sorted([item["action"] for item in panel.plan_items])
        self.assertEqual(["move", "takeout"], actions)

    def test_all_fail_keeps_all_in_plan(self):
        """If every item fails, all should remain in the plan."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {1, 2}
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(2, len(panel.plan_items))

    def test_dedup_then_execute_end_to_end_with_preserved_plan(self):
        """Full scenario: stage -> execute partial fail (plan preserved) -> use undo + re-stage -> execute succeeds."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {2}
        panel = self._new_panel(bridge)

        # First stage: 3 items
        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items)
        self.assertEqual(3, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # On failure, entire plan is preserved (all 3 items)
        self.assertEqual(3, len(panel.plan_items))
        preserved_ids = sorted([item["record_id"] for item in panel.plan_items])
        self.assertEqual([1, 2, 3], preserved_ids)

        # User can use undo to rollback, then re-execute
        # For this test, just clear and re-add with fix
        panel.clear_plan()
        
        # --- Now execute again ?this time all succeed ---
        bridge.batch_should_fail = False
        bridge.record_takeout_fail_ids.clear()
        bridge.batch_move_calls.clear()
        bridge.batch_takeout_calls.clear()
        bridge.record_takeout_calls.clear()

        items_v2 = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=4),  # different target
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items_v2)
        self.assertEqual(3, len(panel.plan_items))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # All succeeded, plan cleared
        self.assertEqual(0, len(panel.plan_items))

class _UndoBridge(_FakeOperationsBridge):
    """Bridge that supports rollback for undo tests."""

    def __init__(self):
        super().__init__()
        self.rollback_called = False
        self.rollback_backup_path = None

    def rollback(self, yaml_path, backup_path=None, execution_mode=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        _ = execution_mode
        return {"ok": True, "message": "Rolled back", "backup_path": backup_path}

    def batch_takeout(self, yaml_path, **payload):
        result = super().batch_takeout(yaml_path, **payload)
        result["backup_path"] = "/tmp/backup_test.yaml"
        return result

    def batch_move(self, yaml_path, **payload):
        result = super().batch_move(yaml_path, **payload)
        result["backup_path"] = "/tmp/backup_test.yaml"
        return result

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class UndoRestoresPlanRegressionTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Regression: undo should restore executed items back to plan."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: self.fake_yaml_path)

    def test_undo_restores_executed_plan_items(self):
        """After executing plan and undoing, items should return to plan."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(panel.undo_btn.isEnabled())
        self.assertEqual(2, len(panel._last_executed_plan))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertTrue(bridge.rollback_called)
        self.assertEqual(2, len(panel.plan_items))
        self.assertEqual("takeout", panel.plan_items[0]["action"])

    def test_undo_then_stage_rollback_replaces_restored_plan(self):
        """Undo-restored plan items should be replaced when a rollback is staged."""
        from lib.plan_item_factory import build_rollback_plan_item

        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        panel.add_plan_items([_make_takeout_item(record_id=1, position=5)])
        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual("takeout", panel.plan_items[0]["action"])

        panel.add_plan_items(
            [build_rollback_plan_item(backup_path="/tmp/undo_second_backup.bak", source="tests")]
        )
        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual("rollback", panel.plan_items[0]["action"])

    def test_undo_clears_last_executed_plan(self):
        """After undo, _last_executed_plan should be cleared."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [_make_takeout_item(record_id=1, position=5)]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(1, len(panel._last_executed_plan))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertEqual(0, len(panel._last_executed_plan))

    def test_execute_plan_saves_backup_and_executed_items(self):
        """execute_plan should save backup_path and executed items for undo."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [_make_move_item(record_id=1, position=5, to_position=10)]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        backup_path = str(panel._last_operation_backup or "")
        self.assertTrue(backup_path)
        self.assertIn(os.path.join("_fake", "backups"), backup_path)
        self.assertTrue(backup_path.endswith(".bak"))
        self.assertEqual(1, len(panel._last_executed_plan))
        self.assertEqual(1, panel._last_executed_plan[0]["record_id"])

    def test_undo_without_executed_plan_does_not_add_items(self):
        """If no plan was executed (e.g., single operation undo), plan stays empty."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        panel._last_operation_backup = "/tmp/backup.yaml"
        from app_gui.ui import operations_panel_actions as _ops_actions

        _ops_actions._enable_undo(panel, timeout_sec=30)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertTrue(bridge.rollback_called)
        self.assertEqual(0, len(panel.plan_items))

    def test_undo_does_not_rearm_itself(self):
        """Undo response backup should not create another undo window."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        panel._last_operation_backup = "/tmp/backup.yaml"
        from app_gui.ui import operations_panel_actions as _ops_actions

        _ops_actions._enable_undo(panel, timeout_sec=30)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertTrue(bridge.rollback_called)
        self.assertIsNone(panel._last_operation_backup)
        self.assertFalse(panel.undo_btn.isEnabled())

    def test_execute_rollback_plan_does_not_enable_undo(self):
        """Rollback plan execution should not arm undo, avoiding looped rollback/undo cycles."""
        from lib.plan_item_factory import build_rollback_plan_item

        bridge = _UndoBridge()
        panel = self._new_panel(bridge)
        panel.add_plan_items([build_rollback_plan_item(backup_path="/tmp/backup.yaml", source="tests")])

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertTrue(bridge.rollback_called)
        self.assertIsNone(panel._last_operation_backup)
        self.assertFalse(panel.undo_btn.isEnabled())

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class RollbackConfirmationDialogTests(ManagedPathTestCase):
    """Regression: rollback confirmations should show complete backup context."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml_and_backup(self):
        import tempfile
        from lib.yaml_ops import create_yaml_backup, write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_rb_confirm_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {
                "meta": {"box_layout": {"rows": 9, "cols": 9}},
                "inventory": [
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "A",
                        "box": 1,
                        "position": 5,
                        "frozen_at": "2025-01-01",
                    }
                ],
            },
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        backup_path = str(create_yaml_backup(yaml_path))
        return yaml_path, tmpdir, backup_path

    def _cleanup_yaml(self, tmpdir):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_plan_rollback_confirmation_includes_full_paths_and_source(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_FakeOperationsBridge(), yaml_path_getter=lambda: yaml_path)
            panel.add_plan_items(
                [
                    {
                        "action": "rollback",
                        "box": 0,
                        "position": 1,
                        "record_id": None,
                        "source": "human",
                        "payload": {
                            "backup_path": backup_path,
                            "source_event": {
                                "timestamp": "2026-02-12T09:00:00",
                                "action": "takeout",
                                "trace_id": "trace-audit-1",
                            },
                        },
                    }
                ]
            )

            captured = {}

            def _capture_info(_self, text):
                captured["info"] = text

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr), patch.object(
                QMessageBox,
                "setInformativeText",
                new=_capture_info,
            ), patch.object(QMessageBox, "exec", return_value=QMessageBox.No):
                panel.execute_plan()

            info = str(captured.get("info") or "")
            self.assertIn(os.path.abspath(yaml_path), info)
            self.assertIn(os.path.abspath(backup_path), info)
            self.assertIn("trace-audit-1", info)
            self.assertIn("takeout", info)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_undo_confirmation_includes_backup_and_yaml_paths(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_UndoBridge(), yaml_path_getter=lambda: yaml_path)
            panel._last_operation_backup = backup_path

            captured = {}

            def _capture_info(_self, text):
                captured["info"] = text

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr), patch.object(
                QMessageBox,
                "setInformativeText",
                new=_capture_info,
            ), patch.object(QMessageBox, "exec", return_value=QMessageBox.No):
                panel.on_undo_last()

            info = str(captured.get("info") or "")
            self.assertIn(os.path.abspath(yaml_path), info)
            self.assertIn(os.path.abspath(backup_path), info)
            self.assertIn(os.path.basename(backup_path), info)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_plan_table_rollback_row_shows_dense_context(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_FakeOperationsBridge(), yaml_path_getter=lambda: yaml_path)

            rollback_item = {
                "action": "rollback",
                "box": 0,
                "position": 1,
                "record_id": None,
                "source": "human",
                "payload": {
                    "backup_path": backup_path,
                    "source_event": {
                        "timestamp": "2026-02-12T09:00:00",
                        "action": "takeout",
                        "trace_id": "trace-audit-1",
                    },
                },
            }

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr):
                panel.add_plan_items([rollback_item])

            self.assertEqual(1, panel.plan_table.rowCount())
            note_item = None
            for col in range(panel.plan_table.columnCount()):
                cell_item = panel.plan_table.item(0, col)
                if cell_item is None:
                    continue
                text = cell_item.text() or ""
                tip = cell_item.toolTip() or ""
                if ("trace-audit-1" in text) or ("trace-audit-1" in tip) or ("takeout" in tip):
                    note_item = cell_item
                    break

            self.assertIsNotNone(note_item)
            # Note contains rollback info with trace_id
            self.assertIn("trace-audit-1", note_item.toolTip())

            # Tooltip has full details
            tooltip = note_item.toolTip()
            self.assertIn("operations.planRollbackSourceEvent", tooltip)
            self.assertIn(os.path.basename(backup_path), tooltip)
            self.assertIn("takeout", tooltip)
        finally:
            self._cleanup_yaml(tmpdir)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PrintPlanRegressionTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Regression: printing should support recently executed plans."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: self.fake_yaml_path)

    def test_print_last_executed_uses_recent_execution(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
        self.assertEqual(2, len(panel._last_executed_plan))

        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_last_executed()

        open_url.assert_called_once()

    def test_print_last_executed_uses_execution_snapshot_after_refresh(self):
        bridge = _UndoBridge()
        overview = SimpleNamespace(
            overview_shape=(1, 5, [1]),
            _current_meta={},
            _current_layout={},
            overview_pos_map={
                (1, 5): {
                    "id": 1,
                    "box": 1,
                    "position": 5,
                    "cell_line": "K562",
                    "short_name": "clone-A",
                }
            },
        )
        panel = OperationsPanel(
            bridge=bridge,
            yaml_path_getter=lambda: self.fake_yaml_path,
            overview_panel=overview,
        )
        panel.update_records_cache(
            {
                1: {
                    "id": 1,
                    "box": 1,
                    "position": 5,
                    "cell_line": "K562",
                    "short_name": "clone-A",
                }
            }
        )
        panel.add_plan_items([_make_takeout_item(record_id=1, position=5)])

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertIsInstance(panel._last_executed_print_snapshot, dict)
        overview.overview_pos_map = {}
        panel.update_records_cache({})

        captured = {}

        def _capture_html(html_text, suffix=".html", open_url_fn=None):
            captured["html"] = str(html_text or "")
            captured["suffix"] = suffix
            captured["open_url_fn"] = open_url_fn
            return "/tmp/fake_last_executed_snapshot.html"

        with patch(
            "app_gui.ui.operations_panel_actions.open_html_in_browser",
            side_effect=_capture_html,
        ):
            panel.print_last_executed()

        html = str(captured.get("html") or "")
        self.assertIn("K562", html)

    def test_print_last_executed_status_uses_executed_label(self):
        bridge = _UndoBridge()
        overview = SimpleNamespace(
            overview_shape=(1, 5, [1]),
            _current_meta={},
            _current_layout={},
            overview_pos_map={(1, 5): {"id": 1, "box": 1, "position": 5, "cell_line": "K562"}},
        )
        panel = OperationsPanel(
            bridge=bridge,
            yaml_path_getter=lambda: self.fake_yaml_path,
            overview_panel=overview,
        )

        panel.add_plan_items([_make_takeout_item(record_id=1, position=5)])

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        captured = {}

        def _capture_html(html_text, suffix=".html", open_url_fn=None):
            captured["html"] = str(html_text or "")
            captured["suffix"] = suffix
            captured["open_url_fn"] = open_url_fn
            return "/tmp/fake_last_executed_status.html"

        with patch(
            "app_gui.ui.operations_panel_actions.open_html_in_browser",
            side_effect=_capture_html,
        ):
            panel.print_last_executed()

        html = str(captured.get("html") or "")
        executed_status = tr("operations.planStatusExecuted")
        self.assertTrue(
            (f">{executed_status}<" in html) or (">operations.planStatusExecuted<" in html)
        )
        self.assertNotIn(">operations.planStatusReady<", html)

    def test_undo_clears_last_executed_print_snapshot(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)
        panel.add_plan_items([_make_takeout_item(record_id=1, position=5)])

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertIsInstance(panel._last_executed_print_snapshot, dict)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()
        self.assertIsNone(panel._last_executed_print_snapshot)

    def test_print_plan_does_not_fallback_to_last_executed(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
        self.assertEqual(2, len(panel._last_executed_plan))

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_plan()

        open_url.assert_not_called()
        self.assertTrue(any(tr("operations.noCurrentPlanToPrint") in msg for msg in messages))

    def test_print_last_executed_errors_without_recent_execution(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from unittest.mock import patch
        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_last_executed()

        open_url.assert_not_called()
        self.assertTrue(any(tr("operations.noLastExecutedToPrint") in msg for msg in messages))

    def test_print_plan_uses_business_table_headers_in_rendered_html(self):
        panel = self._new_panel(_FakeOperationsBridge())
        panel.add_plan_items([_make_takeout_item(record_id=1, position=5)])

        def _fake_build_print_grid_state(_self, _items):
            return {
                "rows": 1,
                "cols": 1,
                "boxes": [
                    {
                        "box_number": 1,
                        "box_label": "1",
                        "cells": [
                            {
                                "box": 1,
                                "position": 1,
                                "display_pos": "1",
                                "is_occupied": False,
                            }
                        ],
                    }
                ],
                "theme": "dark",
            }

        from app_gui.ui import operations_panel_actions as _ops_actions

        original_build_print_grid_state = _ops_actions._build_print_grid_state
        _ops_actions._build_print_grid_state = _fake_build_print_grid_state
        self.addCleanup(setattr, _ops_actions, "_build_print_grid_state", original_build_print_grid_state)

        captured = {}

        def _capture_html(html_text, suffix=".html", open_url_fn=None):
            captured["html"] = str(html_text or "")
            captured["suffix"] = suffix
            captured["open_url_fn"] = open_url_fn
            return "/tmp/fake_print.html"

        called_i18n_keys = []

        def _fake_i18n_tr(key, default=None, **_kwargs):
            called_i18n_keys.append(str(key))
            if default is not None:
                return str(default)
            return str(key)

        from unittest.mock import patch

        with patch("app_gui.i18n.tr", side_effect=_fake_i18n_tr), patch(
            "app_gui.ui.operations_panel_actions.open_html_in_browser",
            side_effect=_capture_html,
        ):
            panel.print_plan()

        html = str(captured.get("html") or "")
        self.assertTrue(html)
        self.assertIn("operations.colAction", called_i18n_keys)
        self.assertIn("operations.colPosition", called_i18n_keys)
        self.assertIn("operations.date", called_i18n_keys)
        self.assertIn("operations.colChanges", called_i18n_keys)
        self.assertIn("operations.colStatus", called_i18n_keys)
        self.assertIn(">Action<", html)
        self.assertIn(">Target<", html)
        self.assertIn(">Date<", html)
        self.assertIn(">Changes<", html)
        self.assertIn(">Status<", html)
        self.assertNotIn(">Done<", html)
        self.assertNotIn(">Confirmation<", html)
        self.assertNotIn("Time: _______", html)
        self.assertNotIn("Init: _______", html)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PlanPreflightGuardTests(ManagedPathTestCase):
    """Regression: preflight should block execution of invalid plans."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records):
        import tempfile
        from lib.yaml_ops import write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_preflight_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {"meta": {"box_layout": {"rows": 9, "cols": 9}}, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_add_items_triggers_preflight(self):
        """Adding items to plan should trigger preflight validation."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=1, position=5)]
            panel.add_plan_items(items)

            self.assertIsNotNone(panel._plan_preflight_report)
            self.assertEqual(1, len(panel._plan_validation_by_key))
        finally:
            self._cleanup_yaml(tmpdir)

    def test_preflight_marks_blocked_items_in_table(self):
        """Blocked items should be rejected at staging time."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            self.assertEqual(0, panel.plan_table.rowCount())
            self.assertEqual(0, len(panel.plan_items))
            self.assertFalse(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_button_disabled_when_blocked(self):
        """Execute button should be disabled when plan has blocked items."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            self.assertFalse(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_button_enabled_when_valid(self):
        """Execute button should be enabled when all items are valid."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _ConfigurableBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_move_item(record_id=1, position=5, to_position=10)]
            panel.add_plan_items(items)

            self.assertTrue(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecuteInterceptTests(ManagedPathTestCase):
    """Regression: execute should be intercepted when plan is blocked."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records):
        import tempfile
        from lib.yaml_ops import write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_intercept_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {"meta": {"box_layout": {"rows": 9, "cols": 9}}, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_blocked_does_not_call_bridge(self):
        """When staging rejects invalid items, execute remains a no-op."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            messages = []
            panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

            panel.execute_plan()

            self.assertTrue(messages)
            self.assertIsNone(bridge.last_batch_payload)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_blocked_emits_operation_event(self):
        """Execute with empty plan emits a normalized system notice."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            events = []
            panel.operation_event.connect(lambda ev: events.append(ev))

            panel.execute_plan()

            self.assertEqual(1, len(events))
            self.assertEqual("system_notice", events[0].get("type"))
            self.assertEqual("plan.execute.empty", events[0].get("code"))
        finally:
            self._cleanup_yaml(tmpdir)

    def test_stage_blocked_emits_system_notice_event(self):
        """Staging rejection should emit a system notice with blocked details."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            events = []
            panel.operation_event.connect(lambda ev: events.append(ev))

            # record_id=999 does not exist; staging must be blocked.
            panel.add_plan_items([_make_takeout_item(record_id=999, position=5)])

            self.assertTrue(events)
            latest = events[-1]
            self.assertEqual("system_notice", latest.get("type"))
            self.assertEqual("plan.stage.blocked", latest.get("code"))
            self.assertTrue((latest.get("data") or {}).get("blocked_items"))
        finally:
            self._cleanup_yaml(tmpdir)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecuteFailurePreservesPlanTests(_NoStagePreflightMixin, ManagedPathTestCase):
    """Regression: execute failure should preserve original plan for retry."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: self.fake_yaml_path)

    def test_execute_failure_preserves_entire_original_plan(self):
        """When execution fails, the entire original plan should be preserved."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {1}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
            _make_takeout_item(record_id=3, position=15),
        ]
        panel.add_plan_items(items)
        original_count = len(panel.plan_items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(original_count, len(panel.plan_items))
        record_ids = [item["record_id"] for item in panel.plan_items]
        self.assertEqual([1, 2, 3], record_ids)

    def test_execute_partial_failure_preserves_entire_plan(self):
        """Even if some items succeed before failure, entire plan should be preserved."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {2}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)
        original_ids = [item["record_id"] for item in panel.plan_items]

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(2, len(panel.plan_items))
        preserved_ids = [item["record_id"] for item in panel.plan_items]
        self.assertEqual(original_ids, preserved_ids)

    def test_execute_partial_failure_attempts_atomic_rollback(self):
        """When batch fails, all items are blocked - no partial success, no rollback needed."""
        bridge = _RollbackAwareBridge()
        bridge.batch_should_fail = True
        bridge.record_takeout_fail_ids = {2}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # --- With new executor, batch failure marks all items blocked ?no partial success ---
        # so no rollback is attempted (no backup_path from any OK item)
        self.assertFalse(bridge.rollback_called)
        # Plan is preserved on failure
        self.assertEqual(2, len(panel.plan_items))

    def test_execute_success_clears_plan(self):
        """When all items succeed, plan should be cleared."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = False
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
