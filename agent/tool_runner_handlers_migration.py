"""Migration and skill dispatch handlers for AgentToolRunner."""

import os
import re
from contextlib import suppress

from lib.import_acceptance import import_validated_yaml, validate_candidate_yaml
from lib.inventory_paths import create_managed_dataset_yaml_path
from lib.builtin_skills import BuiltinSkillError, load_builtin_skill
from lib.path_policy import resolve_repo_read_path
from lib.validate_service import validate_yaml_file
from .tool_runtime_paths import derive_migration_output_yaml_from_yaml, derive_repo_root_from_yaml


_IMPORT_CONFIRMATION_TOKEN = "CONFIRM_IMPORT"
_TARGET_DATASET_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _run_use_skill(self, payload, _trace_id=None):
    tool_name = "use_skill"

    def _call_use_skill():
        skill_name = str(payload.get("skill_name") or "").strip()
        try:
            loaded = load_builtin_skill(skill_name)
        except BuiltinSkillError as exc:
            response = {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
            }
            available = list((exc.details or {}).get("available_skills") or [])
            if available:
                response["available_skills"] = available
            return response

        return {
            "ok": True,
            "skill_name": str(loaded.get("name") or skill_name),
            "description": str(loaded.get("description") or ""),
            "instructions_markdown": str(loaded.get("instructions_markdown") or ""),
            "references": list(loaded.get("references") or []),
            "reference_documents": list(loaded.get("reference_documents") or []),
            "shared_references": list(loaded.get("shared_references") or []),
            "shared_reference_documents": list(loaded.get("shared_reference_documents") or []),
            "scripts": list(loaded.get("scripts") or []),
            "assets": list(loaded.get("assets") or []),
        }

    return self._safe_call(tool_name, _call_use_skill, include_expected_schema=True)


def _migration_output_yaml_path(yaml_path):
    return str(derive_migration_output_yaml_from_yaml(yaml_path))


def _build_import_target_path(dataset_name):
    return create_managed_dataset_yaml_path(dataset_name)


def _run_validate(self, payload, _trace_id=None):
    tool_name = "validate"

    def _call_validate():
        repo_root = str(derive_repo_root_from_yaml(self._yaml_path))
        resolved = resolve_repo_read_path(repo_root, payload.get("path"), default_rel=".")
        if os.path.isdir(resolved):
            return {
                "ok": False,
                "error_code": "path_is_directory",
                "message": f"Path is a directory: {resolved}",
                "effective_root": repo_root,
                "resolved_path": str(resolved),
            }
        result = dict(validate_yaml_file(str(resolved)) or {})
        result["effective_root"] = repo_root
        result["resolved_path"] = str(resolved)
        return result

    return self._safe_call(
        tool_name,
        _call_validate,
        include_expected_schema=True,
    )


def _run_import_migration_output(self, payload, _trace_id=None):
    tool_name = "import_migration_output"

    def _call_import_migration_output():
        token = str(payload.get("confirmation_token") or "").strip()
        if token != _IMPORT_CONFIRMATION_TOKEN:
            return {
                "ok": False,
                "error_code": "invalid_confirmation_token",
                "message": f"confirmation_token must be exactly {_IMPORT_CONFIRMATION_TOKEN}.",
            }

        dataset_name = str(payload.get("target_dataset_name") or "").strip()
        if not dataset_name:
            return {
                "ok": False,
                "error_code": "invalid_target_dataset_name",
                "message": "target_dataset_name must be a non-empty string.",
            }
        if not _TARGET_DATASET_NAME_RE.fullmatch(dataset_name):
            return {
                "ok": False,
                "error_code": "invalid_target_dataset_name",
                "message": "target_dataset_name must match ^[A-Za-z0-9_-]+$.",
                "details": {"target_dataset_name": dataset_name},
            }

        candidate = _migration_output_yaml_path(self._yaml_path)
        validation = validate_candidate_yaml(candidate, fail_on_warnings=True)
        if not validation.get("ok"):
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": str(validation.get("message") or "Candidate YAML failed validation."),
                "report": validation.get("report") or {},
            }

        target_path = _build_import_target_path(dataset_name)
        result = import_validated_yaml(
            candidate,
            target_path,
            mode="create_new",
            overwrite=False,
        )
        if result.get("ok"):
            return result

        with suppress(Exception):
            dataset_dir = os.path.dirname(target_path)
            if dataset_dir and os.path.isdir(dataset_dir) and not os.path.exists(target_path):
                os.rmdir(dataset_dir)
        return result

    return self._safe_call(tool_name, _call_import_migration_output, include_expected_schema=True)
