import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.llm_client import load_opencode_auth_env


def write_auth_json(path):
    payload = {
        "deepseek": {"type": "api", "key": "deepseek-test-key"},
        "moonshotai-cn": {"type": "api", "key": "kimi-test-key"},
        "zhipuai-coding-plan": {"type": "api", "key": "zhipu-test-key"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class LlmClientAuthTests(unittest.TestCase):
    def test_load_opencode_auth_env_sets_provider_keys(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "",
                    "MOONSHOT_API_KEY": "",
                    "KIMI_API_KEY": "",
                    "ZHIPUAI_API_KEY": "",
                    "ZHIPU_API_KEY": "",
                    "GLM_API_KEY": "",
                },
                clear=False,
            ):
                result = load_opencode_auth_env(auth_file=str(auth_path))
                self.assertTrue(result["ok"])
                self.assertEqual("deepseek-test-key", os.environ.get("DEEPSEEK_API_KEY"))
                self.assertEqual("kimi-test-key", os.environ.get("MOONSHOT_API_KEY"))
                self.assertEqual("kimi-test-key", os.environ.get("KIMI_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("ZHIPUAI_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("ZHIPU_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("GLM_API_KEY"))

    def test_load_opencode_auth_env_does_not_override_by_default(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_no_override_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "existing"}, clear=False):
                result = load_opencode_auth_env(auth_file=str(auth_path), force=False)
                self.assertTrue(result["ok"])
                self.assertEqual("existing", os.environ.get("DEEPSEEK_API_KEY"))

    def test_load_opencode_auth_env_force_overrides(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_force_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "existing"}, clear=False):
                result = load_opencode_auth_env(auth_file=str(auth_path), force=True)
                self.assertTrue(result["ok"])
                self.assertEqual("deepseek-test-key", os.environ.get("DEEPSEEK_API_KEY"))

    def test_load_opencode_auth_env_handles_missing_file(self):
        result = load_opencode_auth_env(auth_file="/tmp/non-existent-opencode-auth.json")
        self.assertFalse(result["ok"])
        self.assertEqual("missing_auth_file", result.get("reason"))


if __name__ == "__main__":
    unittest.main()
