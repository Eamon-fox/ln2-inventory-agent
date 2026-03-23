"""Integration tests for the local loopback Open API."""

import json
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application.open_api.service import LocalOpenApiController, LocalOpenApiService
from app_gui.tool_bridge import GuiToolBridge
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.plan_item_factory import build_add_plan_item, build_rollback_plan_item
from lib.plan_store import PlanStore
from lib.yaml_ops import write_yaml
from tests.managed_paths import ManagedPathTestCase


class LocalOpenApiTests(ManagedPathTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        write_yaml(
            {
                "meta": {"box_layout": {"rows": 9, "cols": 9, "box_count": 5, "box_numbers": [1, 2, 3, 4, 5]}},
                "inventory": [
                    {
                        "id": 1,
                        "short_name": "rec-1",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2024-01-01",
                    }
                ],
            },
            path=self.fake_yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        self.dataset_state = {"yaml_path": self.fake_yaml_path}
        self.other_yaml_path = self.ensure_dataset_yaml(
            "dataset-b",
            payload={
                "meta": {"box_layout": {"rows": 9, "cols": 9, "box_count": 5, "box_numbers": [1, 2, 3, 4, 5]}},
                "inventory": [
                    {
                        "id": 2,
                        "short_name": "rec-2",
                        "box": 2,
                        "position": 2,
                        "frozen_at": "2024-01-02",
                    }
                ],
            },
        )
        self.plan_store = PlanStore()
        self.bridge = GuiToolBridge()
        self.focus_calls = []
        self.takeout_prefills = []
        self.add_prefills = []
        self.ai_prompts = []
        self.controller = LocalOpenApiController(
            yaml_path_getter=lambda: self.dataset_state["yaml_path"],
            bridge=self.bridge,
            plan_store=self.plan_store,
            gui_dispatcher=None,
            switch_dataset_fn=self._switch_dataset,
            focus_window_fn=lambda: self.focus_calls.append("focus") or True,
            prefill_takeout_fn=lambda payload: self.takeout_prefills.append(dict(payload)),
            prefill_add_fn=lambda payload: self.add_prefills.append(dict(payload)),
            prefill_ai_prompt_fn=lambda prompt, focus: self.ai_prompts.append(
                {"prompt": prompt, "focus": bool(focus)}
            ),
        )
        self.service = LocalOpenApiService(self.controller, port=0)

    def tearDown(self):
        try:
            self.service.stop()
        finally:
            super().tearDown()

    def _request(self, path, *, method="GET", payload=None):
        if not self.service.is_running():
            self.service.start(port=0)
        url = f"http://127.0.0.1:{self.service.bound_port}{path}"
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _switch_dataset(self, yaml_path, reason):
        self.assertEqual("api_switch", reason)
        normalized = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
        self.dataset_state["yaml_path"] = normalized
        return normalized

    def test_http_health_and_search_routes_work_on_loopback(self):
        status, payload = self._request("/api/v1/health")
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.fake_yaml_path, payload["result"]["dataset_path"])

        query = urllib.parse.urlencode({"query": "rec-1", "max_results": 5})
        status, payload = self._request(f"/api/v1/inventory/search?{query}")
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        records = list((payload.get("result") or {}).get("records") or [])
        self.assertTrue(records)
        self.assertEqual("rec-1", records[0].get("short_name"))

    def test_http_capabilities_route_describes_allowlist_and_boundary(self):
        status, payload = self._request("/api/v1/capabilities")

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        result = payload.get("result") or {}
        self.assertEqual("local_open_api", result.get("service"))
        self.assertEqual(False, result.get("boundary", {}).get("inventory_write_enabled"))
        self.assertIn("meta_only", result.get("validation_modes") or [])
        routes = list(result.get("routes") or [])
        validate_route = next(
            item for item in routes if item.get("method") == "GET" and item.get("path") == "/api/v1/inventory/validate"
        )
        mode_param = next(item for item in (validate_route.get("params") or []) if item.get("name") == "mode")
        self.assertEqual(["auto", "current_inventory", "document", "meta_only"], mode_param.get("accepted_values"))

        search_route = next(
            item for item in routes if item.get("method") == "GET" and item.get("path") == "/api/v1/inventory/search"
        )
        search_param_names = {item.get("name") for item in (search_route.get("params") or [])}
        self.assertTrue({"case_sensitive", "status", "sort_by", "sort_order"} <= search_param_names)
        mode_param = next(item for item in (search_route.get("params") or []) if item.get("name") == "mode")
        self.assertEqual(["fuzzy", "exact", "keywords"], mode_param.get("accepted_values"))

        filter_route = next(
            item for item in routes if item.get("method") == "GET" and item.get("path") == "/api/v1/inventory/filter"
        )
        filter_param_names = {item.get("name") for item in (filter_route.get("params") or [])}
        self.assertTrue({"include_inactive", "sort_by", "sort_order"} <= filter_param_names)

        prefill_add_route = next(
            item for item in routes if item.get("method") == "POST" and item.get("path") == "/api/v1/gui/prefill-add"
        )
        self.assertEqual(
            [{"kind": "at_least_one_of", "params": ["position", "positions"]}],
            prefill_add_route.get("constraints"),
        )

        stage_plan_route = next(
            item for item in routes if item.get("method") == "GET" and item.get("path") == "/api/v1/gui/stage-plan"
        )
        self.assertEqual("gui_stage_state", stage_plan_route.get("effect"))

    def test_http_validate_route_uses_current_gui_session_dataset(self):
        external_yaml = Path(self.install_root) / "outside.yaml"
        external_yaml.write_text("not: valid: yaml:\n", encoding="utf-8")

        query = urllib.parse.urlencode(
            {
                "yaml_path": str(external_yaml),
                "fail_on_warnings": "false",
            }
        )
        status, payload = self._request(f"/api/v1/inventory/validate?{query}")

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"], payload)
        report = payload.get("report") or {}
        self.assertEqual("current_inventory", report.get("mode"))
        self.assertEqual(0, report.get("error_count"))

    def test_http_stats_route_supports_summary_only_mode(self):
        status, payload = self._request("/api/v1/inventory/stats?summary_only=true")

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        result = payload.get("result") or {}
        self.assertTrue(result.get("summary_only"))
        self.assertEqual(405, result.get("total_slots"))
        self.assertEqual(1, result.get("record_count"))
        self.assertEqual(5, result.get("box_count"))
        self.assertNotIn("boxes", result)
        self.assertNotIn("occupancy", result)
        self.assertNotIn("inventory_preview", result)

    def test_http_stats_route_supports_box_summary_only_mode(self):
        status, payload = self._request("/api/v1/inventory/stats?box=1&summary_only=true")

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        result = payload.get("result") or {}
        self.assertTrue(result.get("summary_only"))
        self.assertEqual(1, result.get("box"))
        self.assertEqual(81, result.get("box_total_slots"))
        self.assertEqual(1, result.get("box_occupied"))
        self.assertEqual(1, result.get("box_record_count"))
        self.assertNotIn("box_records", result)
        self.assertNotIn("inventory_preview", result)

    def test_http_datasets_and_switch_dataset_routes_work_for_managed_sessions(self):
        status, payload = self._request("/api/v1/datasets")

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        datasets = list((payload.get("result") or {}).get("datasets") or [])
        self.assertEqual(2, len(datasets))
        self.assertTrue(any(item.get("dataset_name") == "_fake" and item.get("is_current") for item in datasets))

        status, payload = self._request(
            "/api/v1/session/switch-dataset",
            method="POST",
            payload={"dataset_name": "dataset-b"},
        )

        self.assertEqual(200, status)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(self.other_yaml_path, self.dataset_state["yaml_path"])
        self.assertEqual("dataset-b", payload["result"]["dataset_name"])
        self.assertEqual("_fake", payload["result"]["previous_dataset_name"])
        self.assertEqual("managed_dataset_session_switch", payload["effect"])
        self.assertFalse(payload["inventory_written"])

        status, payload = self._request("/api/v1/session")
        self.assertEqual(200, status)
        self.assertEqual(self.other_yaml_path, payload["result"]["dataset_path"])

    def test_http_switch_dataset_rejects_unknown_dataset_name(self):
        status, payload = self._request(
            "/api/v1/session/switch-dataset",
            method="POST",
            payload={"dataset_name": "missing-dataset"},
        )

        self.assertEqual(404, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("dataset_not_found", payload["error_code"])

    def test_http_switch_dataset_rejects_yaml_path_parameter(self):
        status, payload = self._request(
            "/api/v1/session/switch-dataset",
            method="POST",
            payload={"yaml_path": self.other_yaml_path},
        )

        self.assertEqual(400, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("invalid_request", payload["error_code"])
        self.assertEqual("yaml_path", payload["field"])

    def test_http_unknown_route_is_rejected(self):
        status, payload = self._request("/api/v1/inventory/add-entry")
        self.assertEqual(404, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("route_not_found", payload["error_code"])

    def test_http_validate_route_rejects_invalid_mode(self):
        status, payload = self._request("/api/v1/inventory/validate?mode=bad-mode")

        self.assertEqual(400, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("invalid_request", payload["error_code"])
        self.assertEqual("mode", payload["field"])
        self.assertEqual(["auto", "current_inventory", "document", "meta_only"], payload["accepted_values"])

    def test_controller_prefill_routes_update_gui_handoff_targets(self):
        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-takeout",
            {},
            payload={"record_id": 1, "box": 1, "position": 1},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(1, self.takeout_prefills[0]["record_id"])
        self.assertEqual(["focus"], self.focus_calls)
        self.assertEqual("gui_handoff", payload["effect"])
        self.assertFalse(payload["inventory_written"])
        self.assertFalse(payload["executed"])

        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-add",
            {},
            payload={"box": 1, "positions": [2, 3]},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual([2, 3], self.add_prefills[0]["positions"])
        self.assertFalse(payload["inventory_written"])

        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-ai-prompt",
            {},
            payload={"prompt": "show the K562 records"},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual("show the K562 records", self.ai_prompts[0]["prompt"])
        self.assertEqual("gui_handoff", payload["effect"])

    def test_controller_prefill_add_requires_position_or_positions(self):
        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-add",
            {},
            payload={"box": 1},
        )
        self.assertEqual(400, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("invalid_request", payload["error_code"])
        self.assertEqual("position", payload["field"])

    def test_controller_stage_plan_only_stages_allowed_actions(self):
        item = build_add_plan_item(
            box=1,
            positions=[2],
            stored_at="2024-01-02",
            fields={},
            source="api-test",
        )
        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/stage-plan",
            {},
            payload={"items": [item]},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(1, payload["result"]["staged_count"])
        self.assertEqual(1, self.plan_store.count())
        self.assertEqual("gui_stage_only", payload["effect"])
        self.assertTrue(payload["staged"])
        self.assertFalse(payload["inventory_written"])

        status, payload = self.controller.handle_request(
            "GET",
            "/api/v1/gui/stage-plan",
            {},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(1, payload["result"]["count"])
        self.assertEqual("add", payload["result"]["items"][0]["action"])
        self.assertEqual("gui_stage_state", payload["effect"])

        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/stage-plan",
            {},
            payload={"items": [item]},
        )
        self.assertEqual(409, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("plan_stage_blocked", payload["error_code"])

        rollback_item = build_rollback_plan_item(backup_path="/tmp/demo.yaml", source="api-test")
        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/stage-plan",
            {},
            payload={"items": [rollback_item]},
        )
        self.assertEqual(409, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("plan_action_not_allowed", payload["error_code"])
        self.assertEqual(["add", "edit", "move", "takeout"], payload["accepted_values"])


if __name__ == "__main__":
    unittest.main()
