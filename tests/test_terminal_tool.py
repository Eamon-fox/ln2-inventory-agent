import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.terminal_tool import _normalize_terminal_output, run_terminal_command


class TerminalToolTests(unittest.TestCase):
    def _skip_if_bash_missing(self):
        if shutil.which("bash"):
            return
        self.skipTest("bash is not available in current test runtime")

    def _expected_terminal_cwd(self):
        sandbox = ROOT / "migrate"
        return str(sandbox if sandbox.is_dir() else ROOT)

    def test_run_terminal_command_nonzero_exit(self):
        self._skip_if_bash_missing()
        response = run_terminal_command("echo boom; exit 7", timeout_seconds=10, engine="bash")

        self.assertFalse(response["ok"])
        self.assertEqual("terminal_nonzero_exit", response.get("error_code"))
        self.assertEqual(7, response.get("exit_code"))
        self.assertIn("boom", str(response.get("raw_output") or ""))
        self.assertEqual(self._expected_terminal_cwd(), response.get("effective_cwd"))

    def test_run_terminal_command_timeout(self):
        self._skip_if_bash_missing()
        response = run_terminal_command("sleep 2", timeout_seconds=0.2, engine="bash")

        self.assertFalse(response["ok"])
        self.assertEqual("terminal_timeout", response.get("error_code"))
        self.assertEqual(-1, response.get("exit_code"))
        self.assertIsInstance(response.get("raw_output"), str)
        self.assertEqual(self._expected_terminal_cwd(), response.get("effective_cwd"))

    def test_run_terminal_command_executes_in_default_cwd(self):
        self._skip_if_bash_missing()
        response = run_terminal_command("pwd", timeout_seconds=10, engine="bash")

        self.assertTrue(response["ok"])
        self.assertEqual(0, response.get("exit_code"))
        self.assertEqual(self._expected_terminal_cwd(), response.get("effective_cwd"))
        observed = str(response.get("raw_output") or "").strip()
        normalized = observed.replace("\\", "/").rstrip("/")
        self.assertTrue(normalized.lower().endswith("/migrate"))

    def test_cd_command_does_not_persist_between_calls(self):
        self._skip_if_bash_missing()
        first = run_terminal_command("cd ..", timeout_seconds=10, engine="bash")
        self.assertTrue(first["ok"])

        second = run_terminal_command(
            "pwd",
            timeout_seconds=10,
            engine="bash",
        )

        self.assertTrue(second["ok"])
        observed = str(second.get("raw_output") or "").strip()
        normalized = observed.replace("\\", "/").rstrip("/")
        self.assertTrue(normalized.lower().endswith("/migrate"))
        self.assertEqual(self._expected_terminal_cwd(), second.get("effective_cwd"))

    def test_invalid_engine_rejected(self):
        response = run_terminal_command("echo hi", timeout_seconds=5, engine="unknown")
        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response.get("error_code"))

    def test_bash_unavailable_returns_specific_error(self):
        with patch("agent.terminal_tool.shutil.which", return_value=None):
            response = run_terminal_command("echo hi", timeout_seconds=5, engine="bash")
        self.assertFalse(response["ok"])
        self.assertEqual("bash_unavailable", response.get("error_code"))

    def test_powershell_unavailable_returns_specific_error(self):
        with patch("agent.terminal_tool.shutil.which", return_value=None):
            response = run_terminal_command("Write-Output hi", timeout_seconds=5, engine="powershell")
        self.assertFalse(response["ok"])
        self.assertEqual("powershell_unavailable", response.get("error_code"))

    def test_normalize_terminal_output_removes_nul_padding(self):
        raw = "w\x00s\x00l\x00:\x00 \x00o\x00k\x00\n\x00"
        self.assertEqual("wsl: ok\n", _normalize_terminal_output(raw))


if __name__ == "__main__":
    unittest.main()
