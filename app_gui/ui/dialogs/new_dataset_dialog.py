"""New dataset dialog extracted from main window module."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app_gui.i18n import tr

_BOX_PRESETS = [
    ("9 x 9  (81)", 9, 9),
    ("10 x 10  (100)", 10, 10),
    ("8 x 12  (96)", 8, 12),
    ("5 x 5  (25)", 5, 5),
]


class NewDatasetDialog(QDialog):
    """Dialog for choosing box layout when creating a new dataset."""

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
        self.box_count_spin.setRange(1, 50)
        self.box_count_spin.setValue(5)
        form.addRow(tr("main.boxCount"), self.box_count_spin)

        self.indexing_combo = QComboBox()
        self.indexing_combo.addItem(tr("main.indexNumeric"), "numeric")
        self.indexing_combo.addItem(tr("main.indexAlpha"), "alphanumeric")
        form.addRow(tr("main.indexing"), self.indexing_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox()
        ok_btn = QPushButton(tr("common.ok"))
        ok_btn.clicked.connect(self.accept)
        buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.clicked.connect(self.reject)
        buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)

    def _on_preset_changed(self, index):
        is_custom = index >= len(_BOX_PRESETS)
        self.rows_spin.setEnabled(is_custom)
        self.cols_spin.setEnabled(is_custom)
        if not is_custom:
            _, r, c = _BOX_PRESETS[index]
            self.rows_spin.setValue(r)
            self.cols_spin.setValue(c)

    def get_layout(self):
        result = {
            "rows": self.rows_spin.value(),
            "cols": self.cols_spin.value(),
            "box_count": self.box_count_spin.value(),
        }
        indexing = self.indexing_combo.currentData()
        if indexing and indexing != "numeric":
            result["indexing"] = indexing
        return result


__all__ = ["NewDatasetDialog"]
