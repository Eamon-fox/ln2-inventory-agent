"""Terminal command helper for AgentToolRunner."""

import subprocess


DEFAULT_TERMINAL_TIMEOUT_SECONDS = 120


def run_terminal_command(command, timeout_seconds=DEFAULT_TERMINAL_TIMEOUT_SECONDS):
    """Execute one terminal command and return raw combined terminal output."""
    command_text = str(command or "")
    if not command_text.strip():
        return {
            "ok": False,
            "error_code": "invalid_tool_input",
            "message": "command must be a non-empty string.",
            "exit_code": -1,
            "raw_output": "",
        }

    try:
        process = subprocess.Popen(
            command_text,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
        }

    try:
        raw_output, _ = process.communicate(timeout=float(timeout_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        raw_output, _ = process.communicate()
        return {
            "ok": False,
            "error_code": "terminal_timeout",
            "message": f"Terminal command timed out after {timeout_seconds} second(s).",
            "exit_code": -1,
            "raw_output": raw_output or "",
        }
    except Exception as exc:
        process.kill()
        return {
            "ok": False,
            "error_code": "terminal_exec_failed",
            "message": str(exc),
            "exit_code": -1,
            "raw_output": "",
        }

    exit_code = int(process.returncode if process.returncode is not None else -1)
    if exit_code != 0:
        return {
            "ok": False,
            "error_code": "terminal_nonzero_exit",
            "message": f"Terminal command exited with status {exit_code}.",
            "exit_code": exit_code,
            "raw_output": raw_output or "",
        }

    return {
        "ok": True,
        "exit_code": exit_code,
        "raw_output": raw_output or "",
    }
