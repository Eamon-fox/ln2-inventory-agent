"""Contract checks for agent context checkpointing architecture rules."""

import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import ROOT, load_contract_block


ARCH_DOC = ROOT / "docs" / "01-系统架构总览.md"


class AgentContextCheckpointingContractTests(unittest.TestCase):
    def test_architecture_doc_declares_checkpointing_contract(self):
        contract = load_contract_block(ARCH_DOC, "agent_context_checkpointing")
        rules = dict(contract.get("rules") or {})

        self.assertEqual("agent_runtime", rules.get("owner"))

        summary_call = dict(rules.get("checkpoint_summary_call") or {})
        self.assertEqual("current_active_model", summary_call.get("model_source"))
        self.assertTrue(summary_call.get("fresh_context"))
        self.assertFalse(summary_call.get("tools_enabled"))
        self.assertEqual("fixed_summary_prompt", summary_call.get("prompt_type"))

        resume_call = dict(rules.get("checkpoint_resume_call") or {})
        self.assertTrue(resume_call.get("requires_fixed_resume_prompt"))
        self.assertTrue(resume_call.get("requires_checkpoint_summary"))

        gui_behavior = dict(rules.get("gui_session_behavior") or {})
        self.assertTrue(gui_behavior.get("gui_must_treat_summary_state_as_opaque"))
        self.assertTrue(gui_behavior.get("gui_new_chat_must_clear_summary_state"))
        self.assertEqual("current_ai_chat_session_only", gui_behavior.get("default_lifecycle"))


if __name__ == "__main__":
    unittest.main()
