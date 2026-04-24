"""Terminal command helper for AgentToolRunner."""

import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile


DEFAULT_TERMINAL_TIMEOUT_SECONDS = 120
SHELL_ENGINE_BASH = "bash"
SHELL_ENGINE_POWERSHELL = "powershell"
SHELL_ENGINE_AUTO = "auto"
SUPPORTED_SHELL_ENGINES = {SHELL_ENGINE_AUTO, SHELL_ENGINE_BASH, SHELL_ENGINE_POWERSHELL}


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


def _resolve_auto_engine():
    is_windows = platform.system().lower().startswith("win")
    has_powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if is_windows and has_powershell:
        return SHELL_ENGINE_POWERSHELL
    if shutil.which("bash"):
        return SHELL_ENGINE_BASH
    if has_powershell:
        return SHELL_ENGINE_POWERSHELL
    return SHELL_ENGINE_BASH


def _append_cwd_capture(command_text, engine, cwd_file):
    if not cwd_file:
        return command_text
    if engine == SHELL_ENGINE_POWERSHELL:
        escaped = str(cwd_file).replace("'", "''")
        return (
            "try {\n"
            f"{command_text}\n"
            "} finally {\n"
            f"  $pwd.Path | Set-Content -LiteralPath '{escaped}' -Encoding UTF8\n"
            "}\n"
            "if ($global:LASTEXITCODE -ne $null) { exit $global:LASTEXITCODE }"
        )
    escaped = shlex.quote(str(cwd_file))
    return (
        f"SNOWFOX_CWD_CAPTURE={escaped}\n"
        "export SNOWFOX_CWD_CAPTURE\n"
        "trap 'printf \"%s\\n\" \"$PWD\" > \"$SNOWFOX_CWD_CAPTURE\"' EXIT\n"
        f"{command_text}"
    )


def _resolve_shell_argv(engine, command_text):
    normalized_engine = str(engine or SHELL_ENGINE_AUTO).strip().lower()
    if normalized_engine == SHELL_ENGINE_AUTO:
        normalized_engine = _resolve_auto_engine()
    if normalized_engine == SHELL_ENGINE_BASH:
        bash_path = shutil.which("bash")
        if not bash_path:
            return None, "shell_unavailable", "No supported shell is available in current runtime.", normalized_engine
        return [bash_path, "-lc", command_text], "", "", normalized_engine

    if normalized_engine == SHELL_ENGINE_POWERSHELL:
        pwsh_path = shutil.which("powershell") or shutil.which("powershell.exe")
        if not pwsh_path:
            return None, "shell_unavailable", "No supported shell is available in current runtime.", normalized_engine
        return [
            pwsh_path,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command_text,
        ], "", "", normalized_engine

    return None, "invalid_tool_input", "engine must be one of: auto, bash, powershell.", normalized_engine


def run_terminal_command(
    command,
    timeout_seconds=DEFAULT_TERMINAL_TIMEOUT_SECONDS,
    cwd=None,
    engine=SHELL_ENGINE_AUTO,
    extra_env=None,
    capture_cwd=False,
):
    """Execute one terminal command and return raw combined terminal output."""
    command_text = str(command or "")
    engine_name = str(engine or SHELL_ENGINE_AUTO).strip().lower()
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
            "final_cwd": "",
        }

    cwd_capture_path = ""
    if capture_cwd:
        fd, cwd_capture_path = tempfile.mkstemp(prefix="snowfox-shell-cwd-", text=True)
        os.close(fd)

    resolved_engine = engine_name
    if engine_name == SHELL_ENGINE_AUTO:
        resolved_engine = _resolve_auto_engine()
    exec_command_text = _append_cwd_capture(command_text, resolved_engine, cwd_capture_path)

    argv, error_code, error_message, resolved_engine = _resolve_shell_argv(engine_name, exec_command_text)
    if not argv:
        if cwd_capture_path:
            try:
                os.unlink(cwd_capture_path)
            except OSError:
                pass
        return {
            "ok": False,
            "error_code": error_code or "terminal_exec_failed",
            "message": error_message or "Shell engine is unavailable.",
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": resolved_engine,
            "final_cwd": "",
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
        if cwd_capture_path:
            try:
                os.unlink(cwd_capture_path)
            except OSError:
                pass
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": resolved_engine,
            "final_cwd": "",
        }

    try:
        raw_output, _ = process.communicate(timeout=float(timeout_seconds))
        normalized_output = _normalize_terminal_output(raw_output)
    except subprocess.TimeoutExpired:
        process.kill()
        raw_output, _ = process.communicate()
        normalized_output = _normalize_terminal_output(raw_output)
        if cwd_capture_path:
            try:
                os.unlink(cwd_capture_path)
            except OSError:
                pass
        return {
            "ok": False,
            "error_code": "terminal_timeout",
            "message": f"Terminal command timed out after {timeout_seconds} second(s).",
            "exit_code": -1,
            "raw_output": normalized_output,
            "effective_cwd": effective_cwd,
            "engine": resolved_engine,
            "final_cwd": "",
        }
    except Exception as exc:
        process.kill()
        if cwd_capture_path:
            try:
                os.unlink(cwd_capture_path)
            except OSError:
                pass
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
            "effective_cwd": effective_cwd,
            "engine": resolved_engine,
            "final_cwd": "",
        }

    final_cwd = ""
    if cwd_capture_path:
        try:
            final_cwd = _normalize_terminal_output(
                Path(cwd_capture_path).read_text(encoding="utf-8", errors="replace")
            ).strip()
        except Exception:
            final_cwd = ""
        try:
            os.unlink(cwd_capture_path)
        except OSError:
            pass

    exit_code = int(process.returncode if process.returncode is not None else -1)
    if exit_code != 0:
        return {
            "ok": False,
            "error_code": "terminal_nonzero_exit",
            "message": f"Terminal command exited with status {exit_code}.",
            "exit_code": exit_code,
            "raw_output": normalized_output,
            "effective_cwd": effective_cwd,
            "engine": resolved_engine,
            "final_cwd": final_cwd,
        }

    return {
        "ok": True,
        "exit_code": exit_code,
        "raw_output": normalized_output,
        "effective_cwd": effective_cwd,
        "engine": resolved_engine,
        "final_cwd": final_cwd,
    }
