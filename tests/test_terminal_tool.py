import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.terminal_tool import run_terminal_command


def _shell_command(args):
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


class TerminalToolTests(unittest.TestCase):
    def test_run_terminal_command_nonzero_exit(self):
        command = _shell_command(
            [sys.executable, "-c", "import sys; print('boom'); sys.exit(7)"]
        )
        response = run_terminal_command(command, timeout_seconds=10)

        self.assertFalse(response["ok"])
        self.assertEqual("terminal_nonzero_exit", response.get("error_code"))
        self.assertEqual(7, response.get("exit_code"))
        self.assertIn("boom", str(response.get("raw_output") or ""))

    def test_run_terminal_command_timeout(self):
        command = _shell_command(
            [sys.executable, "-c", "import time; time.sleep(2)"]
        )
        response = run_terminal_command(command, timeout_seconds=0.2)

        self.assertFalse(response["ok"])
        self.assertEqual("terminal_timeout", response.get("error_code"))
        self.assertEqual(-1, response.get("exit_code"))
        self.assertIsInstance(response.get("raw_output"), str)


if __name__ == "__main__":
    unittest.main()
