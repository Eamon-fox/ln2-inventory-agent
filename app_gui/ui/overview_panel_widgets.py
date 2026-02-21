"""Reusable widget classes for OverviewPanel."""

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon
from app_gui.ui.theme import resolve_theme_token


class _OverviewTableTintDelegate(QStyledItemDelegate):
    """Paint row-level color tint for table view cells."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        # Keep selected row highlight from theme unchanged.
        if option.state & QStyle.State_Selected:
            return

        from app_gui.ui import overview_panel as _ov_panel

        tint_hex = index.data(_ov_panel.TABLE_ROW_TINT_ROLE)
        if not tint_hex:
            return

        tint = QColor(str(tint_hex))
        if not tint.isValid():
            return

        tint.setAlpha(128)
        painter.save()
        painter.fillRect(option.rect, tint)
        painter.restore()


class _FilterableHeaderView(QHeaderView):
    """Custom header view with filter icons in each column."""

    filterClicked = Signal(int, str)  # column_index, column_name

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._filtered_columns = set()  # Set of column indices with active filters
        self._hover_section = -1
        self.setMouseTracking(True)
        self.setSectionsClickable(True)

    def set_column_filtered(self, column_index, filtered):
        """Mark a column as filtered or not filtered."""
        if filtered:
            self._filtered_columns.add(column_index)
        else:
            self._filtered_columns.discard(column_index)
        self.viewport().update()

    def paintSection(self, painter, rect, logicalIndex):
        """Paint section with filter icon."""
        super().paintSection(painter, rect, logicalIndex)

        # Draw filter icon on the right side of the header
        icon_size = 14
        icon_margin = 6
        icon_x = rect.right() - icon_size - icon_margin
        icon_y = rect.center().y() - icon_size // 2
        icon_rect = QRect(icon_x, icon_y, icon_size, icon_size)

        # Determine icon color based on filter state
        is_filtered = logicalIndex in self._filtered_columns
        is_hovered = logicalIndex == self._hover_section

        if is_filtered:
            # Blue color for filtered columns
            icon_color = resolve_theme_token("primary", fallback="#3b82f6")
        elif is_hovered:
            # Lighter color on hover
            icon_color = resolve_theme_token("text-primary", fallback="#e5e7eb")
        else:
            # Muted color for normal state
            icon_color = resolve_theme_token("text-muted", fallback="#9ca3af")

        # Draw filter icon
        icon = get_icon(Icons.FILTER, size=icon_size, color=icon_color)
        icon.paint(painter, icon_rect)

    def mouseMoveEvent(self, event):
        """Track hover state for visual feedback."""
        logical_index = self.logicalIndexAt(event.pos())
        if logical_index != self._hover_section:
            self._hover_section = logical_index
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        """Clear hover state when mouse leaves."""
        if self._hover_section != -1:
            self._hover_section = -1
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Handle clicks on filter icons."""
        if event.button() == Qt.LeftButton:
            logical_index = self.logicalIndexAt(event.pos())
            if logical_index >= 0:
                # Check if click is on the filter icon area
                section_rect = self.sectionViewportPosition(logical_index)
                section_width = self.sectionSize(logical_index)
                icon_size = 14
                icon_margin = 6
                icon_x_start = section_rect + section_width - icon_size - icon_margin * 2

                if event.pos().x() >= icon_x_start:
                    # Click on filter icon
                    column_name = self.model().headerData(logical_index, Qt.Horizontal)
                    self.filterClicked.emit(logical_index, str(column_name))
                    return

        super().mousePressEvent(event)


