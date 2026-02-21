"""Dialog for strict validation and import of externally generated YAML."""

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
)

from app_gui.i18n import t, tr
from lib.import_acceptance import import_validated_yaml, validate_candidate_yaml


class ImportValidatedYamlDialog(QDialog):
    """Validate a candidate YAML and import it as a new dataset file."""

    def __init__(self, parent=None, default_target_path=""):
        super().__init__(parent)
        self.setWindowTitle(tr("main.importValidatedTitle"))
        self.setMinimumWidth(760)
        self.setMinimumHeight(480)

        self.imported_yaml_path = ""
        self._last_validation_ok = False

        layout = QVBoxLayout(self)

        desc = QLabel(tr("main.importValidatedDesc"))
        desc.setWordWrap(True)
        desc.setProperty("role", "dialogHint")
        layout.addWidget(desc)

        guide = QLabel(tr("main.importValidatedGuide"))
        guide.setWordWrap(True)
        guide.setProperty("role", "dialogHint")
        layout.addWidget(guide)

        form = QFormLayout()

        candidate_row = QHBoxLayout()
        self.candidate_edit = QLineEdit()
        candidate_row.addWidget(self.candidate_edit, 1)
        browse_candidate_btn = QPushButton(tr("settings.browse"))
        browse_candidate_btn.clicked.connect(self._browse_candidate)
        candidate_row.addWidget(browse_candidate_btn)
        form.addRow(tr("main.importCandidateYaml"), candidate_row)

        target_row = QHBoxLayout()
        self.target_edit = QLineEdit(default_target_path or "")
        target_row.addWidget(self.target_edit, 1)
        browse_target_btn = QPushButton(tr("settings.browse"))
        browse_target_btn.clicked.connect(self._browse_target)
        target_row.addWidget(browse_target_btn)
        form.addRow(tr("main.importTargetYaml"), target_row)

        layout.addLayout(form)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText(tr("main.importValidationResultPlaceholder"))
        layout.addWidget(self.result_view, 1)

        buttons = QDialogButtonBox()
        self.validate_btn = QPushButton(tr("main.importValidateAction"))
        self.validate_btn.clicked.connect(self._run_validation)
        buttons.addButton(self.validate_btn, QDialogButtonBox.ActionRole)

        self.import_btn = QPushButton(tr("main.importValidatedAction"))
        self.import_btn.clicked.connect(self._run_import)
        self.import_btn.setEnabled(False)
        buttons.addButton(self.import_btn, QDialogButtonBox.AcceptRole)

        close_btn = QPushButton(tr("common.close"))
        close_btn.clicked.connect(self.reject)
        buttons.addButton(close_btn, QDialogButtonBox.RejectRole)

        layout.addWidget(buttons)

        self.target_edit.textChanged.connect(self._refresh_import_enabled)
        self.candidate_edit.textChanged.connect(self._on_candidate_changed)

    def _on_candidate_changed(self):
        self._last_validation_ok = False
        self._refresh_import_enabled()

    def _refresh_import_enabled(self):
        has_target = bool(str(self.target_edit.text() or "").strip())
        self.import_btn.setEnabled(bool(self._last_validation_ok and has_target))

    def _browse_candidate(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("main.importCandidateYaml"),
            "",
            "YAML Files (*.yaml *.yml)",
        )
        if path:
            self.candidate_edit.setText(path)

    def _browse_target(self):
        target, _ = QFileDialog.getSaveFileName(
            self,
            tr("main.importTargetYaml"),
            self.target_edit.text().strip(),
            "YAML Files (*.yaml *.yml)",
        )
        if target:
            self.target_edit.setText(target)

    @staticmethod
    def _format_report(report: dict) -> str:
        if not isinstance(report, dict):
            return ""
        lines = []
        errors = report.get("errors") or []
        warnings = report.get("warnings") or []
        lines.append(f"errors: {len(errors)}")
        for item in errors[:20]:
            lines.append(f"  - {item}")
        if len(errors) > 20:
            lines.append(f"  - ... and {len(errors) - 20} more")
        lines.append(f"warnings: {len(warnings)}")
        for item in warnings[:20]:
            lines.append(f"  - {item}")
        if len(warnings) > 20:
            lines.append(f"  - ... and {len(warnings) - 20} more")
        return "\n".join(lines)

    def _run_validation(self):
        candidate = self.candidate_edit.text().strip()
        result = validate_candidate_yaml(candidate, fail_on_warnings=True)
        self._last_validation_ok = bool(result.get("ok"))
        message = result.get("message") or ""
        report_text = self._format_report(result.get("report") or {})
        text = message
        if report_text:
            text = f"{message}\n\n{report_text}".strip()
        self.result_view.setPlainText(text)
        self._refresh_import_enabled()

    def _run_import(self):
        if not self._last_validation_ok:
            self._run_validation()
            if not self._last_validation_ok:
                QMessageBox.warning(self, tr("common.info"), tr("main.importValidationFailed"))
                return

        candidate = self.candidate_edit.text().strip()
        target = self.target_edit.text().strip()
        overwrite = False
        if target and os.path.exists(target):
            reply = QMessageBox.question(
                self,
                tr("common.info"),
                t("main.importTargetExistsConfirm", path=target),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return
            overwrite = True

        result = import_validated_yaml(candidate, target, mode="create_new", overwrite=overwrite)
        if not result.get("ok"):
            message = result.get("message") or tr("main.importValidatedFailed")
            report_text = self._format_report(result.get("report") or {})
            if report_text:
                message = f"{message}\n\n{report_text}"
            QMessageBox.warning(self, tr("common.info"), message)
            return

        self.imported_yaml_path = result.get("target_path") or ""
        QMessageBox.information(
            self,
            tr("common.info"),
            t("main.importValidatedSuccess", path=self.imported_yaml_path),
        )
        self.accept()


__all__ = ["ImportValidatedYamlDialog"]
