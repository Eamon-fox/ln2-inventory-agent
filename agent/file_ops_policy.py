"""Path policy helpers for isolated file-operation tools."""

from lib.path_policy import (
    PathPolicyError,
    normalize_repo_roots,
    resolve_repo_read_path,
    resolve_repo_workdir_path,
    resolve_repo_write_path,
)


class FileOpsPolicyError(ValueError):
    """Raised when a file-operation request violates policy."""

    def __init__(self, code, message, *, resolved_path=None, details=None):
        super().__init__(str(message))
        self.code = str(code)
        self.message = str(message)
        self.resolved_path = str(resolved_path) if resolved_path else ""
        self.details = dict(details or {})


def _convert_policy_error(exc):
    if isinstance(exc, PathPolicyError):
        return FileOpsPolicyError(
            exc.code,
            exc.message,
            resolved_path=exc.resolved_path,
            details=exc.details,
        )
    return exc


def normalize_roots(repo_root, migrate_root=None):
    """Normalize and validate repo/migrate roots."""

    try:
        return normalize_repo_roots(repo_root, migrate_root)
    except Exception as exc:  # pragma: no cover - tiny adapter
        raise _convert_policy_error(exc)


def resolve_read_path(repo_root, path_value, *, default_rel="."):
    """Resolve a read path under repo scope."""

    try:
        return resolve_repo_read_path(repo_root, path_value, default_rel=default_rel)
    except Exception as exc:  # pragma: no cover - tiny adapter
        raise _convert_policy_error(exc)


def resolve_write_path(repo_root, migrate_root, path_value, *, default_rel="."):
    """Resolve a write path that must remain inside migrate root."""

    try:
        return resolve_repo_write_path(repo_root, migrate_root, path_value, default_rel=default_rel)
    except Exception as exc:  # pragma: no cover - tiny adapter
        raise _convert_policy_error(exc)


def resolve_shell_workdir(repo_root, migrate_root, workdir_value):
    """Resolve shell working directory; it must stay inside migrate root."""

    try:
        return resolve_repo_workdir_path(repo_root, migrate_root, workdir_value, default_rel="migrate")
    except Exception as exc:  # pragma: no cover - tiny adapter
        raise _convert_policy_error(exc)
