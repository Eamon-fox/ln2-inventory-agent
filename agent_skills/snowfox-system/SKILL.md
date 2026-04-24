---
name: snowfox-system
description: Understand SnowFox's own architecture, GUI operation paths, and capability boundaries. Use when the user asks how the app works, where to perform an action, what the Agent or local API can do, or proposes an unsupported operation that should be refused early.
---

# SnowFox System

Follow this skill when the user is asking about SnowFox itself rather than asking SnowFox to inspect inventory data.

## Core Workflow

1. First decide whether the request is about architecture, GUI operation path, capability boundary, or an unsupported action.
2. Read the bundled architecture and boundary references before proposing a workflow.
3. If the action belongs to a user-operated GUI flow, explain the exact UI path instead of pretending the Agent can do it.
4. If the request crosses a documented boundary, refuse early and state the nearest supported path.
5. Only continue into normal tool usage after confirming the requested action is actually supported.

## Read Next As Needed

- Runtime capability catalog: [references/runtime_capabilities.yaml](references/runtime_capabilities.yaml)
- Field schema reference: [references/field_schema.md](references/field_schema.md)
- Architecture map: [references/architecture_map.md](references/architecture_map.md)
- GUI and operator paths: [references/user_workflows.md](references/user_workflows.md)
- Capability boundaries and early-refusal rules: [references/capability_boundaries.md](references/capability_boundaries.md)

## Non-Negotiables

- Treat the bundled references in this skill as the runtime authority for SnowFox system behavior.
- Do not invent product features, GUI flows, or write paths that are not documented.
- Do not present GUI-only actions as Agent capabilities.
- Do not present internal bash/powershell engines as Agent-visible tools; command execution is the single `shell` tool.
- Do not keep retrying tools after a known product boundary has already been hit.
- If bundled references are still insufficient, say the capability is unknown or unsupported instead of assuming.
