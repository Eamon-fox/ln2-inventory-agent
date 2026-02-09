import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.yaml_ops import (
    ensure_http_server,
    list_yaml_backups,
    load_yaml,
    rollback_yaml,
    stop_http_server,
    write_yaml,
)


def make_record(rec_id=1, box=1, positions=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


class YamlOpsPreviewTests(unittest.TestCase):
    def test_write_yaml_creates_html_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_ops_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = make_data([])

            write_yaml(data, path=str(yaml_path), auto_html=True, auto_server=False)

            html_path = Path(temp_dir) / "ln2_inventory.html"
            self.assertTrue(html_path.exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn('id="search-input"', html_text)
            self.assertIn('id="detail-panel"', html_text)

    def test_ensure_http_server_starts_and_reuses_process(self):
        with tempfile.TemporaryDirectory(prefix="ln2_preview_") as temp_dir:
            html_path = Path(temp_dir) / "ln2_inventory.html"
            html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()

            try:
                url, started = ensure_http_server(temp_dir, preferred_port=port)
                self.assertTrue(started)
                self.assertIn(f":{port}/ln2_inventory.html", url)

                with urlopen(url, timeout=2) as resp:
                    body = resp.read().decode("utf-8")
                self.assertIn("ok", body)

                url2, started2 = ensure_http_server(temp_dir, preferred_port=port)
                self.assertFalse(started2)
                self.assertEqual(url, url2)
            finally:
                stop_http_server(temp_dir)


class YamlOpsSafetyTests(unittest.TestCase):
    def test_write_yaml_creates_backup_and_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_safety_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            data_v1 = make_data([make_record(1, box=1, positions=[1])])
            write_yaml(
                data_v1,
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            data_v2 = make_data([
                make_record(1, box=1, positions=[1]),
                make_record(2, box=2, positions=[3, 4]),
            ])
            write_yaml(
                data_v2,
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "add_entry", "source": "tests"},
            )

            backups = list_yaml_backups(str(yaml_path))
            self.assertEqual(1, len(backups))

            audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
            self.assertTrue(audit_path.exists())

            lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)
            last = lines[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("tests", last["source"])
            self.assertIn(2, last["changed_ids"]["added"])
            self.assertTrue(last["backup_path"])

    def test_rollback_yaml_restores_latest_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rollback_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            data_v1 = make_data([make_record(1, box=1, positions=[1])])
            data_v2 = make_data([make_record(1, box=1, positions=[9])])

            write_yaml(data_v1, path=str(yaml_path), auto_html=False, auto_server=False)
            write_yaml(data_v2, path=str(yaml_path), auto_html=False, auto_server=False)

            current = load_yaml(str(yaml_path))
            self.assertEqual([9], current["inventory"][0]["positions"])

            result = rollback_yaml(
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"source": "tests"},
            )

            restored = load_yaml(str(yaml_path))
            self.assertEqual([1], restored["inventory"][0]["positions"])
            self.assertTrue(Path(result["restored_from"]).exists())
            self.assertTrue(Path(result["snapshot_before_rollback"]).exists())


if __name__ == "__main__":
    unittest.main()
