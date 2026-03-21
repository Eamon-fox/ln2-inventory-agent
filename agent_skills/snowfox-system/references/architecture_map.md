# SnowFox Architecture Map

Use this reference when the user asks how SnowFox is designed, where a problem belongs, or which layer owns a behavior.

## Sources Of Truth

This bundled reference is the runtime architecture summary shipped with the app.
It must stay synchronized with the architecture docs during development, but the Agent should rely on this bundled file at runtime.

## Mental Model

SnowFox is a layered desktop monolith.

- GUI and Agent are two top-level entrypoints.
- Both share the same inventory core instead of keeping separate business rules.
- Managed inventory data lives in YAML datasets.
- The local open API is only a loopback helper for read-only query, validation, and GUI handoff. It is not a remote write API and it does not expose agent runtime.

## Layers

- Presentation layer: `app_gui/ui/`
- Application coordination layer: `app_gui/application/`, `app_gui/main.py`, `app_gui/main_window_flows.py`, `app_gui/tool_bridge.py`, `app_gui/plan_*.py`
- Core business layer: `agent/` plus the business parts of `lib/`
- Infrastructure layer: YAML I/O, path policy, backup, audit, config, environment adapters under `lib/`

Dependency direction must stay:

`presentation -> application -> core -> infrastructure`

## Module Map

- `gui_presentation`: Qt widgets, panels, dialogs, rendering
- `gui_application`: GUI orchestration, event flows, plan execution, bridge wiring
- `agent_runtime`: ReAct loop, model calls, tool dispatch, hooks, recovery behavior
- `inventory_core`: tool API, tool registry, validation, schema, YAML business rules
- `migration_import`: migration workspace, import pipeline, migration validation
- `release_packaging`: installer, spec files, release assets

## Stable Entry Points

- `lib/tool_api.py`: shared inventory tool surface
- `lib/tool_registry.py`: tool contract source of truth
- `agent/tool_runner.py`: agent tool dispatch
- `app_gui/application/use_cases.py`: GUI use-case layer
- `app_gui/main.py`: GUI composition root

## Shared Chokepoints

These files are cross-module chokepoints and should be treated as shared boundaries:

- `lib/tool_api.py`
- `lib/tool_registry.py`
- `app_gui/tool_bridge.py`
- `app_gui/main.py`
- `app_gui/main_window_flows.py`
- `app_gui/i18n/translations/en.json`
- `app_gui/i18n/translations/zh-CN.json`

## Diagnosis Heuristic

When explaining or debugging behavior, classify it first:

- UI rendering, dialog layout, table display: `gui_presentation`
- Main-window flow, plan execution, settings handoff, GUI coordination: `gui_application`
- Tool choice, prompt behavior, runtime recovery, skill routing: `agent_runtime`
- Schema meaning, validation errors, YAML truth, tool semantics: `inventory_core`
- Import or migration pipeline: `migration_import`
