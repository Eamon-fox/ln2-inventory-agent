"""Application use case for settings-dialog inventory validation."""

from typing import Any, Dict

from lib.import_acceptance import validate_candidate_yaml
from lib.validate_service import VALIDATION_MODE_META_ONLY, validate_yaml_file
from lib.validators import format_validation_errors


class SettingsValidationUseCase:
    """Coordinate settings dialog validation rules for dataset selection."""

    @staticmethod
    def _validation_failed_result(errors, *, warnings=None, prefix="Validation failed") -> Dict[str, Any]:
        normalized_errors = list(errors or [])
        normalized_warnings = list(warnings or [])
        return {
            "ok": False,
            "error_code": "validation_failed",
            "message": format_validation_errors(normalized_errors, prefix=prefix),
            "report": {
                "error_count": len(normalized_errors),
                "warning_count": len(normalized_warnings),
                "errors": normalized_errors,
                "warnings": normalized_warnings,
            },
        }

    @classmethod
    def _rewrite_validation_failure_prefix(cls, result, *, prefix) -> Dict[str, Any]:
        normalized = dict(result or {})
        if normalized.get("ok"):
            return normalized
        if str(normalized.get("error_code") or "") != "validation_failed":
            return normalized
        report = dict(normalized.get("report") or {})
        return cls._validation_failed_result(
            report.get("errors") or [],
            warnings=report.get("warnings") or [],
            prefix=prefix,
        )

    def validate_yaml_meta_only(self, *, yaml_path: str) -> Dict[str, Any]:
        result = validate_yaml_file(
            yaml_path,
            mode=VALIDATION_MODE_META_ONLY,
        )
        return self._rewrite_validation_failure_prefix(
            result,
            prefix="Validation failed",
        )

    def validate_yaml_for_settings_accept(
        self,
        *,
        yaml_path: str,
        initial_yaml_path: str,
    ) -> Dict[str, Any]:
        if str(yaml_path or "") != str(initial_yaml_path or ""):
            return validate_candidate_yaml(yaml_path, fail_on_warnings=True)
        return self.validate_yaml_meta_only(yaml_path=yaml_path)
