"""Generic before/after hooks around AgentToolRunner tool calls."""

from __future__ import annotations

from pathlib import Path

from lib.tool_registry import TOOL_CONTRACTS

from .tool_runner_guidance import MIGRATION_SESSION_CHECKLIST, merge_hint_text


def _normalize_ui_effects(value):
    if not isinstance(value, list):
        return []
    effects = []
    for item in value:
        if isinstance(item, dict) and item:
            effects.append(dict(item))
    return effects


def _normalize_hook_result(value):
    if not isinstance(value, dict):
        return {}

    normalized = {}
    if value.get("blocked"):
        normalized["blocked"] = True

    message = str(value.get("message") or "").strip()
    if message:
        normalized["message"] = message

    payload_patch = value.get("payload_patch")
    if isinstance(payload_patch, dict) and payload_patch:
        normalized["payload_patch"] = dict(payload_patch)

    hint = str(value.get("_hint") or "").strip()
    if hint:
        normalized["_hint"] = hint

    ui_effects = _normalize_ui_effects(value.get("ui_effects"))
    if ui_effects:
        normalized["ui_effects"] = ui_effects

    return normalized


def apply_payload_patch(payload, hook_result):
    normalized = _normalize_hook_result(hook_result)
    patch = normalized.get("payload_patch")
    if not isinstance(patch, dict) or not patch:
        return dict(payload or {})
    merged = dict(payload or {})
    merged.update(patch)
    return merged


def merge_hook_result(response, hook_result):
    normalized = _normalize_hook_result(hook_result)
    if not normalized:
        return response

    if isinstance(response, dict):
        merged = dict(response)
    else:
        merged = {
            "ok": False,
            "error_code": "invalid_tool_response",
            "message": str(response or "Tool returned invalid response."),
        }

    if normalized.get("blocked"):
        merged["blocked"] = True
        merged["ok"] = False
        merged["error_code"] = str(merged.get("error_code") or "tool_hook_blocked")
        merged["message"] = str(
            normalized.get("message")
            or merged.get("message")
            or "Tool call blocked by hook."
        )
    elif normalized.get("message") and not str(merged.get("message") or "").strip():
        merged["message"] = normalized["message"]

    merged_hint = merge_hint_text(merged.get("_hint"), normalized.get("_hint"))
    if merged_hint:
        merged["_hint"] = merged_hint

    existing_effects = _normalize_ui_effects(merged.get("ui_effects"))
    merged_effects = existing_effects + list(normalized.get("ui_effects") or [])
    if merged_effects:
        merged["ui_effects"] = merged_effects

    return merged


def _merge_many(results):
    merged = {}
    hints = []
    ui_effects = []
    payload_patch = {}

    for raw in results:
        normalized = _normalize_hook_result(raw)
        if not normalized:
            continue
        if normalized.get("blocked"):
            merged["blocked"] = True
        if normalized.get("message"):
            merged["message"] = normalized["message"]
        if isinstance(normalized.get("payload_patch"), dict):
            payload_patch.update(normalized["payload_patch"])
        if normalized.get("_hint"):
            hints.append(normalized["_hint"])
        ui_effects.extend(list(normalized.get("ui_effects") or []))

    if payload_patch:
        merged["payload_patch"] = payload_patch
    merged_hint = merge_hint_text(*hints)
    if merged_hint:
        merged["_hint"] = merged_hint
    if ui_effects:
        merged["ui_effects"] = ui_effects
    return merged


def _matches_tool_pattern(pattern, tool_name):
    pattern_text = str(pattern or "").strip()
    name = str(tool_name or "").strip()
    if not pattern_text or not name:
        return False
    if pattern_text == "*":
        return True
    if pattern_text.endswith("*"):
        return name.startswith(pattern_text[:-1])
    return pattern_text == name


class ToolHookManager:
    """Register and execute before/after hooks around tool calls."""

    def __init__(self):
        self._before_hooks = []
        self._after_hooks = []

    def register(self, tool_pattern, *, before=None, after=None):
        pattern = str(tool_pattern or "").strip()
        if not pattern:
            raise ValueError("tool_pattern must be a non-empty string.")
        if before is not None and not callable(before):
            raise ValueError("before hook must be callable.")
        if after is not None and not callable(after):
            raise ValueError("after hook must be callable.")
        if callable(before):
            self._before_hooks.append((pattern, before))
        if callable(after):
            self._after_hooks.append((pattern, after))

    def run_before(self, tool_name, payload, context):
        matches = []
        for pattern, hook in list(self._before_hooks):
            if _matches_tool_pattern(pattern, tool_name):
                matches.append(hook(tool_name, dict(payload or {}), dict(context or {})))
        return _merge_many(matches)

    def run_after(self, tool_name, payload, result, context):
        matches = []
        for pattern, hook in list(self._after_hooks):
            if _matches_tool_pattern(pattern, tool_name):
                matches.append(
                    hook(
                        tool_name,
                        dict(payload or {}),
                        result if isinstance(result, dict) else result,
                        dict(context or {}),
                    )
                )
        return _merge_many(matches)

