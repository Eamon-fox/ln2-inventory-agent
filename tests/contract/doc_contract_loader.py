"""Helpers for loading machine-readable contract blocks from Markdown docs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class DocContractError(ValueError):
    """Raised when a Markdown contract block is missing or malformed."""


_CONTRACT_BLOCK_RE = re.compile(
    r"<!--\s*contract:(?P<name>[a-zA-Z0-9_-]+)\s*-->\s*"
    r"```yaml\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse_contract_blocks(path: Path) -> dict[str, object]:
    """Parse all named YAML contract blocks from one Markdown file."""
    text = _read_text(path)
    matches = list(_CONTRACT_BLOCK_RE.finditer(text))
    blocks: dict[str, object] = {}
    for match in matches:
        name = str(match.group("name") or "").strip()
        body = str(match.group("body") or "")
        if name in blocks:
            raise DocContractError(f"Duplicate contract block '{name}' in {path}")
        try:
            blocks[name] = yaml.safe_load(body)
        except Exception as exc:  # pragma: no cover - defensive parse guard
            raise DocContractError(f"Failed to parse contract block '{name}' in {path}: {exc}") from exc
    return blocks


def load_contract_block(path: Path, name: str):
    """Load one named contract block from Markdown and return parsed YAML."""
    blocks = parse_contract_blocks(path)
    if name not in blocks:
        raise DocContractError(f"Missing contract block '{name}' in {path}")
    return blocks[name]
