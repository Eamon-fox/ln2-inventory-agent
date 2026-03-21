"""New dataset dialog extracted from main window module."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app_gui.i18n import tr
from app_gui.ui.limits import MAX_BOX_COUNT_UI
from lib.position_fmt import BOX_LAYOUT_INDEXING_VALUES, DEFAULT_BOX_LAYOUT_INDEXING

_BOX_PRESETS = [
    ("9 x 9  (81)", 9, 9),
    ("10 x 10  (100)", 10, 10),
    ("8 x 12  (96)", 8, 12),
    ("5 x 5  (25)", 5, 5),
]


class NewDatasetDialog(QDialog):
    """Dialog for choosing box layout when creating a new dataset."""

    RESULT_IMPORT_EXISTING = int(QDialog.DialogCode.Accepted) + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.newDatasetLayout"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.preset_combo = QComboBox()
        for label, _r, _c in _BOX_PRESETS:
            self.preset_combo.addItem(label)
        self.preset_combo.addItem(tr("main.custom"))
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow(tr("main.boxSize"), self.preset_combo)

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 26)
        self.rows_spin.setValue(9)
        self.rows_spin.setEnabled(False)
        form.addRow(tr("main.rows"), self.rows_spin)

        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 26)
        self.cols_spin.setValue(9)
        self.cols_spin.setEnabled(False)
        form.addRow(tr("main.cols"), self.cols_spin)

        self.box_count_spin = QSpinBox()
        self.box_count_spin.setRange(1, MAX_BOX_COUNT_UI)
        self.box_count_spin.setValue(5)
        form.addRow(tr("main.boxCount"), self.box_count_spin)

        self.indexing_combo = QComboBox()
        for indexing in BOX_LAYOUT_INDEXING_VALUES:
            label_key = "main.indexNumeric" if indexing == "numeric" else "main.indexAlpha"
            self.indexing_combo.addItem(tr(label_key), indexing)
        form.addRow(tr("main.indexing"), self.indexing_combo)

        layout.addLayout(form)

        footer = QHBoxLayout()
        import_btn = QPushButton(tr("main.importExistingDataTitle"))
        import_btn.setToolTip(tr("main.importExistingDataHint"))
        import_btn.clicked.connect(self._request_import_existing_data)
        footer.addWidget(import_btn)
        footer.addStretch(1)

        buttons = QDialogButtonBox()
        ok_btn = QPushButton(tr("common.ok"))
        ok_btn.clicked.connect(self.accept)
        buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.clicked.connect(self.reject)
        buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def _on_preset_changed(self, index):
        is_custom = index >= len(_BOX_PRESETS)
        self.rows_spin.setEnabled(is_custom)
        self.cols_spin.setEnabled(is_custom)
        if not is_custom:
            _, r, c = _BOX_PRESETS[index]
            self.rows_spin.setValue(r)
            self.cols_spin.setValue(c)

    def _request_import_existing_data(self):
        self.done(self.RESULT_IMPORT_EXISTING)

    def get_layout(self):
        box_count = self.box_count_spin.value()
        result = {
            "rows": self.rows_spin.value(),
            "cols": self.cols_spin.value(),
            "box_count": box_count,
            "box_numbers": list(range(1, box_count + 1)),
        }
        indexing = self.indexing_combo.currentData()
        if indexing and indexing != DEFAULT_BOX_LAYOUT_INDEXING:
            result["indexing"] = indexing
        return result


__all__ = ["NewDatasetDialog"]
