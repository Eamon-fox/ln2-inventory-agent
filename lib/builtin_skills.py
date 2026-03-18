"""Built-in skill catalog and loader helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Dict, List

import yaml

from .inventory_paths import get_install_dir


_SKILL_FRONTMATTER_RE = re.compile(r"(?s)^---\s*\n(.*?)\n---\s*\n?(.*)$")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESOURCE_DIR_NAMES = ("references", "scripts", "assets")


class BuiltinSkillError(ValueError):
    """Raised when built-in skill metadata or lookup is invalid."""

    def __init__(self, code: str, message: str, *, details: Dict[str, object] | None = None):
        super().__init__(str(message))
        self.code = str(code or "builtin_skill_error")
        self.message = str(message or "Built-in skill error")
        self.details = dict(details or {})


@dataclass(frozen=True)
class BuiltinSkill:
    """One built-in skill loaded from SKILL.md."""

    name: str
    description: str
    body: str
    skill_root: Path
    skill_file: Path


def _candidate_skill_roots() -> List[Path]:
    install_root = Path(get_install_dir()).resolve(strict=False)
    candidates = [
        install_root / "agent_skills",
        install_root / "_internal" / "agent_skills",
        install_root.parent / "Resources" / "agent_skills",
        install_root.parent / "Frameworks" / "agent_skills",
    ]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(str(meipass)) / "agent_skills")

    roots: List[Path] = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _split_frontmatter(text: str, *, path: Path) -> tuple[Dict[str, object], str]:
    match = _SKILL_FRONTMATTER_RE.match(str(text or ""))
    if not match:
        raise BuiltinSkillError(
            "invalid_skill_frontmatter",
            f"Skill file is missing YAML frontmatter: {path}",
        )

    raw_frontmatter = str(match.group(1) or "")
    body = str(match.group(2) or "").strip()
    try:
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
    except Exception as exc:
        raise BuiltinSkillError(
            "invalid_skill_frontmatter",
            f"Skill frontmatter is invalid YAML: {path} ({exc})",
        ) from exc

    if not isinstance(frontmatter, dict):
        raise BuiltinSkillError(
            "invalid_skill_frontmatter",
            f"Skill frontmatter must be an object: {path}",
        )
    return dict(frontmatter), body


def _load_skill_file(path: Path) -> BuiltinSkill:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise BuiltinSkillError(
            "skill_read_failed",
            f"Failed to read skill file: {path} ({exc})",
        ) from exc

    frontmatter, body = _split_frontmatter(text, path=path)
    name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not _SKILL_NAME_RE.fullmatch(name):
        raise BuiltinSkillError(
            "invalid_skill_name",
            f"Skill name must match {_SKILL_NAME_RE.pattern}: {path}",
        )
    if not description:
        raise BuiltinSkillError(
            "missing_skill_description",
            f"Skill description is required: {path}",
        )

    return BuiltinSkill(
        name=name,
        description=description,
        body=body,
        skill_root=path.parent,
        skill_file=path,
    )


def _display_path(path: Path) -> str:
    target = path.resolve(strict=False)
    install_root = Path(get_install_dir()).resolve(strict=False)
    try:
        return target.relative_to(install_root).as_posix()
    except Exception:
        return target.as_posix()


def _list_resource_paths(skill_root: Path, resource_dir_name: str) -> List[str]:
    root = skill_root / resource_dir_name
    if not root.is_dir():
        return []
    entries: List[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append(_display_path(path))
    return entries


def list_builtin_skills() -> List[Dict[str, str]]:
    """Return built-in skill metadata sorted by skill name."""
    rows: List[Dict[str, str]] = []
    seen_names = set()

    for skills_root in _candidate_skill_roots():
        if not skills_root.is_dir():
            continue
        for skill_root in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            skill_file = skill_root / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill = _load_skill_file(skill_file)
            if skill.name in seen_names:
                continue
            seen_names.add(skill.name)
            rows.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                }
            )

    rows.sort(key=lambda item: str(item.get("name") or ""))
    return rows


def load_builtin_skill(skill_name: str) -> Dict[str, object]:
    """Load one built-in skill by frontmatter name."""
    requested = str(skill_name or "").strip().lower()
    if not requested:
        raise BuiltinSkillError(
            "invalid_skill_name",
            "skill_name must be a non-empty string.",
        )

    available: List[str] = []
    for skills_root in _candidate_skill_roots():
        if not skills_root.is_dir():
            continue
        for skill_root in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            skill_file = skill_root / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill = _load_skill_file(skill_file)
            available.append(skill.name)
            if skill.name != requested:
                continue

            payload: Dict[str, object] = {
                "name": skill.name,
                "description": skill.description,
                "instructions_markdown": skill.body,
                "references": _list_resource_paths(skill.skill_root, "references"),
                "scripts": _list_resource_paths(skill.skill_root, "scripts"),
                "assets": _list_resource_paths(skill.skill_root, "assets"),
            }
            shared_root = skill.skill_root.parent / "shared"
            if shared_root.is_dir():
                payload["shared_references"] = _list_resource_paths(shared_root, "references")
            return payload

    raise BuiltinSkillError(
        "unknown_skill",
        f"Unknown built-in skill: {requested}",
        details={"available_skills": sorted(set(available))},
    )


def build_skill_catalog_prompt() -> str:
    """Return a compact system-prompt block listing available skills."""
    skills = list_builtin_skills()
    if not skills:
        return ""

    lines = [
        "Built-in skills are available via the `use_skill` tool.",
        "When a request clearly matches one of the skills below, call `use_skill` with the exact skill name before following that skill's workflow.",
        "Do not silently assume a skill is loaded until `use_skill` returns its instructions.",
        "Available built-in skills:",
    ]
    for item in skills:
        lines.append(f"- `{item['name']}`: {item['description']}")
    return "\n".join(lines)
