"""Dialog for exporting external-agent conversion task bundles."""

import os

from PySide6.QtCore import QUrl
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
from lib.import_task_bundle import export_import_task_bundle


class _SourceDropTextEdit(QTextEdit):
    """Read-only preview box that accepts drag-and-drop of local files only."""

    def __init__(self, on_files_dropped, parent=None):
        super().__init__(parent)
        self._on_files_dropped = on_files_dropped
        self.setAcceptDrops(True)

    @staticmethod
    def _extract_local_file_paths(mime_data):
        urls = list(mime_data.urls()) if mime_data is not None and mime_data.hasUrls() else []
        paths = []
        for url in urls:
            if not isinstance(url, QUrl) or not url.isLocalFile():
                continue
            path = os.path.abspath(os.path.normpath(url.toLocalFile()))
            if os.path.isfile(path):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event):
        files = self._extract_local_file_paths(event.mimeData())
        if files:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        files = self._extract_local_file_paths(event.mimeData())
        if files:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        files = self._extract_local_file_paths(event.mimeData())
        if not files:
            event.ignore()
            return
        callback = self._on_files_dropped
        if callable(callback):
            callback(files)
        event.acceptProposedAction()


class ExportTaskBundleDialog(QDialog):
    """Guide users to export a standardized conversion bundle directory."""

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

        guide = QLabel(tr("main.exportTaskBundleGuide"))
        guide.setWordWrap(True)
        guide.setProperty("role", "dialogHint")
        layout.addWidget(guide)

        source_group = QWidget()
        source_form = QFormLayout(source_group)

        source_toolbar = QHBoxLayout()
        add_files_btn = QPushButton(tr("main.selectSourceFiles"))
        add_files_btn.clicked.connect(self._add_files)
        source_toolbar.addWidget(add_files_btn)

        clear_btn = QPushButton(tr("ai.clear"))
        clear_btn.clicked.connect(self._clear_sources)
        source_toolbar.addWidget(clear_btn)
        source_toolbar.addStretch()

        source_form.addRow(tr("main.exportBundleSources"), source_toolbar)

        self.source_preview = _SourceDropTextEdit(self._append_source_files)
        self.source_preview.setObjectName("exportTaskSourcePreview")
        self.source_preview.setReadOnly(True)
        self.source_preview.setMinimumHeight(140)
        source_form.addRow("", self.source_preview)

        output_row = QHBoxLayout()
        default_output = os.path.join(
            os.path.expanduser("~"),
            "ln2_import_task_bundle",
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
            self._set_source_preview_state("empty")
            self.source_preview.setPlainText(tr("main.exportBundleNoSources"))
            return
        self._set_source_preview_state("filled")
        lines = [str(path) for path in self._source_paths]
        self.source_preview.setPlainText("\n".join(lines))

    def _set_source_preview_state(self, state):
        state_text = str(state or "")
        if self.source_preview.property("state") == state_text:
            return
        self.source_preview.setProperty("state", state_text)
        style = self.source_preview.style()
        style.unpolish(self.source_preview)
        style.polish(self.source_preview)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("main.selectSourceFiles"),
            "",
            tr("main.allFilesFilter"),
        )
        if not paths:
            return
        self._append_source_files(paths)

    def _append_source_files(self, paths):
        normalized = []
        for path in paths or []:
            p = os.path.abspath(os.path.normpath(str(path or "").strip()))
            if not p:
                continue
            if not os.path.isfile(p):
                continue
            normalized.append(p)

        if not normalized:
            return 0

        seen = {os.path.normcase(os.path.abspath(p)) for p in self._source_paths}
        added = 0
        for path in normalized:
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            self._source_paths.append(path)
            added += 1
        if added:
            self._render_source_preview()
        return added

    def _clear_sources(self):
        self._source_paths = []
        self._render_source_preview()

    def _browse_output(self):
        output = QFileDialog.getExistingDirectory(
            self,
            tr("main.exportBundleOutput"),
            self.output_edit.text().strip(),
        )
        if output:
            self.output_edit.setText(output)

    def _export_bundle(self):
        output_path = self.output_edit.text().strip()
        result = export_import_task_bundle(self._source_paths, output_path)
        if result.get("ok"):
            bundle_path = result.get("bundle_dir") or output_path
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
