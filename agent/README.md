# ReAct Agent Runtime

This directory provides a minimal ReAct agent runtime on top of the unified Tool API.

## Run (mock mode)

```bash
python agent/run_agent.py "查询K562最近冻存记录" --mock
```

## Run (real model via LiteLLM)

```bash
pip install litellm
export LITELLM_MODEL="anthropic/claude-3-5-sonnet"
# set provider keys in env according to your model/provider
python agent/run_agent.py "把ID 10 的位置 23 标记为取出，日期今天" --yaml ./ln2_inventory.yaml
```

All write operations executed by the agent go through unified Tool API and keep
the same audit schema as human operations.
