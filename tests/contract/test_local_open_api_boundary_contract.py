"""Contract checks for the local loopback Open API boundary."""

import unittest

from tests.contract.doc_contract_loader import ROOT, load_contract_block


ARCH_DOC = ROOT / "docs" / "01-系统架构总览.md"


class LocalOpenApiBoundaryContractTests(unittest.TestCase):
    def test_local_open_api_boundary_contract_declares_expected_limits(self):
        contract = load_contract_block(ARCH_DOC, "local_open_api_boundary")
        rules = dict(contract.get("rules") or {})

        self.assertEqual("gui_application", rules.get("owner"))
        transport = dict(rules.get("transport") or {})
        self.assertEqual("127.0.0.1", transport.get("bind_host"))
        self.assertEqual(False, transport.get("enabled_by_default"))
        self.assertEqual(True, transport.get("remembers_last_enabled_state"))
        self.assertEqual(True, transport.get("requires_running_gui_instance"))

        data_scope = dict(rules.get("data_scope") or {})
        self.assertEqual("current_gui_session", data_scope.get("dataset_source"))
        self.assertEqual(True, data_scope.get("client_must_not_override_yaml_path"))

        exposure = dict(rules.get("exposure") or {})
        self.assertEqual(True, exposure.get("must_use_explicit_route_allowlist"))
        self.assertEqual(True, exposure.get("must_not_execute_write_tools"))
        self.assertEqual("agent_runtime", exposure.get("must_not_depend_on"))


if __name__ == "__main__":
    unittest.main()
