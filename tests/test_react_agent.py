import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from lib.yaml_ops import write_yaml


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


class _SequenceLLM:
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def complete(self, messages, temperature=0.0):
        _ = messages
        _ = temperature
        if not self._outputs:
            return '{"thought":"done","action":"finish","action_input":{},"final":"done"}'
        return self._outputs.pop(0)


class _CapturePromptLLM:
    def __init__(self):
        self.last_messages = None

    def complete(self, messages, temperature=0.0):
        _ = temperature
        self.last_messages = messages
        return '{"thought":"memory check","action":"finish","action_input":{},"final":"ok"}'


class ReactAgentTests(unittest.TestCase):
    def test_react_agent_calls_tool_then_finishes(self):
        with tempfile.TemporaryDirectory(prefix="ln2_react_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 1,
                        "positions": [1],
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            llm = _SequenceLLM(
                [
                    json.dumps(
                        {
                            "thought": "Need to query inventory first",
                            "action": "query_inventory",
                            "action_input": {"cell": "K562"},
                            "final": "",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "thought": "I have enough info",
                            "action": "finish",
                            "action_input": {},
                            "final": "Found one K562 record.",
                        },
                        ensure_ascii=False,
                    ),
                ]
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path), actor_id="react-test")
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=4)
            result = agent.run("Find K562 entries")

            self.assertTrue(result["ok"])
            self.assertEqual("Found one K562 record.", result["final"])
            self.assertEqual(1, len(result["scratchpad"]))
            obs = result["scratchpad"][0]["observation"]
            self.assertTrue(obs["ok"])
            self.assertEqual(1, obs["result"]["count"])

    def test_react_agent_includes_conversation_history_in_prompt(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml", actor_id="react-test")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=2)

        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
            {"role": "tool", "content": "ignored"},
        ]
        result = agent.run("repeat your last response", conversation_history=history)

        self.assertTrue(result["ok"])
        self.assertEqual(2, result.get("conversation_history_used"))
        messages = llm.last_messages
        if not isinstance(messages, list):
            self.fail("LLM should receive a message list")
        self.assertGreaterEqual(len(messages), 2)

        prompt_payload = json.loads(messages[1]["content"])
        memory = prompt_payload.get("conversation_history")
        if not isinstance(memory, list):
            self.fail("conversation_history should be a list")
        self.assertEqual(2, len(memory))
        self.assertEqual("user", memory[0]["role"])
        self.assertEqual("assistant", memory[1]["role"])


if __name__ == "__main__":
    unittest.main()
