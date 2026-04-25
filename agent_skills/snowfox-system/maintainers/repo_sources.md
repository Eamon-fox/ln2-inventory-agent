# Repo Sync Map

This file is for maintainers and tests, not for runtime Agent decisions on end-user machines.

The Agent should not require these repo files to answer normal product questions because packaged installs may not include them.
Use this map only to keep the bundled skill references synchronized during development.

## Architecture

- `docs/00-约束模型.md`
- `docs/01-系统架构总览.md`
- `docs/02-模块地图.md`
- `docs/03-共享瓶颈点.md`

## Module Guides

- `docs/modules/11-界面应用层.md`
- `docs/modules/12-智能体运行时.md`
- `docs/modules/13-库存核心.md`

## GUI Surface

- `app_gui/main.py`
- `app_gui/main_window_flows.py`
- `app_gui/ui/dialogs/settings_dialog.py`
- `app_gui/ui/dialogs/help_dialog.py`
- `app_gui/ui/dialogs/settings_dialog_feedback_section.py`
- `app_gui/application/open_api/service.py`

## Agent Rules

- `agent/react_agent.py`
- `agent/react_agent_runtime.py`
- `agent/tool_runner.py`
- `agent/tool_hooks.py`

## Tool Truth

- `lib/tool_registry.py`
- `lib/tool_api.py`

## Existing Skills

- `agent_skills/migration/SKILL.md`
- `agent_skills/yaml-repair/SKILL.md`

## Verification Rule

Development-time tests may compare the bundled skill references against these repo files.
At runtime, the bundled skill references remain the usable authority.
