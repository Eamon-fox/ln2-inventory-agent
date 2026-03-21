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
        self.plan_store = PlanStore()
        self.bridge = GuiToolBridge()
        self.focus_calls = []
        self.takeout_prefills = []
        self.add_prefills = []
        self.ai_prompts = []
        self.controller = LocalOpenApiController(
            yaml_path_getter=lambda: self.fake_yaml_path,
            bridge=self.bridge,
            plan_store=self.plan_store,
            gui_dispatcher=None,
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

        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-add",
            {},
            payload={"box": 1, "positions": [2, 3]},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual([2, 3], self.add_prefills[0]["positions"])

        status, payload = self.controller.handle_request(
            "POST",
            "/api/v1/gui/prefill-ai-prompt",
            {},
            payload={"prompt": "show the K562 records"},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual("show the K562 records", self.ai_prompts[0]["prompt"])

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


if __name__ == "__main__":
    unittest.main()