class _ColumnFilterDialog(QDialog):
    """Dialog for filtering a specific column."""

    def __init__(self, parent, column_name, filter_type, unique_values=None, current_filter=None):
        super().__init__(parent)
        self.setWindowTitle(tr("overview.filterColumn").format(column=column_name))
        self.setMinimumWidth(300)
        self.setMinimumHeight(400)

        self.column_name = column_name
        self.filter_type = filter_type
        self.filter_config = current_filter or {}

        layout = QVBoxLayout(self)

        if filter_type == "list":
            self._setup_list_filter(layout, unique_values)
        elif filter_type == "text":
            self._setup_text_filter(layout)
        elif filter_type == "number":
            self._setup_number_filter(layout, unique_values)
        elif filter_type == "date":
            self._setup_date_filter(layout)

        # Buttons
        button_box = QDialogButtonBox()
        clear_btn = button_box.addButton(tr("overview.clearFilter"), QDialogButtonBox.ResetRole)
        clear_btn.clicked.connect(self._on_clear)
        button_box.addButton(QDialogButtonBox.Cancel)
        button_box.addButton(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _setup_list_filter(self, layout, unique_values):
        """Setup list-based filter with checkboxes."""
        # Search box
        search_label = QLabel(tr("overview.search"))
        layout.addWidget(search_label)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("overview.searchPlaceholder"))
        self.search_box.textChanged.connect(self._filter_checkbox_list)
        layout.addWidget(self.search_box)

        # Select all checkbox
        self.select_all_cb = QCheckBox(tr("overview.selectAll"))
        self.select_all_cb.stateChanged.connect(self._on_select_all_changed)
        layout.addWidget(self.select_all_cb)

        # Scrollable checkbox list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.checkbox_layout = QVBoxLayout(scroll_content)
        self.checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self.checkbox_layout.setSpacing(2)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # Create checkboxes for each unique value
        self.value_checkboxes = []
        current_values = set(self.filter_config.get("values", []))

        for value, count in unique_values:
            cb = QCheckBox(f"{value} ({count})")
            cb.setProperty("filter_value", value)
            cb.setChecked(not current_values or value in current_values)
            cb.stateChanged.connect(self._on_checkbox_changed)
            self.checkbox_layout.addWidget(cb)
            self.value_checkboxes.append(cb)

        # Add stretch at the end to push checkboxes to the top
        self.checkbox_layout.addStretch()

        self._update_select_all_state()

    def _setup_text_filter(self, layout):
        """Setup text search filter."""
        label = QLabel(tr("overview.searchText"))
        layout.addWidget(label)

        self.text_input = QLineEdit()
        self.text_input.setText(self.filter_config.get("text", ""))
        self.text_input.setPlaceholderText(tr("overview.enterSearchText"))
        layout.addWidget(self.text_input)

        layout.addStretch()

    def _setup_number_filter(self, layout, unique_values):
        """Setup number range filter."""
        if unique_values and len(unique_values) <= 20:
            # Use list filter for small number of unique values
            self._setup_list_filter(layout, unique_values)
        else:
            # Use range filter
            label = QLabel(tr("overview.numberRange"))
            layout.addWidget(label)

            range_layout = QHBoxLayout()
            self.min_input = QLineEdit()
            self.min_input.setPlaceholderText(tr("overview.min"))
            self.min_input.setText(str(self.filter_config.get("min", "")))
            range_layout.addWidget(self.min_input)

            range_layout.addWidget(QLabel("-"))

            self.max_input = QLineEdit()
            self.max_input.setPlaceholderText(tr("overview.max"))
            self.max_input.setText(str(self.filter_config.get("max", "")))
            range_layout.addWidget(self.max_input)

            layout.addLayout(range_layout)
            layout.addStretch()

    def _setup_date_filter(self, layout):
        """Setup date range filter."""
        label = QLabel(tr("overview.dateRange"))
        layout.addWidget(label)

        range_layout = QHBoxLayout()
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        range_layout.addWidget(self.date_from)

        range_layout.addWidget(QLabel("-"))

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        range_layout.addWidget(self.date_to)

        layout.addLayout(range_layout)
        layout.addStretch()

    def _filter_checkbox_list(self, text):
        """Filter checkbox list based on search text."""
        text = text.lower()
        for cb in self.value_checkboxes:
            value = str(cb.property("filter_value") or "").lower()
            cb.setVisible(not text or text in value)

    def _on_select_all_changed(self, state):
        """Handle select all checkbox state change."""
        checked = state == Qt.Checked
        for cb in self.value_checkboxes:
            if cb.isVisible():
                cb.setChecked(checked)

    def _on_checkbox_changed(self):
        """Handle individual checkbox state change."""
        self._update_select_all_state()

    def _update_select_all_state(self):
        """Update select all checkbox state based on individual checkboxes."""
        visible_checkboxes = [cb for cb in self.value_checkboxes if cb.isVisible()]
        if not visible_checkboxes:
            return

        all_checked = all(cb.isChecked() for cb in visible_checkboxes)
        any_checked = any(cb.isChecked() for cb in visible_checkboxes)

        self.select_all_cb.blockSignals(True)
        if all_checked:
            self.select_all_cb.setCheckState(Qt.Checked)
        elif any_checked:
            self.select_all_cb.setCheckState(Qt.PartiallyChecked)
        else:
            self.select_all_cb.setCheckState(Qt.Unchecked)
        self.select_all_cb.blockSignals(False)

    def _on_clear(self):
        """Clear the filter."""
        self.filter_config = {}
        self.reject()

    def get_filter_config(self):
        """Get the filter configuration."""
        if self.filter_type == "list":
            selected_values = [
                cb.property("filter_value")
                for cb in self.value_checkboxes
                if cb.isChecked()
            ]
            if not selected_values or len(selected_values) == len(self.value_checkboxes):
                return None  # No filter (all selected)
            return {"type": "list", "values": selected_values}

        elif self.filter_type == "text":
            text = self.text_input.text().strip()
            if not text:
                return None
            return {"type": "text", "text": text}

        elif self.filter_type == "number":
            if hasattr(self, "value_checkboxes"):
                # List-based number filter
                selected_values = [
                    cb.property("filter_value")
                    for cb in self.value_checkboxes
                    if cb.isChecked()
                ]
                if not selected_values or len(selected_values) == len(self.value_checkboxes):
                    return None
                return {"type": "list", "values": selected_values}
            else:
                # Range-based number filter
                min_val = self.min_input.text().strip()
                max_val = self.max_input.text().strip()
                if not min_val and not max_val:
                    return None
                return {
                    "type": "number",
                    "min": float(min_val) if min_val else None,
                    "max": float(max_val) if max_val else None,
                }

        elif self.filter_type == "date":
            return {
                "type": "date",
                "from": self.date_from.date().toString("yyyy-MM-dd"),
                "to": self.date_to.date().toString("yyyy-MM-dd"),
            }

        return None
