"""Terminal command helper for AgentToolRunner."""

import os
from pathlib import Path
import shutil
import subprocess


DEFAULT_TERMINAL_TIMEOUT_SECONDS = 120
SHELL_ENGINE_BASH = "bash"
SHELL_ENGINE_POWERSHELL = "powershell"
SUPPORTED_SHELL_ENGINES = {SHELL_ENGINE_BASH, SHELL_ENGINE_POWERSHELL}


def default_terminal_cwd():
    repo_root = Path(__file__).resolve().parents[1]
    return str(repo_root)


def _default_terminal_cwd():
    return default_terminal_cwd()


def _resolve_effective_cwd(cwd=None):
    raw_cwd = str(cwd or "").strip()
    if not raw_cwd:
        return _default_terminal_cwd()

    candidate = Path(raw_cwd)
    if candidate.is_absolute():
        return str(candidate.resolve(strict=False))
    return str((Path(_default_terminal_cwd()) / candidate).resolve(strict=False))


def _child_process_env(extra_env=None):
    child_env = dict(os.environ)
    # Force UTF-8 for child Python processes to avoid GBK/UTF-8 decode mismatch on Windows.
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    if isinstance(extra_env, dict):
        for key, value in extra_env.items():
            name = str(key or "").strip()
            if not name:
                continue
            child_env[name] = str(value or "")
    return child_env


def _normalize_terminal_output(value):
    text = str(value or "")
    if not text:
        return ""
    # Some Windows subprocesses emit UTF-16-like streams that surface as NUL-padded text.
    text = text.replace("\x00", "")
    return text.lstrip("\ufeff")


def _resolve_shell_argv(engine, command_text):
    normalized_engine = str(engine or SHELL_ENGINE_BASH).strip().lower()
    if normalized_engine == SHELL_ENGINE_BASH:
        bash_path = shutil.which("bash")
        if not bash_path:
            return None, "bash_unavailable", "bash executable is not available in current runtime."
        return [bash_path, "-lc", command_text], "", ""

    if normalized_engine == SHELL_ENGINE_POWERSHELL:
        pwsh_path = shutil.which("powershell") or shutil.which("powershell.exe")
        if not pwsh_path:
            return None, "powershell_unavailable", "powershell executable is not available in current runtime."
        return [
            pwsh_path,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command_text,
        ], "", ""

    return None, "invalid_tool_input", "engine must be one of: bash, powershell."


def run_terminal_command(
    command,
    timeout_seconds=DEFAULT_TERMINAL_TIMEOUT_SECONDS,
    cwd=None,
    engine=SHELL_ENGINE_BASH,
    extra_env=None,
):
    """Execute one terminal command and return raw combined terminal output."""
    command_text = str(command or "")
    engine_name = str(engine or SHELL_ENGINE_BASH).strip().lower()
    effective_cwd = _resolve_effective_cwd(cwd)
    if not command_text.strip():
        return {
            "ok": False,
            "error_code": "invalid_tool_input",
            "message": "command must be a non-empty string.",
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }

    argv, error_code, error_message = _resolve_shell_argv(engine_name, command_text)
    if not argv:
        return {
            "ok": False,
            "error_code": error_code or "terminal_exec_failed",
            "message": error_message or "Shell engine is unavailable.",
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }

    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            cwd=effective_cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_child_process_env(extra_env=extra_env),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }

    try:
        raw_output, _ = process.communicate(timeout=float(timeout_seconds))
        normalized_output = _normalize_terminal_output(raw_output)
    except subprocess.TimeoutExpired:
        process.kill()
        raw_output, _ = process.communicate()
        normalized_output = _normalize_terminal_output(raw_output)
        return {
            "ok": False,
            "error_code": "terminal_timeout",
            "message": f"Terminal command timed out after {timeout_seconds} second(s).",
            "exit_code": -1,
            "raw_output": normalized_output,
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }
    except Exception as exc:
        process.kill()
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }

    exit_code = int(process.returncode if process.returncode is not None else -1)
    if exit_code != 0:
        return {
            "ok": False,
            "error_code": "terminal_nonzero_exit",
            "message": f"Terminal command exited with status {exit_code}.",
            "exit_code": exit_code,
            "raw_output": normalized_output,
            "effective_cwd": effective_cwd,
            "engine": engine_name,
        }

    return {
        "ok": True,
        "exit_code": exit_code,
        "raw_output": normalized_output,
        "effective_cwd": effective_cwd,
        "engine": engine_name,
    }
