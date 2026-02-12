import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lib.config as config_module


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.get("LN2_CONFIG_FILE")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("LN2_CONFIG_FILE", None)
        else:
            os.environ["LN2_CONFIG_FILE"] = self._old_env
        importlib.reload(config_module)

    def test_env_config_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cfg_") as temp_dir:
            cfg_path = Path(temp_dir) / "ln2_config.json"
            cfg_payload = {
                "yaml_path": "./data/inventory.yaml",
                "python_path": sys.executable,
                "safety": {
                    "backup_keep_count": 42,
                    "yaml_size_warning_mb": 1.5,
                },
            }
            cfg_path.write_text(json.dumps(cfg_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            os.environ["LN2_CONFIG_FILE"] = str(cfg_path)
            mod = importlib.reload(config_module)

            self.assertEqual(os.path.join(temp_dir, "data", "inventory.yaml"), mod.YAML_PATH)
            self.assertEqual(sys.executable, mod.PYTHON_PATH)
            self.assertEqual(42, mod.BACKUP_KEEP_COUNT)
            self.assertEqual(1.5, mod.YAML_SIZE_WARNING_MB)


if __name__ == "__main__":
    unittest.main()
