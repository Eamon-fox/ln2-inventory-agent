import os
import sys
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QApplication, QPushButton

    from app_gui.i18n import tr
    from app_gui.ui.dialogs.export_task_bundle_dialog import (
        ExportTaskBundleDialog,
        _SourceDropTextEdit,
    )

    PYSIDE_AVAILABLE = True
except Exception:
    QMimeData = None
    QUrl = None
    QApplication = None
    QPushButton = None
    tr = None
    ExportTaskBundleDialog = None
    _SourceDropTextEdit = None
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for dialog tests")
class ExportTaskBundleDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_extract_local_file_paths_filters_to_existing_files_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_file = tmp / "source.txt"
            source_file.write_text("demo", encoding="utf-8")
            source_dir = tmp / "source_folder"
            source_dir.mkdir()

            mime = QMimeData()
            mime.setUrls(
                [
                    QUrl.fromLocalFile(str(source_file)),
                    QUrl.fromLocalFile(str(source_dir)),
                    QUrl("https://example.com/source.txt"),
                ]
            )
            result = _SourceDropTextEdit._extract_local_file_paths(mime)

            self.assertEqual([os.path.abspath(str(source_file))], result)

    def test_append_source_files_dedupes_and_ignores_directories(self):
        dialog = ExportTaskBundleDialog()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                source_file = tmp / "source.txt"
                source_file.write_text("demo", encoding="utf-8")
                source_dir = tmp / "source_folder"
                source_dir.mkdir()

                added = dialog._append_source_files(
                    [str(source_file), str(source_file), str(source_dir)]
                )

                self.assertEqual(1, added)
                self.assertEqual([os.path.abspath(str(source_file))], dialog._source_paths)
                self.assertIn(
                    os.path.abspath(str(source_file)),
                    dialog.source_preview.toPlainText(),
                )
        finally:
            dialog.close()

    def test_append_source_files_returns_zero_for_non_file_inputs(self):
        dialog = ExportTaskBundleDialog()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                source_dir = Path(tmpdir) / "source_folder"
                source_dir.mkdir()

                added = dialog._append_source_files([str(source_dir)])

                self.assertEqual(0, added)
                self.assertEqual([], dialog._source_paths)
        finally:
            dialog.close()

    def test_dialog_does_not_show_add_folder_button(self):
        dialog = ExportTaskBundleDialog()
        try:
            labels = [btn.text() for btn in dialog.findChildren(QPushButton)]
            self.assertNotIn(tr("main.selectSourceFolder"), labels)
        finally:
            dialog.close()

    def test_source_preview_uses_empty_and_filled_state(self):
        dialog = ExportTaskBundleDialog()
        try:
            self.assertEqual("empty", dialog.source_preview.property("state"))

            with tempfile.TemporaryDirectory() as tmpdir:
                source_file = Path(tmpdir) / "source.txt"
                source_file.write_text("demo", encoding="utf-8")
                dialog._append_source_files([str(source_file)])

            self.assertEqual("filled", dialog.source_preview.property("state"))
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
