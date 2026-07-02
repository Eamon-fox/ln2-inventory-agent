"""
Module: test_agent_tool_runner
Layer: integration/agent
Covers: agent/tool_runner.py

工具分发、验证与处理器行为
"""

import ast
import json
import sys
import tempfile
import threading
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from lib.app_storage import ensure_data_root_layout, set_session_data_root
from lib.tool_api_write_validation import resolve_request_backup_path
from lib.yaml_ops import create_yaml_backup, get_audit_log_path, load_yaml, read_audit_events, write_yaml
from tests.managed_paths import ManagedPathTestCase


def _collect_agent_tool_runner_i18n_keys():
    source = (ROOT / "agent" / "tool_runner.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    keys = set()

    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_msg"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)

    return keys


def _flatten_leaf_keys(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix} if prefix else set()

    flattened = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened |= _flatten_leaf_keys(value, path)
        else:
            flattened.add(path)
    return flattened


def make_record(rec_id=1, box=1, position=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def make_data_alphanumeric(records):
    data = make_data(records)
    data["meta"]["box_layout"]["indexing"] = "alphanumeric"
    return data


class AgentToolRunnerBaseCase(ManagedPathTestCase):
    def _repo_root(self):
        return Path(self.fake_yaml_path).resolve().parents[2]

    def _migration_output_path(self):
        repo_root = self._repo_root()
        output_dir = repo_root / "migrate" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / "ln2_inventory.yaml"

    def _repo_relative_path(self, path_value):
        return Path(path_value).resolve().relative_to(self._repo_root()).as_posix()

__all__ = [name for name in dir() if not name.startswith("__")]
