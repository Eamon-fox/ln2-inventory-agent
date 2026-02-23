"""Reusable path policy helpers for repository and dataset scopes.

These helpers centralize path normalization + scope validation so callers can
enforce "resolve first, then verify boundary" consistently.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .inventory_paths import assert_allowed_inventory_yaml_path


class PathPolicyError(ValueError):
    """Raised when a path violates security or scope policy."""

    def __init__(self, code: str, message: str, *, resolved_path: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(str(message))
        self.code = str(code)
        self.message = str(message)
        self.resolved_path = str(resolved_path or "")
        self.details = dict(details or {})


@dataclass(frozen=True)
class PathPolicyContext:
    """Resolved roots used by file-operation path policies."""

    repo_root: Path
    migrate_root: Path
    dataset_root: Optional[Path] = None
    backups_root: Optional[Path] = None
    audit_root: Optional[Path] = None


def _require_text(value: Any, *, field_name: str, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PathPolicyError(code, f"{field_name} is required.")
    return text


def _as_resolved_path(value: Any, *, field_name: str, code: str) -> Path:
    text = _require_text(value, field_name=field_name, code=code)
    return Path(text).resolve(strict=False)


def _assert_under_root(path: Path, root: Path, *, code: str, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PathPolicyError(
            code,
            message,
            resolved_path=str(path),
            details={"root": str(root)},
        ) from exc


def normalize_repo_roots(repo_root: Any, migrate_root: Any = None) -> Tuple[Path, Path]:
    """Normalize repo/migrate roots and verify migrate is under repo."""

    repo = _as_resolved_path(repo_root, field_name="repo_root", code="path.policy_invalid")
    migrate_source = migrate_root if migrate_root not in (None, "") else (repo / "migrate")
    migrate = _as_resolved_path(migrate_source, field_name="migrate_root", code="path.policy_invalid")
    _assert_under_root(
        migrate,
        repo,
        code="path.policy_invalid",
        message="migrate_root must stay within repo_root.",
    )
    return repo, migrate


def resolve_under_root(
    root: Any,
    raw_path: Any,
    *,
    default_rel: str = ".",
    allow_absolute: bool = False,
) -> Path:
    """Resolve input path and enforce that final path stays under root."""

    root_path = _as_resolved_path(root, field_name="root", code="path.policy_invalid")
    text = str(raw_path if raw_path not in (None, "") else default_rel).strip()
    if not text:
        text = str(default_rel or ".")
    candidate = Path(text)

    if candidate.is_absolute() and not allow_absolute:
        raise PathPolicyError(
            "path.absolute_not_allowed",
            "Path must be repository-relative (absolute paths are not allowed).",
            resolved_path=str(candidate.resolve(strict=False)),
        )

    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (root_path / candidate).resolve(strict=False)
    _assert_under_root(
        resolved,
        root_path,
        code="path.escape_detected",
        message="Path escapes allowed scope.",
    )
    return resolved


def resolve_repo_read_path(repo_root: Any, raw_path: Any, *, default_rel: str = ".") -> Path:
    """Resolve a read path under repo root."""

    return resolve_under_root(repo_root, raw_path, default_rel=default_rel, allow_absolute=False)


def resolve_repo_write_path(repo_root: Any, migrate_root: Any, raw_path: Any, *, default_rel: str = "migrate") -> Path:
    """Resolve a write path under repo root and restrict writes to migrate root."""

    repo, migrate = normalize_repo_roots(repo_root, migrate_root)
    resolved = resolve_under_root(repo, raw_path, default_rel=default_rel, allow_absolute=False)
    _assert_under_root(
        resolved,
        migrate,
        code="path.scope_write_denied",
        message="Write operations are allowed only under migrate/.",
    )
    return resolved


def resolve_repo_workdir_path(repo_root: Any, migrate_root: Any, raw_path: Any, *, default_rel: str = "migrate") -> Path:
    """Resolve shell workdir and restrict it to migrate root."""

    repo, migrate = normalize_repo_roots(repo_root, migrate_root)
    if raw_path in (None, ""):
        return migrate
    resolved = resolve_under_root(repo, raw_path, default_rel=default_rel, allow_absolute=False)
    _assert_under_root(
        resolved,
        migrate,
        code="path.scope_workdir_denied",
        message="workdir must stay under migrate/.",
    )
    return resolved


def _backup_root_for_yaml(yaml_path: Any) -> Path:
    managed_yaml = assert_allowed_inventory_yaml_path(yaml_path, must_exist=False)
    return (Path(managed_yaml).resolve(strict=False).parent / "backups").resolve(strict=False)


def resolve_dataset_backup_request_path(yaml_path: Any, raw_path: Any, *, allow_empty: bool = True) -> Optional[Path]:
    """Resolve request backup path and require it to stay in dataset backups/."""

    text = str(raw_path or "").strip()
    if not text:
        if allow_empty:
            return None
        raise PathPolicyError(
            "path.invalid_input",
            "request_backup_path must be a non-empty string.",
        )

    backups_root = _backup_root_for_yaml(yaml_path)
    candidate = Path(text)
    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (backups_root / candidate).resolve(strict=False)
    _assert_under_root(
        resolved,
        backups_root,
        code="path.backup_scope_denied",
        message="Backup path must stay under dataset backups/.",
    )
    return resolved


def resolve_dataset_backup_read_path(yaml_path: Any, raw_path: Any, *, must_exist: bool = True, must_be_file: bool = True) -> Path:
    """Resolve rollback backup path and enforce existence/type checks."""

    resolved = resolve_dataset_backup_request_path(yaml_path, raw_path, allow_empty=False)
    if resolved is None:
        raise PathPolicyError(
            "path.invalid_input",
            "backup_path must be a non-empty string.",
        )

    if must_exist and not resolved.exists():
        raise PathPolicyError(
            "path.not_found",
            f"Path not found: {resolved}",
            resolved_path=str(resolved),
        )
    if must_be_file and resolved.exists() and not resolved.is_file():
        raise PathPolicyError(
            "path.not_file",
            f"Path is not a file: {resolved}",
            resolved_path=str(resolved),
        )
    return resolved
