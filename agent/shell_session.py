"""Session-scoped shell working directory state."""

from __future__ import annotations

from pathlib import Path


class ShellSessionState:
    """Track the agent shell cwd as a repo-relative path."""

    def __init__(self, current_workdir="."):
        self.current_workdir = _normalize_repo_relative(current_workdir)

    def resolve_workdir(self, repo_root, requested_workdir=None):
        raw = str(requested_workdir or "").strip()
        return _normalize_repo_relative(raw or self.current_workdir)

    def update_from_absolute(self, repo_root, absolute_cwd):
        rel = repo_relative_workdir(repo_root, absolute_cwd)
        self.current_workdir = rel
        return rel

    def reset(self):
        self.current_workdir = "."


def repo_relative_workdir(repo_root, absolute_path):
    root = Path(str(repo_root or "")).resolve(strict=False)
    path = Path(str(absolute_path or "")).resolve(strict=False)
    try:
        rel = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("workdir_out_of_scope") from exc
    return _normalize_repo_relative(str(rel))


def _normalize_repo_relative(value):
    text = str(value or "").strip().replace("\\", "/")
    if not text or text == ".":
        return "."
    return text.strip("/") or "."