def _repo_relative_display(path_text, *, repo_root):
    path = str(path_text or "").strip()
    root = str(repo_root or "").strip()
    if not path:
        return ""
    if not root:
        return path
    try:
        relative = Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        return relative.as_posix()
    except Exception:
        return path.replace("\\", "/")


def _before_fs_list(_tool_name, payload, _context):
    if str(payload.get("path") or "").strip():
        return {}
    return {
        "payload_patch": {
            "path": ".",
        }
    }


def _normalize_migrate_relative_path(raw_path, *, repo_root=None, default_rel="migrate"):
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text or text == ".":
        return str(default_rel or "migrate")
    if Path(text).is_absolute():
        return text

    while text.startswith("./"):
        text = text[2:]
    if not text:
        return str(default_rel or "migrate")
    if text == "migrate" or text.startswith("migrate/"):
        return text
    if text.startswith("../") or "/../" in f"/{text}/":
        return text
    if "/" in text:
        top_level = text.split("/", 1)[0]
        if top_level and str(repo_root or "").strip():
            candidate = Path(str(repo_root)).resolve(strict=False) / top_level
            if candidate.exists():
                return text
    return f"migrate/{text}"


def _patch_payload_path_under_migrate(payload, context, *, field_name, default_rel=None):
    original = str(payload.get(field_name) or "").strip()
    if not original and default_rel is None:
        return {}
    normalized = _normalize_migrate_relative_path(
        original,
        repo_root=context.get("repo_root"),
        default_rel=(default_rel or "migrate"),
    )
    current = original.replace("\\", "/")
    if normalized == current:
        return {}
    return {"payload_patch": {field_name: normalized}}


def _before_fs_write(_tool_name, payload, context):
    return _patch_payload_path_under_migrate(payload, context, field_name="path")


def _before_fs_edit(_tool_name, payload, context):
    return _patch_payload_path_under_migrate(payload, context, field_name="filePath")


def _after_use_skill(_tool_name, payload, result, context):
    if not isinstance(result, dict) or not result.get("ok"):
        return {}

    requested = str(
        result.get("skill_name")
        or payload.get("skill_name")
        or ""
    ).strip().lower()
    if requested == "migration":
        return {
            "_hint": (
                "Migration workspace root: migrate/. Keep live progress in "
                f"`{MIGRATION_SESSION_CHECKLIST}`. Write candidate output to "
                "migrate/output/ln2_inventory.yaml, then run `validate` with that repo-relative path before import."
            ),
            "ui_effects": [
                {
                    "type": "migration_mode",
                    "enabled": True,
                    "reason": "use_skill:migration",
                }
            ],
        }

    if requested == "yaml-repair":
        yaml_path = str(context.get("yaml_path") or "").strip()
        return {
            "_hint": (
                "Current repair target: "
                f"{yaml_path or '(unknown inventory.yaml)'}. "
                "Treat this managed inventory as the source of truth and keep writes explicit."
            )
        }

    return {}


def _after_validate(_tool_name, _payload, result, context):
    if not isinstance(result, dict):
        return {}

    repo_root = str(result.get("effective_root") or context.get("repo_root") or "").strip()
    resolved_path = str(result.get("resolved_path") or "").strip()
    display_path = _repo_relative_display(resolved_path, repo_root=repo_root) or "(unknown path)"
    report = dict(result.get("report") or {})
    error_count = int(report.get("error_count") or 0)
    warning_count = int(report.get("warning_count") or 0)

    if result.get("ok"):
        if warning_count > 0:
            return {
                "_hint": (
                    f"Validation passed for `{display_path}` with {warning_count} warning(s). "
                    "Review warnings before any blocking workflow step."
                )
            }
        return {"_hint": f"Validation passed for `{display_path}`."}

    error_code = str(result.get("error_code") or "").strip()
    if error_code == "validation_failed":
        return {
            "_hint": (
                f"Validation failed for `{display_path}` "
                f"({error_count} error(s), {warning_count} warning(s)). "
                "Fix listed issues and run `validate` again."
            )
        }
    if error_code in {"file_not_found", "load_failed", "path_is_directory", "invalid_path"}:
        return {
            "_hint": (
                f"Validation target: `{display_path}`. "
                "Confirm the repo-relative YAML path and retry."
            )
        }
    return {}


def _after_paginated_read_tool(tool_name, _payload, result, _context):
    if not isinstance(result, dict) or not result.get("ok"):
        return {}

    result_payload = result.get("result")
    if not isinstance(result_payload, dict):
        return {}

    try:
        total_count = int(result_payload.get("total_count"))
        display_count = int(result_payload.get("display_count"))
    except (TypeError, ValueError):
        return {}

    if total_count <= 0 or display_count < 0 or display_count >= total_count:
        return {}

    tool_label = str(tool_name or "tool")
    return {
        "_hint": (
            f"{tool_label} results are truncated: showing {display_count} of {total_count} matches. "
            "Do not conclude a record is absent from this page alone. "
            "Rerun with a larger page size, or refine with more specific "
            "keywords / box / position / record_id from the user's clue."
        )
    }


