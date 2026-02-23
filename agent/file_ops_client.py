"""Client helpers for calling isolated file-operation service."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SERVICE_TIMEOUT_SECONDS = 120.0


def _derive_repo_root_from_yaml(yaml_path):
    inventory_path = Path(str(yaml_path or "")).resolve(strict=False)
    if inventory_path.name.lower() != "inventory.yaml":
        raise ValueError("yaml_path must end with inventory.yaml")
    try:
        return inventory_path.parents[2]
    except IndexError as exc:
        raise ValueError("yaml_path does not follow managed inventories layout.") from exc


def _derive_migrate_root(repo_root):
    return (Path(repo_root) / "migrate").resolve(strict=False)


def _service_timeout_seconds(tool_name, args):
    if str(tool_name or "").strip() not in {"bash", "powershell"}:
        return DEFAULT_SERVICE_TIMEOUT_SECONDS
    timeout_value = (args or {}).get("timeout")
    if timeout_value in (None, ""):
        return DEFAULT_SERVICE_TIMEOUT_SECONDS
    try:
        timeout_ms = float(timeout_value)
    except Exception:
        return DEFAULT_SERVICE_TIMEOUT_SECONDS
    if timeout_ms <= 0:
        return DEFAULT_SERVICE_TIMEOUT_SECONDS
    return max(30.0, (timeout_ms / 1000.0) + 15.0)


def _service_environment():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_file_tool(tool_name, args, *, yaml_path):
    """Execute a file tool via isolated subprocess service."""
    repo_root = _derive_repo_root_from_yaml(yaml_path)
    migrate_root = _derive_migrate_root(repo_root)
    payload = {
        "tool": str(tool_name or "").strip(),
        "args": dict(args or {}),
        "repo_root": str(repo_root),
        "migrate_root": str(migrate_root),
    }

    project_root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "agent.file_ops_service"]
    timeout_seconds = _service_timeout_seconds(tool_name, payload.get("args") or {})

    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=_service_environment(),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error_code": "file_ops_service_timeout",
            "message": "File operation service timed out.",
            "effective_root": str(repo_root),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "file_ops_service_failed",
            "message": str(exc),
            "effective_root": str(repo_root),
        }

    if int(proc.returncode) != 0:
        stderr_text = str(proc.stderr or "").strip()
        stdout_text = str(proc.stdout or "").strip()
        detail = stderr_text or stdout_text or f"service exited with status {proc.returncode}"
        return {
            "ok": False,
            "error_code": "file_ops_service_failed",
            "message": detail,
            "effective_root": str(repo_root),
            "raw_output": stdout_text or stderr_text,
        }

    raw_stdout = str(proc.stdout or "").strip()
    try:
        response = json.loads(raw_stdout or "{}")
    except Exception:
        return {
            "ok": False,
            "error_code": "file_ops_invalid_response",
            "message": "File operation service returned non-JSON response.",
            "effective_root": str(repo_root),
            "raw_output": raw_stdout,
        }
    if not isinstance(response, dict):
        return {
            "ok": False,
            "error_code": "file_ops_invalid_response",
            "message": "File operation service returned non-object response.",
            "effective_root": str(repo_root),
        }
    if "effective_root" not in response:
        response = dict(response)
        response["effective_root"] = str(repo_root)
    return response
