"""Dialog for box/layout management actions from Settings."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import tr
from app_gui.ui.limits import MAX_BOX_COUNT_UI
from lib.position_fmt import (
    BOX_LAYOUT_INDEXING_VALUES,
    box_tag_text,
    get_box_numbers,
    normalize_box_layout_indexing,
)


class ManageBoxesDialog(QDialog):
    """Collect one structured manage-boxes request."""

    def __init__(self, *, layout=None, parent=None):
        super().__init__(parent)
        self._layout = dict(layout or {})
        self._box_numbers = list(get_box_numbers(self._layout))

        self.setWindowTitle(tr("main.manageBoxes"))
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.action_combo = QComboBox()
        self.action_combo.addItem(tr("main.boxOpAdd"), "add")
        self.action_combo.addItem(tr("main.boxOpRemove"), "remove")
        self.action_combo.addItem(tr("main.boxOpSetTag"), "set_tag")
        self.action_combo.addItem(tr("main.boxOpSetIndexing"), "set_indexing")
        self.action_combo.currentIndexChanged.connect(self._sync_action_page)
        form.addRow(tr("main.boxActionPrompt"), self.action_combo)

        self.stack = QStackedWidget()
        self._page_by_action = {}
        self._page_by_action["add"] = self.stack.addWidget(self._build_add_page())
        self._page_by_action["remove"] = self.stack.addWidget(self._build_remove_page())
        self._page_by_action["set_tag"] = self.stack.addWidget(self._build_tag_page())
        self._page_by_action["set_indexing"] = self.stack.addWidget(self._build_indexing_page())
        form.addRow(self.stack)

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._sync_action_page()
        self._sync_remove_mode_state()
        self._sync_tag_edit()

    def _build_add_page(self):
        page = QWidget(self)
        form = QFormLayout(page)
        self.add_count_spin = QSpinBox(page)
        self.add_count_spin.setRange(1, MAX_BOX_COUNT_UI)
        self.add_count_spin.setValue(1)
        form.addRow(tr("main.boxAddCountPrompt"), self.add_count_spin)
        return page

    def _build_remove_page(self):
        page = QWidget(self)
        form = QFormLayout(page)

        self.remove_box_combo = QComboBox(page)
        for box_num in self._box_numbers:
            self.remove_box_combo.addItem(str(box_num), int(box_num))
        self.remove_box_combo.currentIndexChanged.connect(self._sync_remove_mode_state)
        form.addRow(tr("main.boxRemovePrompt"), self.remove_box_combo)

        self.remove_mode_combo = QComboBox(page)
        self.remove_mode_combo.addItem(tr("main.boxDeleteKeepGaps"), "keep_gaps")
        self.remove_mode_combo.addItem(tr("main.boxDeleteRenumber"), "renumber_contiguous")
        form.addRow(tr("main.boxRemoveModePrompt"), self.remove_mode_combo)

        self.remove_mode_hint = QLabel(tr("main.boxRemoveModeHint"), page)
        self.remove_mode_hint.setWordWrap(True)
        self.remove_mode_hint.setProperty("role", "settingsHint")
        form.addRow("", self.remove_mode_hint)
        return page

    def _build_tag_page(self):
        page = QWidget(self)
        form = QFormLayout(page)

        self.tag_box_combo = QComboBox(page)
        for box_num in self._box_numbers:
            self.tag_box_combo.addItem(str(box_num), int(box_num))
        self.tag_box_combo.currentIndexChanged.connect(self._sync_tag_edit)
        form.addRow(tr("main.boxTagTargetPrompt"), self.tag_box_combo)

        self.tag_edit = QLineEdit(page)
        form.addRow(tr("main.boxTagValueLabel"), self.tag_edit)
        return page

    def _build_indexing_page(self):
        page = QWidget(self)
        form = QFormLayout(page)

        self.indexing_combo = QComboBox(page)
        for indexing in BOX_LAYOUT_INDEXING_VALUES:
            label_key = "main.indexNumeric" if indexing == "numeric" else "main.indexAlpha"
            self.indexing_combo.addItem(tr(label_key), indexing)
        current_indexing = normalize_box_layout_indexing(self._layout.get("indexing"))
        current_index = self.indexing_combo.findData(current_indexing)
        if current_index >= 0:
            self.indexing_combo.setCurrentIndex(current_index)
        form.addRow(tr("main.indexing"), self.indexing_combo)

        hint = QLabel(tr("main.boxIndexingHint"), page)
        hint.setWordWrap(True)
        hint.setProperty("role", "settingsHint")
        form.addRow("", hint)
        return page

    def _selected_box(self, combo):
        data = combo.currentData()
        try:
            return int(data)
        except Exception:
            return None

    def _sync_action_page(self):
        action = str(self.action_combo.currentData() or "add")
        self.stack.setCurrentIndex(self._page_by_action[action])

    def _sync_remove_mode_state(self):
        selected_box = self._selected_box(self.remove_box_combo)
        has_later_boxes = bool(
            selected_box is not None
            and any(int(box_num) > int(selected_box) for box_num in self._box_numbers)
        )
        self.remove_mode_combo.setEnabled(has_later_boxes)
        self.remove_mode_hint.setVisible(has_later_boxes)

    def _sync_tag_edit(self):
        selected_box = self._selected_box(self.tag_box_combo)
        self.tag_edit.setText(box_tag_text(selected_box, self._layout) if selected_box is not None else "")

    def get_request(self):
        action = str(self.action_combo.currentData() or "").strip()
        if action == "add":
            return {"operation": "add", "count": int(self.add_count_spin.value())}
        if action == "remove":
            request = {
                "operation": "remove",
                "box": int(self._selected_box(self.remove_box_combo) or 0),
            }
            if self.remove_mode_combo.isEnabled():
                request["renumber_mode"] = str(self.remove_mode_combo.currentData() or "keep_gaps")
            return request
        if action == "set_tag":
            return {
                "operation": "set_tag",
                "box": int(self._selected_box(self.tag_box_combo) or 0),
                "tag": self.tag_edit.text(),
            }
        if action == "set_indexing":
            return {
                "operation": "set_indexing",
                "indexing": str(self.indexing_combo.currentData() or "numeric"),
            }
        return {}


__all__ = ["ManageBoxesDialog"]
