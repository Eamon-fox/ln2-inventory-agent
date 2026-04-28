"""Unit tests for development diagnostics switches."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import EventBus
from lib import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_default_off_writes_no_log(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "SNOWFOX_CONFIG_ROOT": tmp,
                "SNOWFOX_DIAGNOSTICS": "",
                "SNOWFOX_EVENT_BUS_TRACE": "",
            },
            clear=False,
        ):
            diagnostics.log_event("test.event", action="noop")
            self.assertFalse(os.path.exists(diagnostics.diagnostics_log_path()))

    def test_diagnostics_enabled_writes_sanitized_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "SNOWFOX_CONFIG_ROOT": tmp,
                "SNOWFOX_DIAGNOSTICS": "1",
            },
            clear=False,
        ):
            diagnostics.log_event(
                "tool.read",
                action="search_records",
                prompt="do not log this",
                api_key="secret",
                yaml_path="D:/data/inventory.yaml",
            )
            path = diagnostics.diagnostics_log_path()
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as handle:
                row = json.loads(handle.readline())
            self.assertEqual("tool.read", row["event"])
            self.assertEqual("[redacted]", row["prompt"])
            self.assertEqual("[redacted]", row["api_key"])
            self.assertEqual("inventory.yaml", row["yaml_path"])

    def test_event_bus_trace_requires_main_diagnostics_switch(self):
        class _Event:
            pass

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "SNOWFOX_CONFIG_ROOT": tmp,
                "SNOWFOX_DIAGNOSTICS": "",
                "SNOWFOX_EVENT_BUS_TRACE": "1",
            },
            clear=False,
        ):
            bus = EventBus()
            bus.subscribe(_Event, lambda _event: None)
            bus.publish(_Event())
            self.assertFalse(os.path.exists(diagnostics.diagnostics_log_path()))

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "SNOWFOX_CONFIG_ROOT": tmp,
                "SNOWFOX_DIAGNOSTICS": "1",
                "SNOWFOX_EVENT_BUS_TRACE": "1",
            },
            clear=False,
        ):
            bus = EventBus()
            bus.subscribe(_Event, lambda _event: None)
            bus.publish(_Event())
            with open(diagnostics.diagnostics_log_path(), "r", encoding="utf-8") as handle:
                events = [json.loads(line)["event"] for line in handle if line.strip()]
            self.assertIn("event_bus.publish", events)
            self.assertIn("event_bus.handler", events)


if __name__ == "__main__":
    unittest.main()