def _after_search_records(_tool_name, _payload, result, _context):
    hooked = _after_paginated_read_tool("search_records", _payload, result, _context)
    if not hooked:
        return {}
    hint = str(hooked.get("_hint") or "").strip()
    if not hint:
        return hooked
    hooked["_hint"] = hint.replace(
        "Rerun with a larger page size",
        "Rerun `search_records` with a larger `max_results`",
    )
    return hooked


def _after_filter_records(_tool_name, _payload, result, _context):
    hooked = _after_paginated_read_tool("filter_records", _payload, result, _context)
    if not hooked:
        return {}
    hint = str(hooked.get("_hint") or "").strip()
    if not hint:
        return hooked
    hooked["_hint"] = hint.replace(
        "Rerun with a larger page size",
        "Rerun `filter_records` with a larger `limit`",
    )
    return hooked


def _fs_hint_paths(result, context):
    if not isinstance(result, dict):
        return None

    repo_root = str(result.get("effective_root") or context.get("repo_root") or "").strip()
    resolved_path = str(result.get("resolved_path") or "").strip()
    display_path = _repo_relative_display(resolved_path, repo_root=repo_root) or "."
    migrate_root = str(context.get("migrate_root") or "").strip()
    write_root = _repo_relative_display(migrate_root, repo_root=repo_root) or "migrate"
    return repo_root, display_path, write_root


def _repo_root_hint(repo_root, *, label, display_path):
    return {"_hint": f"Repository root: {repo_root or '(unknown)'}. {label}: {display_path}."}


def _write_root_hint(write_root, *, label, display_path):
    return {"_hint": f"Writable workspace root: {write_root}. {label}: {display_path}."}


def _after_fs_list(_tool_name, _payload, result, context):
    paths = _fs_hint_paths(result, context)
    if paths is None:
        return {}
    repo_root, display_path, _write_root = paths
    return _repo_root_hint(repo_root, label="Last listed path", display_path=display_path)


def _after_fs_read(_tool_name, _payload, result, context):
    paths = _fs_hint_paths(result, context)
    if paths is None:
        return {}
    repo_root, display_path, _write_root = paths
    return _repo_root_hint(repo_root, label="Last read path", display_path=display_path)


def _after_fs_write(_tool_name, _payload, result, context):
    paths = _fs_hint_paths(result, context)
    if paths is None:
        return {}
    _repo_root, display_path, write_root = paths
    return _write_root_hint(write_root, label="Last write target", display_path=display_path)


def _after_fs_edit(_tool_name, _payload, result, context):
    paths = _fs_hint_paths(result, context)
    if paths is None:
        return {}
    _repo_root, display_path, write_root = paths
    return _write_root_hint(write_root, label="Last edited file", display_path=display_path)


def _after_shell(tool_name, _payload, result, context):
    if not isinstance(result, dict):
        return {}

    repo_root = str(result.get("effective_root") or context.get("repo_root") or "").strip()
    resolved_path = str(
        result.get("resolved_path")
        or result.get("effective_cwd")
        or ""
    ).strip()
    display_path = _repo_relative_display(resolved_path, repo_root=repo_root) or "."
    if display_path == ".":
        display_path = "repo root"
    migrate_root = str(context.get("migrate_root") or "").strip()
    write_root = _repo_relative_display(migrate_root, repo_root=repo_root) or "migrate"
    return {
        "_hint": (
            f"Shell engine: {tool_name}. "
            f"Current working directory: {display_path}. "
            f"Writable workspace root: {write_root}."
        )
    }


def _after_import_migration_output(_tool_name, _payload, result, _context):
    if not isinstance(result, dict) or not result.get("ok"):
        return {}

    target_path = str(result.get("target_path") or "").strip()
    if not target_path:
        return {}

    return {
        "_hint": f"Imported dataset path: {target_path}.",
        "ui_effects": [
            {
                "type": "open_dataset",
                "target_path": target_path,
            },
            {
                "type": "migration_mode",
                "enabled": False,
                "reason": "import_migration_output",
            },
        ],
    }

def build_default_tool_hook_manager(runtime_specs):
    specs = dict(runtime_specs or {})
    invalid = sorted(name for name in specs if name not in TOOL_CONTRACTS)
    if invalid:
        raise ValueError(f"Runtime hook specs reference unknown tools: {invalid}")
    manager = ToolHookManager()
    for tool_name, spec in specs.items():
        before = getattr(spec, "before_hook", None)
        after = getattr(spec, "after_hook", None)
        if callable(before) or callable(after):
            manager.register(tool_name, before=before, after=after)
    return manager
