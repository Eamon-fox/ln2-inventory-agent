import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.gui_config import load_gui_config, save_gui_config, DEFAULT_GUI_CONFIG, _load_default_prompt


class GuiConfigTests(unittest.TestCase):
    def test_load_gui_config_defaults(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("deepseek", cfg["ai"]["provider"])
        self.assertEqual("deepseek-chat", cfg["ai"]["model"])
        self.assertEqual(12, cfg["ai"]["max_steps"])
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
        self.assertEqual(12, cfg["ai"]["max_steps"])
        self.assertTrue(cfg["ai"]["thinking_enabled"])

    def test_save_and_load_gui_config_keeps_explicit_model(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "yaml_path": "/tmp/ln2_inventory.yaml",
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


class ApiKeysConfigTests(unittest.TestCase):
    def test_default_config_has_api_keys_as_empty_dict(self):
        self.assertIn("api_keys", DEFAULT_GUI_CONFIG)
        self.assertEqual({}, DEFAULT_GUI_CONFIG["api_keys"])

    def test_load_gui_config_defaults_api_keys_to_empty_dict(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_apikeys_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual({}, cfg.get("api_keys"))

    def test_save_and_load_api_keys(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_apikeys_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "yaml_path": "/tmp/ln2_inventory.yaml",
                "api_keys": {
                    "deepseek": "sk-deepseek-123",
                    "zhipu": "glm-zhipu-456",
                },
                "ai": {
                    "model": "deepseek-chat",
                    "max_steps": 8,
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("sk-deepseek-123", cfg["api_keys"].get("deepseek"))
        self.assertEqual("glm-zhipu-456", cfg["api_keys"].get("zhipu"))


class CustomPromptConfigTests(unittest.TestCase):
    def test_default_custom_prompt_falls_back_to_bundled_file(self):
        """When config has no custom_prompt, load_gui_config uses default_prompt.txt."""
        bundled = _load_default_prompt()
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual(bundled, cfg["ai"]["custom_prompt"])

    def test_save_and_load_custom_prompt(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_save_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "ai": {
                    "model": "deepseek-chat",
                    "custom_prompt": "请用中文回答",
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual("请用中文回答", cfg["ai"]["custom_prompt"])

    def test_missing_custom_prompt_backfills_from_bundled_file(self):
        """Config without custom_prompt key gets bundled default."""
        bundled = _load_default_prompt()
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_miss_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """ai:
  model: deepseek-chat
  max_steps: 5
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual(bundled, cfg["ai"]["custom_prompt"])

    def test_custom_prompt_in_default_config(self):
        self.assertIn("custom_prompt", DEFAULT_GUI_CONFIG["ai"])
        self.assertEqual("", DEFAULT_GUI_CONFIG["ai"]["custom_prompt"])

    def test_user_custom_prompt_overrides_bundled_default(self):
        """When user explicitly sets custom_prompt, it takes priority over bundled file."""
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_override_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "ai": {
                    "model": "deepseek-chat",
                    "custom_prompt": "my own instructions",
                },
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))
        self.assertEqual("my own instructions", cfg["ai"]["custom_prompt"])

    def test_bundled_default_prompt_file_exists(self):
        """The default_prompt.txt file should exist in assets."""
        bundled = _load_default_prompt()
        self.assertTrue(len(bundled) > 0, "default_prompt.txt should not be empty")

    def test_custom_prompt_survives_close_save_roundtrip(self):
        """Regression: closeEvent used to rebuild ai dict without custom_prompt."""
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_close_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            # Simulate: user sets custom_prompt via settings dialog
            initial = {
                "yaml_path": "/tmp/demo.yaml",
                "ai": {
                    "model": "deepseek-chat",
                    "max_steps": 12,
                    "thinking_enabled": True,
                    "custom_prompt": "请用中文回答",
                },
            }
            save_gui_config(initial, path=str(config_path))

            # Simulate: closeEvent rebuilds ai dict (must include custom_prompt)
            cfg = load_gui_config(path=str(config_path))
            cfg["ai"] = {
                "model": cfg["ai"]["model"],
                "max_steps": cfg["ai"]["max_steps"],
                "thinking_enabled": cfg["ai"]["thinking_enabled"],
                "custom_prompt": cfg["ai"].get("custom_prompt", ""),
            }
            save_gui_config(cfg, path=str(config_path))

            # Reload and verify custom_prompt survived
            reloaded = load_gui_config(path=str(config_path))
            self.assertEqual("请用中文回答", reloaded["ai"]["custom_prompt"])

    def test_custom_prompt_lost_without_field_in_save(self):
        """If custom_prompt is omitted during save, it falls back to bundled default."""
        bundled = _load_default_prompt()
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_cp_lost_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            initial = {
                "ai": {
                    "model": "deepseek-chat",
                    "custom_prompt": "my instructions",
                },
            }
            save_gui_config(initial, path=str(config_path))

            # Simulate buggy closeEvent that omits custom_prompt
            cfg = load_gui_config(path=str(config_path))
            buggy_ai = {
                "model": cfg["ai"]["model"],
                "max_steps": cfg["ai"]["max_steps"],
                "thinking_enabled": cfg["ai"]["thinking_enabled"],
                # custom_prompt intentionally omitted — this was the bug
            }
            save_gui_config({"ai": buggy_ai}, path=str(config_path))

            reloaded = load_gui_config(path=str(config_path))
            # Without the field, falls back to bundled default (not user's "my instructions")
            self.assertEqual(bundled, reloaded["ai"]["custom_prompt"])
            self.assertNotEqual("my instructions", reloaded["ai"]["custom_prompt"])


class ReleaseNotificationConfigTests(unittest.TestCase):
    def test_default_config_has_release_notification_fields(self):
        self.assertIn("last_notified_release", DEFAULT_GUI_CONFIG)
        self.assertEqual("0.0.0", DEFAULT_GUI_CONFIG["last_notified_release"])
        self.assertIn("release_notes_preview", DEFAULT_GUI_CONFIG)
        self.assertEqual("", DEFAULT_GUI_CONFIG["release_notes_preview"])

    def test_save_and_load_release_notification_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_release_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            source = {
                "last_notified_release": "1.0.0",
                "release_notes_preview": "Bug fixes and improvements.",
            }
            save_gui_config(source, path=str(config_path))
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("1.0.0", cfg["last_notified_release"])
        self.assertEqual("Bug fixes and improvements.", cfg["release_notes_preview"])

    def test_load_config_missing_release_fields_uses_defaults(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_cfg_release_miss_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """yaml_path: /tmp/demo.yaml
""",
                encoding="utf-8",
            )
            cfg = load_gui_config(path=str(config_path))

        self.assertEqual("0.0.0", cfg["last_notified_release"])
        self.assertEqual("", cfg["release_notes_preview"])


if __name__ == "__main__":
    unittest.main()
