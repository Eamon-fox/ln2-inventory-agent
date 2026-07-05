---
name: snowfox-local-api
description: Discover, probe, and use the SnowFox local Open API for read-only inventory queries, validation, and GUI handoff — including staging write plans into the GUI for human confirmation. The API never writes inventory directly; all writes land as staged plans a human executes in the GUI.
---

# SnowFox Local Open API

Follow this skill when the user wants to query the current SnowFox session, validate the active dataset, prepare GUI context, or stage write operations into the GUI for human confirmation. The API itself never executes writes directly.

## Core Workflow

1. Make sure the SnowFox desktop app is running.
2. If it is not running, try the host environment's app-launch mechanism first.
3. Do not hardcode an install path. If no launch method is available, ask the user to open SnowFox manually.
4. Probe the local API before doing any inventory work.
5. If the API is unreachable, tell the user to open SnowFox Settings and check whether Local Open API is enabled and whether the port matches the one you are probing.
6. After the API is reachable, call `/api/v1/capabilities` before assuming field names or response keys.
7. Use `dataset_schema` from `/api/v1/capabilities` to learn the current GUI dataset fields, aliases, `display_key`, `color_key`, and `box_layout`.
8. Use `response_shapes` from `/api/v1/capabilities` before parsing `/api/v1/inventory/search` or `/api/v1/inventory/filter`.
9. Call `/api/v1/session` to learn which dataset is currently open in the GUI.
10. If the user needs another managed dataset, call `/api/v1/datasets`, choose the target dataset, then call `/api/v1/session/switch-dataset`.
11. Prefer read/query endpoints first. Use GUI handoff endpoints when the user wants the SnowFox window prepared for a human to review or execute.
12. Treat staged plan items as GUI staging only. They are not executed writes.

## Connection Checklist

- Probe loopback only: `http://127.0.0.1:<port>`
- The API listens only on the loopback of the host running SnowFox. If you run on a different machine (e.g. managing the host over SSH), set up SSH local port forwarding first (`ssh -L 37666:127.0.0.1:37666 <host>`) or execute the probe/request commands on the host itself; never ask the user to bind the port to a non-loopback address.
- Default first guess: `37666`
- First probe: `GET /api/v1/health`
- Capability probe: `GET /api/v1/capabilities`
- Session probe: `GET /api/v1/session`
- Read `dataset_schema` and `response_shapes` before assuming field names or response keys.
- If the app responds but `dataset_exists` is `false`, tell the user the current GUI session has no valid open dataset yet.

## API Reference

{{LOCAL_OPEN_API_ROUTE_REFERENCE}}

## Staging Writes (stage-plan) Notes

- `POST /api/v1/gui/stage-plan` is the only write-shaped handoff: items only enter the GUI staging area and still require human confirmation in the GUI.
- `mode` defaults to `merge` (merged into the existing staged plan); `replace` first clears ALL currently staged items, including ones staged by other sources. Before re-sending a correction, `GET /api/v1/gui/stage-plan` to see the current state; to wipe everything intentionally use `POST /api/v1/gui/stage-plan/clear`, not `replace` as a side effect.
- Payload shapes differ per action: `edit` wraps changes under `payload.fields`; `takeout`/`move` use flat keys. Treat `stage_plan_schema` from `/api/v1/capabilities` as the source of truth.
- `edit` requires `record_id` to point at a record that actually exists in the current dataset (preflight rejects otherwise); `edit` does NOT need `box`/`position` — the server fills defaults.
- POST bodies containing non-ASCII text must be sent as UTF-8 bytes. Windows PowerShell 5.1 re-encodes string `-Body` values with the system codepage, turning non-ASCII characters into `?`; convert first: `-Body ([System.Text.Encoding]::UTF8.GetBytes($body))`.

Minimal example (one edit plus one takeout):

```json
{"items": [
  {"action": "edit", "record_id": 7,
   "payload": {"fields": {"note": "thawed one vial"}}},
  {"action": "takeout", "record_id": 7, "box": 1, "position": 5,
   "payload": {"date_str": "2026-02-10"}}
]}
```

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
  - `GET /api/v1/gui/stage-plan` first to inspect what is already staged, fix the rejected items, and re-send with `merge`; do not reach for `mode: replace` as a shortcut

## Non-Negotiables

- Do not describe this API as direct write access.
- Do not assume any install path for SnowFox.
- Do not bypass the GUI session boundary.
- Do not describe managed dataset switching as background file access.
- Do not tell the user that staging equals execution.
- When the API is unavailable, explicitly guide the user to SnowFox Settings -> Local Open API.
