---
name: snowfox-local-api
description: Discover, probe, and use the SnowFox local Open API for read-only inventory queries, validation, and GUI handoff. Use when the user wants SnowFox data or wants the GUI prepared without direct writes.
---

# SnowFox Local Open API

Follow this skill when the user wants to query the current SnowFox session, validate the active dataset, or prepare GUI context without executing write operations.

## Core Workflow

1. Make sure the SnowFox desktop app is running.
2. If it is not running, try the host environment's app-launch mechanism first.
3. Do not hardcode an install path. If no launch method is available, ask the user to open SnowFox manually.
4. Probe the local API before doing any inventory work.
5. If the API is unreachable, tell the user to open SnowFox Settings and check whether Local Open API is enabled and whether the port matches the one you are probing.
6. Once the API is reachable, call `/api/v1/session` to learn which dataset is currently open in the GUI.
7. If the user needs another managed dataset, call `/api/v1/datasets`, choose the target dataset, then call `/api/v1/session/switch-dataset`.
8. Prefer read/query endpoints first. Use GUI handoff endpoints when the user wants the SnowFox window prepared for a human to review or execute.
9. Treat staged plan items as GUI staging only. They are not executed writes.

## Connection Checklist

- Probe loopback only: `http://127.0.0.1:<port>`
- Default first guess: `37666`
- First probe: `GET /api/v1/health`
- Session probe: `GET /api/v1/session`
- If the app responds but `dataset_exists` is `false`, tell the user the current GUI session has no valid open dataset yet.

## API Reference

{{LOCAL_OPEN_API_ROUTE_REFERENCE}}

## Failure Handling

- Connection refused or timeout:
  - SnowFox may not be running
  - Local Open API may be disabled
  - the port may differ from the default
- `404 route_not_found`:
  - the app version may not expose that route yet
- `404 dataset_not_found`:
  - the requested managed dataset name does not exist in the current SnowFox data root
- `400 invalid_request`:
  - fix malformed params instead of retrying unchanged
- validation failure:
  - return `report.errors` and `report.warnings` clearly to the user
- `plan_stage_blocked` or `plan_action_not_allowed`:
  - explain that SnowFox accepted only GUI staging, not direct execution

## Non-Negotiables

- Do not describe this API as direct write access.
- Do not assume any install path for SnowFox.
- Do not bypass the GUI session boundary.
- Do not describe managed dataset switching as background file access.
- Do not tell the user that staging equals execution.
- When the API is unavailable, explicitly guide the user to SnowFox Settings -> Local Open API.
