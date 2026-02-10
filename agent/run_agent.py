"""CLI entry for ReAct agent runtime."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm_client import DeepSeekLLMClient, MockLLMClient
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from lib.config import YAML_PATH


def build_llm_client(model=None, mock=False):
    if mock:
        return MockLLMClient()

    chosen_model = model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
    return DeepSeekLLMClient(model=chosen_model)


def main():
    parser = argparse.ArgumentParser(description="Run LN2 ReAct agent")
    parser.add_argument("query", help="Natural language request")
    parser.add_argument("--yaml", default=YAML_PATH, help="Path to inventory YAML")
    parser.add_argument("--model", help="DeepSeek model id, e.g. deepseek-chat")
    parser.add_argument("--max-steps", type=int, default=8, help="Max ReAct steps")
    parser.add_argument("--actor-id", default="react-agent", help="Actor ID recorded in audit logs")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM instead of real model call")
    args = parser.parse_args()

    try:
        llm = build_llm_client(model=args.model, mock=args.mock)
    except Exception as exc:
        print(f"❌ Failed to initialize LLM client: {exc}")
        return 1

    runner = AgentToolRunner(yaml_path=args.yaml, actor_id=args.actor_id)
    agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=args.max_steps)
    result = agent.run(args.query)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
