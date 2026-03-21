"""Test utilities for strict managed-inventory path policy."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from lib.app_storage import set_session_data_root
from lib.inventory_paths import create_managed_dataset_yaml_path


def _default_inventory_payload():
    return {
        "meta": {
            "box_layout": {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_numbers": [1, 2, 3, 4, 5],
            },
        },
        "inventory": [],
    }


class ManagedPathTestCase(unittest.TestCase):
    """Base TestCase that forces temp YAML files into managed dataset paths."""

    def setUp(self):
        super().setUp()
        self._install_root_tmp = tempfile.TemporaryDirectory(prefix="ln2_test_install_")
        self.install_root = Path(self._install_root_tmp.name)
        self.inventories_root = self.install_root / "inventories"
        self.inventories_root.mkdir(parents=True, exist_ok=True)

        self._patch_install_dir = patch(
            "lib.app_storage.get_install_dir",
            return_value=str(self.install_root),
        )
        self._patch_install_dir.start()
        self.addCleanup(self._patch_install_dir.stop)
        set_session_data_root(str(self.install_root))
        self.addCleanup(lambda: set_session_data_root(""))

        original_tempdir = tempfile.TemporaryDirectory
        original_mkdtemp = tempfile.mkdtemp

        def _managed_tempdir(*args, **kwargs):
            params = dict(kwargs)
            params.setdefault("dir", str(self.inventories_root))
            return original_tempdir(*args, **params)

        def _managed_mkdtemp(*args, **kwargs):
            if len(args) >= 3 or "dir" in kwargs:
                return original_mkdtemp(*args, **kwargs)
            params = dict(kwargs)
            params["dir"] = str(self.inventories_root)
            return original_mkdtemp(*args, **params)

        self._patch_tempdir = patch(
            "tempfile.TemporaryDirectory",
            side_effect=_managed_tempdir,
        )
        self._patch_tempdir.start()
        self.addCleanup(self._patch_tempdir.stop)

        self._patch_mkdtemp = patch(
            "tempfile.mkdtemp",
            side_effect=_managed_mkdtemp,
        )
        self._patch_mkdtemp.start()
        self.addCleanup(self._patch_mkdtemp.stop)
        self.addCleanup(self._install_root_tmp.cleanup)

        self.fake_yaml_path = self.ensure_dataset_yaml("_fake")

    def ensure_dataset_yaml(self, dataset_name, payload=None):
        yaml_path = Path(create_managed_dataset_yaml_path(dataset_name))
        if payload is None:
            payload = _default_inventory_payload()
        os.makedirs(yaml_path.parent, exist_ok=True)
        yaml_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
            encoding="utf-8",
        )
        return str(yaml_path)
