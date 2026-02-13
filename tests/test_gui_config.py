import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.gui_config import load_gui_config, save_gui_config, DEFAULT_GUI_CONFIG


class GuiConfigTests(unittest.TestCase):
    def test_load_gui_config_defaults_to_deepseek_chat_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertEqual(8, cfg["ai"]["max_steps"])
        self.assertTrue(cfg["ai"]["thinking_enabled"])

    def test_load_gui_config_backfills_blank_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_blank_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """yaml_path: /tmp/demo.yaml
ai:
  model: ""
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertEqual(8, cfg["ai"]["max_steps"])
        self.assertTrue(cfg["ai"]["thinking_enabled"])

    def test_save_and_load_gui_config_keeps_explicit_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "yaml_path": "/tmp/ln2_inventory.yaml",
                "actor_id": "gui-test",
                "ai": {
                    "model": "deepseek-chat",
                    "max_steps": 12,
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertEqual(12, cfg["ai"]["max_steps"])
        self.assertTrue(cfg["ai"]["thinking_enabled"])

    def test_load_gui_config_ignores_legacy_mock_field(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_legacy_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """ai:
  model: deepseek-chat
  mock: true
  max_steps: 5
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertEqual(5, cfg["ai"]["max_steps"])
        self.assertTrue(cfg["ai"]["thinking_enabled"])
        self.assertNotIn("mock", cfg["ai"])

    def test_save_and_load_thinking_enabled_flag(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_thinking_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "ai": {
                    "model": "deepseek-chat",
                    "max_steps": 8,
                    "thinking_enabled": False,
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertFalse(cfg["ai"]["thinking_enabled"])


class ApiKeyConfigTests(unittest.TestCase):
    def test_default_config_has_api_key_none(self):
        self.assertIsNone(DEFAULT_GUI_CONFIG.get("api_key"))

    def test_load_gui_config_defaults_api_key_to_none(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_api_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))
        self.assertIsNone(cfg.get("api_key"))

    def test_save_and_load_api_key(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_api_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "yaml_path": "/tmp/ln2_inventory.yaml",
                "actor_id": "gui-test",
                "api_key": "sk-test-12345",
                "ai": {
                    "model": "deepseek-chat",
                    "max_steps": 8,
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("sk-test-12345", cfg.get("api_key"))

    def test_load_config_with_empty_api_key(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_api_empty_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """yaml_path: /tmp/demo.yaml
api_key: ""
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual("", cfg.get("api_key"))

    def test_load_config_preserves_existing_api_key(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_api_exist_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """yaml_path: /tmp/demo.yaml
api_key: existing-key-xyz
actor_id: test-user
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual("existing-key-xyz", cfg.get("api_key"))
        self.assertEqual("test-user", cfg.get("actor_id"))


if __name__ == "__main__":
    unittest.main()
