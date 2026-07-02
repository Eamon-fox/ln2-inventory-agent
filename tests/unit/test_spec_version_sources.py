"""
Module: test_spec_version_sources
Layer: unit
Covers: snowfox.spec / snowfox.mac.spec
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WINDOWS_SPEC = ROOT / "snowfox.spec"
MAC_SPEC = ROOT / "snowfox.mac.spec"


class TestSpecVersionSources(unittest.TestCase):
    def test_windows_spec_reads_version_py(self):
        text = WINDOWS_SPEC.read_text(encoding="utf-8")
        self.assertIn('with open("app_gui/version.py", encoding="utf-8") as f:', text)
        self.assertIn(r'APP_VERSION[^=]*=\s*["\']([^"\']+)["\']', text)

    def test_mac_spec_reads_version_py(self):
        text = MAC_SPEC.read_text(encoding="utf-8")
        self.assertIn('with open("app_gui/version.py", encoding="utf-8") as handle:', text)
        self.assertIn(r'APP_VERSION[^=]*=\s*["\']([^"\']+)["\']', text)


if __name__ == "__main__":
    unittest.main()
