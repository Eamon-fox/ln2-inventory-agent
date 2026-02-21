"""Dialog for exporting external-agent conversion task bundles."""

import os

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import t, tr
from lib.import_task_bundle import build_import_task_bundle


class ExportTaskBundleDialog(QDialog):
    """Guide users to export a standardized conversion bundle ZIP."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.exportTaskBundleTitle"))
        self.setMinimumWidth(700)
        self.setMinimumHeight(420)

        self._source_paths = []

        layout = QVBoxLayout(self)

        desc = QLabel(tr("main.exportTaskBundleDesc"))
        desc.setWordWrap(True)
        desc.setProperty("role", "dialogHint")
        layout.addWidget(desc)

        source_group = QWidget()
        source_form = QFormLayout(source_group)

        source_toolbar = QHBoxLayout()
        add_files_btn = QPushButton(tr("main.selectSourceFiles"))
        add_files_btn.clicked.connect(self._add_files)
        source_toolbar.addWidget(add_files_btn)

        add_dir_btn = QPushButton(tr("main.selectSourceFolder"))
        add_dir_btn.clicked.connect(self._add_folder)
        source_toolbar.addWidget(add_dir_btn)

        clear_btn = QPushButton(tr("ai.clear"))
        clear_btn.clicked.connect(self._clear_sources)
        source_toolbar.addWidget(clear_btn)
        source_toolbar.addStretch()

        source_form.addRow(tr("main.exportBundleSources"), source_toolbar)

        self.source_preview = QTextEdit()
        self.source_preview.setReadOnly(True)
        self.source_preview.setMinimumHeight(140)
        source_form.addRow("", self.source_preview)

        output_row = QHBoxLayout()
        default_output = os.path.join(
            os.path.expanduser("~"),
            "ln2_import_task_bundle.zip",
        )
        self.output_edit = QLineEdit(default_output)
        output_row.addWidget(self.output_edit, 1)

        browse_output_btn = QPushButton(tr("settings.browse"))
        browse_output_btn.clicked.connect(self._browse_output)
        output_row.addWidget(browse_output_btn)
        source_form.addRow(tr("main.exportBundleOutput"), output_row)

        layout.addWidget(source_group, 1)

        buttons = QDialogButtonBox()
        export_btn = QPushButton(tr("main.exportTaskBundleAction"))
        export_btn.clicked.connect(self._export_bundle)
        buttons.addButton(export_btn, QDialogButtonBox.AcceptRole)

        close_btn = QPushButton(tr("common.close"))
        close_btn.clicked.connect(self.reject)
        buttons.addButton(close_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)

        self._render_source_preview()

    def _render_source_preview(self):
        if not self._source_paths:
            self.source_preview.setPlainText(tr("main.exportBundleNoSources"))
            return
        lines = [str(path) for path in self._source_paths]
        self.source_preview.setPlainText("\n".join(lines))

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("main.selectSourceFiles"),
            "",
            tr("main.allFilesFilter"),
        )
        if not paths:
            return
        seen = set(self._source_paths)
        for path in paths:
            if path not in seen:
                self._source_paths.append(path)
                seen.add(path)
        self._render_source_preview()

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("main.selectSourceFolder"),
            "",
        )
        if not folder:
            return
        if folder not in self._source_paths:
            self._source_paths.append(folder)
        self._render_source_preview()

    def _clear_sources(self):
        self._source_paths = []
        self._render_source_preview()

    def _browse_output(self):
        output, _ = QFileDialog.getSaveFileName(
            self,
            tr("main.exportBundleOutput"),
            self.output_edit.text().strip(),
            tr("main.zipFilesFilter"),
        )
        if output:
            self.output_edit.setText(output)

    def _export_bundle(self):
        output_path = self.output_edit.text().strip()
        result = build_import_task_bundle(self._source_paths, output_path)
        if result.get("ok"):
            bundle_path = result.get("bundle_path") or output_path
            warning_text = ""
            warnings = result.get("warnings") or []
            if warnings:
                warning_text = "\n\n" + t("main.exportTaskBundleWarnings", warnings="\n".join(warnings))
            QMessageBox.information(
                self,
                tr("common.info"),
                t("main.exportTaskBundleSuccess", path=bundle_path) + warning_text,
            )
            return

        QMessageBox.warning(
            self,
            tr("common.info"),
            result.get("message") or tr("main.exportTaskBundleFailed"),
        )


__all__ = ["ExportTaskBundleDialog"]
