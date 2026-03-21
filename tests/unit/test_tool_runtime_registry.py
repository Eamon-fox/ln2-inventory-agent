import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from agent.tool_runtime_registry import build_tool_runtime_specs, expected_runtime_tool_names
from tests.managed_paths import ManagedPathTestCase


class ToolRuntimeRegistryTests(ManagedPathTestCase):
    def _make_runner(self):
        return AgentToolRunner(yaml_path=self.fake_yaml_path)

    def test_runtime_specs_cover_all_dispatch_tools(self):
        runner = self._make_runner()

        runtime_specs = build_tool_runtime_specs(runner)

        self.assertEqual(expected_runtime_tool_names(), frozenset(runtime_specs))
        self.assertNotIn("question", runtime_specs)

    def test_add_entry_runtime_spec_collects_runtime_metadata(self):
        runner = self._make_runner()

        spec = build_tool_runtime_specs(runner)["add_entry"]

        self.assertTrue(callable(spec.handler))
        self.assertTrue(callable(spec.stage_builder))
        self.assertEqual(("positions",), spec.layout_array_fields)
        self.assertTrue(callable(spec.schema_enricher))
        self.assertTrue(callable(spec.validation_payload_adapter))
        self.assertTrue(callable(spec.error_hint))
        self.assertTrue(callable(spec.status_formatter))

    def test_validate_runtime_spec_owns_hint_and_after_hook(self):
        runner = self._make_runner()

        spec = build_tool_runtime_specs(runner)["validate"]

        self.assertTrue(callable(spec.error_hint))
        self.assertTrue(callable(spec.after_hook))
        self.assertIsNone(spec.stage_builder)

    def test_fs_write_runtime_spec_owns_input_guard_and_hooks(self):
        runner = self._make_runner()

        spec = build_tool_runtime_specs(runner)["fs_write"]

        self.assertTrue(callable(spec.input_guard))
        self.assertTrue(callable(spec.before_hook))
        self.assertTrue(callable(spec.after_hook))
