import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.gui_config import load_gui_config, save_gui_config


class GuiConfigTests(unittest.TestCase):
    def test_load_gui_config_defaults_to_deepseek_chat_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertTrue(cfg["ai"]["mock"])

    def test_load_gui_config_backfills_blank_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_blank_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """yaml_path: /tmp/demo.yaml
ai:
  model: ""
  mock: false
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertFalse(cfg["ai"]["mock"])

    def test_save_and_load_gui_config_keeps_explicit_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "yaml_path": "/tmp/ln2_inventory.yaml",
                "actor_id": "gui-test",
                "ai": {
                    "model": "deepseek-chat",
                    "mock": False,
                    "max_steps": 12,
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertFalse(cfg["ai"]["mock"])
        self.assertEqual(12, cfg["ai"]["max_steps"])


if __name__ == "__main__":
    unittest.main()
