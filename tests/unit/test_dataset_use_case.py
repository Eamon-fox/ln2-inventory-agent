"""Unit tests for dataset switching application use case."""

import os
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import (
    DatasetUseCase,
    EventBus,
    MigrationModeUseCase,
    PlanExecutionUseCase,
    PlanRunUseCase,
)
from lib.domain.commands import SwitchDatasetCommand
from lib.domain.events import DatasetSwitched, MigrationModeChanged, OperationExecuted


class DatasetUseCaseTests(unittest.TestCase):
    def test_switch_dataset_updates_state_and_publishes_event(self):
        saved_configs = []
        events = []
        prepared = []

        bus = EventBus()
        bus.subscribe(DatasetSwitched, events.append)
        use_case = DatasetUseCase(
            normalize_yaml_path=lambda path: str(path or "").strip(),
            assert_allowed_path=lambda path, must_exist=True: path,
            save_gui_config=lambda cfg: saved_configs.append(dict(cfg)),
            ensure_runtime_ready=lambda path: prepared.append(path) or path,
            event_bus=bus,
        )
        session = SimpleNamespace(
            current_yaml_path=os.path.abspath("D:/inventories/old/inventory.yaml"),
            gui_config={},
        )
        target = os.path.abspath("D:/inventories/new/inventory.yaml")

        result = use_case.switch_dataset(
            session=session,
            command=SwitchDatasetCommand(yaml_path=target, reason="manual_switch"),
        )

        self.assertTrue(result.changed)
        self.assertEqual(target, session.current_yaml_path)
        self.assertEqual(target, session.gui_config["yaml_path"])
        self.assertEqual([target], prepared)
        self.assertEqual(1, len(saved_configs))
        self.assertEqual(1, len(events))
        self.assertEqual("manual_switch", events[0].reason)
        self.assertEqual(os.path.abspath(target), events[0].new_path)

    def test_switch_dataset_skips_same_path_for_manual_switch(self):
        saves = []
        events = []
        path = os.path.abspath("D:/inventories/same/inventory.yaml")
        prepared = []

        bus = EventBus()
        bus.subscribe(DatasetSwitched, events.append)
        use_case = DatasetUseCase(
            normalize_yaml_path=lambda value: str(value),
            assert_allowed_path=lambda value, must_exist=True: value,
            save_gui_config=lambda cfg: saves.append(dict(cfg)),
            ensure_runtime_ready=lambda value: prepared.append(value) or value,
            event_bus=bus,
        )
        session = SimpleNamespace(
            current_yaml_path=path,
            gui_config={},
        )

        result = use_case.switch_dataset(
            session=session,
            command=SwitchDatasetCommand(yaml_path=path, reason="manual_switch"),
        )

        self.assertFalse(result.changed)
        self.assertEqual([path], prepared)
        self.assertEqual([], saves)
        self.assertEqual([], events)
        self.assertNotIn("yaml_path", session.gui_config)

    def test_switch_dataset_forces_refresh_for_import_success(self):
        saves = []
        events = []
        path = os.path.abspath("D:/inventories/same/inventory.yaml")
        prepared = []

        bus = EventBus()
        bus.subscribe(DatasetSwitched, events.append)
        use_case = DatasetUseCase(
            normalize_yaml_path=lambda value: str(value),
            assert_allowed_path=lambda value, must_exist=True: value,
            save_gui_config=lambda cfg: saves.append(dict(cfg)),
            ensure_runtime_ready=lambda value: prepared.append(value) or value,
            event_bus=bus,
        )
        session = SimpleNamespace(
            current_yaml_path=path,
            gui_config={},
        )

        result = use_case.switch_dataset(
            session=session,
            command=SwitchDatasetCommand(yaml_path=path, reason="import_success"),
        )

        self.assertTrue(result.changed)
        self.assertEqual([path], prepared)
        self.assertEqual(1, len(saves))
        self.assertEqual(1, len(events))
        self.assertEqual("import_success", events[0].reason)
        self.assertEqual(path, session.gui_config["yaml_path"])


class MigrationModeUseCaseTests(unittest.TestCase):
    def test_set_mode_publishes_event(self):
        events = []
        bus = EventBus()
        bus.subscribe(MigrationModeChanged, events.append)
        use_case = MigrationModeUseCase(event_bus=bus)

        emitted = use_case.set_mode(enabled=True, reason="ai_panel")

        self.assertEqual(True, emitted.enabled)
        self.assertEqual("ai_panel", emitted.reason)
        self.assertEqual(1, len(events))
        self.assertEqual(True, events[0].enabled)


class PlanExecutionUseCaseTests(unittest.TestCase):
    def test_report_operation_completed_publishes_event(self):
        events = []
        bus = EventBus()
        bus.subscribe(OperationExecuted, events.append)
        use_case = PlanExecutionUseCase(event_bus=bus)

        emitted = use_case.report_operation_completed(
            success=True,
            operation="plan_execute",
            source="operations_panel",
        )

        self.assertTrue(emitted.success)
        self.assertEqual("plan_execute", emitted.operation)
        self.assertEqual("operations_panel", emitted.reason)
        self.assertEqual(1, len(events))
        self.assertEqual("plan_execute", events[0].operation)
        self.assertTrue(events[0].success)


class PlanRunUseCaseTests(unittest.TestCase):
    def test_execute_calls_run_plan_and_collects_normalized_rows(self):
        input_items = [{"action": "takeout", "record_id": 5}]
        fake_report = {
            "ok": False,
            "items": [
                {
                    "ok": True,
                    "item": input_items[0],
                    "response": {"backup_path": "/tmp/bak_5.yaml"},
                },
                {
                    "ok": False,
                    "item": {"action": "move", "record_id": 8},
                    "message": "boom",
                    "error_code": "validation_failed",
                },
            ],
        }
        calls = []
        use_case = PlanRunUseCase(
            run_plan_fn=lambda yaml_path, plan_items, bridge, mode: (
                calls.append((yaml_path, list(plan_items), bridge, mode)) or fake_report
            ),
            summarize_plan_execution_fn=lambda report, rollback_info: {
                "ok_count": 1,
                "fail_count": 1,
                "applied_count": 1,
                "rollback_ok": bool((rollback_info or {}).get("ok", False)),
            },
        )

        result = use_case.execute(
            yaml_path="D:/inventories/current/inventory.yaml",
            plan_items=input_items,
            bridge=object(),
            mode="execute",
        )

        self.assertEqual(1, len(calls))
        self.assertEqual(fake_report, result.report)
        self.assertEqual("OK", result.results[0][0])
        self.assertEqual("FAIL", result.results[1][0])
        self.assertEqual("validation_failed", result.results[1][2]["error_code"])

        summary = use_case.summarize(report=result.report, rollback_info={"ok": True})
        self.assertEqual(1, summary["ok_count"])
        self.assertEqual(1, summary["fail_count"])
        self.assertTrue(summary["rollback_ok"])


if __name__ == "__main__":
    unittest.main()
