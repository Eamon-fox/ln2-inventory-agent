from datetime import datetime
import os
from contextlib import suppress
from PySide6.QtCore import Qt, Signal, QEvent, QMimeData, QRect, QEasingCurve, QPropertyAnimation, QTimer, QSize
from PySide6.QtGui import QColor, QDrag, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QScrollArea,
    QSizePolicy, QGroupBox, QMenu, QStackedWidget, QButtonGroup,
    QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate, QStyle, QApplication,
    QDialog, QDialogButtonBox, QDateEdit
)
from app_gui.ui.utils import cell_color, build_color_palette
from lib.position_fmt import pos_to_display, box_to_display, get_box_count
from lib.csv_export import build_export_rows
from app_gui.ui.theme import (
    cell_occupied_style,
    cell_empty_style,
    resolve_theme_token,
    FONT_SIZE_CELL,
)
from app_gui.i18n import tr, t
from app_gui.ui.icons import get_icon, Icons
from app_gui.ui import overview_panel_filters as _ov_filters
from app_gui.ui import overview_panel_interactions as _ov_interactions
from app_gui.ui import overview_panel_zoom as _ov_zoom

MIME_TYPE_MOVE = "application/x-ln2-move"
TABLE_ROW_TINT_ROLE = Qt.UserRole + 41
_MONKEYPATCH_EXPORTS = (QMenu, FONT_SIZE_CELL)


class _OverviewTableTintDelegate(QStyledItemDelegate):
    """Paint row-level color tint for table view cells."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        # Keep selected row highlight from theme unchanged.
        if option.state & QStyle.State_Selected:
            return

        tint_hex = index.data(TABLE_ROW_TINT_ROLE)
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


class CellButton(QPushButton):
    doubleClicked = Signal(int, int)
    dropReceived = Signal(int, int, int, int, int)

    def __init__(self, text, box, pos, parent=None):
        super().__init__(text, parent)
        self.box = box
        self.pos = pos
        self.record_id = None
        self.setAcceptDrops(True)
        self._drag_start_pos = None
        # Keep hover feedback snappy; long animations feel laggy in dense grids.
        self._hover_duration_ms = 80
        self._hover_scale = 1.08
        self._base_rect = QRect()
        self._is_hovered = False
        self._hover_anim = None
        self._hover_anim_on_finished = None
        self._hover_proxy = None

    def set_record_id(self, record_id):
        self.record_id = record_id

    def _scaled_rect(self):
        if not self._base_rect.isValid() or self._base_rect.width() <= 0 or self._base_rect.height() <= 0:
            return QRect()
        width = max(1, int(round(self._base_rect.width() * self._hover_scale)))
        height = max(1, int(round(self._base_rect.height() * self._hover_scale)))
        dx = (width - self._base_rect.width()) // 2
        dy = (height - self._base_rect.height()) // 2
        return QRect(self._base_rect.x() - dx, self._base_rect.y() - dy, width, height)

    def _ensure_hover_proxy(self):
        if self._hover_proxy is not None:
            return self._hover_proxy
        parent = self.parentWidget() or self
        proxy = QPushButton(parent)
        proxy.setObjectName("OverviewCellHoverProxy")
        proxy.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        proxy.setFocusPolicy(Qt.NoFocus)
        proxy.hide()
        self._hover_anim = QPropertyAnimation(proxy, b"geometry", proxy)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.finished.connect(self._on_hover_animation_finished)
        self._hover_proxy = proxy
        return proxy

    def _on_hover_animation_finished(self):
        callback = self._hover_anim_on_finished
        self._hover_anim_on_finished = None
        if callback is not None:
            callback()

    def _sync_hover_proxy(self):
        proxy = self._ensure_hover_proxy()
        proxy.setText(self.text())
        proxy.setStyleSheet(self.styleSheet())
        proxy.setToolTip(self.toolTip())
        proxy.setFont(self.font())
        proxy.setGeometry(self._base_rect)

    def _animate_proxy_to(self, rect, on_finished=None):
        proxy = self._hover_proxy
        if proxy is None or not rect.isValid():
            if on_finished is not None:
                on_finished()
            return
        animation = self._hover_anim
        if animation is None:
            self._ensure_hover_proxy()
            animation = self._hover_anim
        if animation is None:
            if on_finished is not None:
                on_finished()
            return
        animation.stop()
        self._hover_anim_on_finished = on_finished
        animation.setDuration(self._hover_duration_ms)
        animation.setStartValue(proxy.geometry())
        animation.setEndValue(rect)
        animation.start()

    def reset_hover_state(self, clear_base=False):
        if self._hover_anim is not None:
            self._hover_anim.stop()
        self._hover_anim_on_finished = None
        self._is_hovered = False
        if self._hover_proxy is not None:
            self._hover_proxy.hide()
        if clear_base:
            self._base_rect = QRect()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.box, self.pos)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self.start_hover_visual()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.stop_hover_visual()
        super().leaveEvent(event)

    def start_hover_visual(self):
        if not self.isVisible():
            return
        self._is_hovered = True
        rect = self.geometry()
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            self._base_rect = QRect(rect)
        else:
            return
        self._sync_hover_proxy()
        self._hover_proxy.show()
        self._hover_proxy.raise_()
        target = self._scaled_rect()
        if target.isValid():
            self._animate_proxy_to(target)

    def stop_hover_visual(self):
        self._is_hovered = False
        proxy = self._hover_proxy
        if proxy is None:
            return
        # Avoid animating shrink-out on leave; many concurrent leave animations
        # cause perceived input lag when moving quickly across cells.
        if self._hover_anim is not None:
            self._hover_anim.stop()
        self._hover_anim_on_finished = None
        proxy.hide()

    def hideEvent(self, event):
        self.reset_hover_state()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None or self.record_id is None:
            super().mouseMoveEvent(event)
            return

        if (event.pos() - self._drag_start_pos).manhattanLength() < 20:
            super().mouseMoveEvent(event)
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE_MOVE, f"{self.box}:{self.pos}:{self.record_id}".encode())
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)
        self._drag_start_pos = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            data = bytes(event.mimeData().data(MIME_TYPE_MOVE)).decode()
            parts = data.split(":")
            if len(parts) == 3:
                from_box = int(parts[0])
                from_pos = int(parts[1])
                record_id = int(parts[2])
                self.dropReceived.emit(from_box, from_pos, self.box, self.pos, record_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

class OverviewPanel(QWidget):
    status_message = Signal(str, int)
    request_prefill = Signal(dict)
    request_prefill_background = Signal(dict)
    request_quick_add = Signal()
    request_add_prefill = Signal(dict)
    request_add_prefill_background = Signal(dict)
    request_move_prefill = Signal(dict)
    # Use object to preserve non-string dict keys (Qt map coercion can drop int keys).
    data_loaded = Signal(object)
    plan_items_requested = Signal(list)
    # Statistics update for status bar
    stats_changed = Signal(dict)  # {"total": n, "occupied": n, "empty": n, "rate": pct}
    hover_stats_changed = Signal(str)  # Formatted string for hovered cell

    def __init__(self, bridge, yaml_path_getter):
        super().__init__()
        self.setObjectName("OverviewPanel")
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter

        # State
        self.overview_shape = None
        self.overview_cells = {}
        self.overview_pos_map = {}
        self.overview_box_live_labels = {}
        self.overview_box_groups = {}
        self.overview_selected_key = None
        self.overview_hover_key = None
        self.overview_records_by_id = {}
        self._current_records = []
        self._current_font_sizes = (9, 8)
        self._overview_view_mode = "grid"
        self._table_rows = []
        self._table_columns = []
        self._table_row_records = []
        self._hover_warmed = False
        self._show_summary_cards = True  # Can be set to False to hide cards
        self._column_filters = {}  # {column_name: filter_config}

        # Animation objects for smooth zoom and scroll transitions
        self._zoom_animation = None
        self._scroll_h_animation = None
        self._scroll_v_animation = None

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        # Summary Cards (can be hidden via _show_summary_cards)
        self._summary_row = QHBoxLayout()
        self._summary_row.setSpacing(6)

        self.ov_total_records_value = self._build_card(self._summary_row, tr("overview.totalRecords"))
        self.ov_occupied_value = self._build_card(self._summary_row, tr("overview.occupied"))
        self.ov_empty_value = self._build_card(self._summary_row, tr("overview.empty"))
        self.ov_rate_value = self._build_card(self._summary_row, tr("overview.occupancyRate"))

        self._summary_container = QWidget()
        self._summary_container.setLayout(self._summary_row)
        self._summary_container.setVisible(self._show_summary_cards)
        layout.addWidget(self._summary_container)

        # Filter Row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel(tr("overview.search")))

        self.ov_filter_keyword = QLineEdit()
        self.ov_filter_keyword.setPlaceholderText(tr("overview.searchPlaceholder"))
        self.ov_filter_keyword.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.ov_filter_keyword, 2)

        # More filters button with icon
        self.ov_filter_toggle_btn = QPushButton(tr("overview.moreFilters"))
        self.ov_filter_toggle_btn.setIcon(get_icon(Icons.CHEVRON_DOWN))
        self.ov_filter_toggle_btn.setIconSize(QSize(12, 12))
        self.ov_filter_toggle_btn.setCheckable(True)
        self.ov_filter_toggle_btn.toggled.connect(self.on_toggle_filters)
        filter_row.addWidget(self.ov_filter_toggle_btn)
        layout.addLayout(filter_row)

        # Advanced Filters
        advanced_filter_row = QHBoxLayout()
        advanced_filter_row.setSpacing(6)

        self.ov_filter_box = QComboBox()
        self.ov_filter_box.addItem(tr("overview.allBoxes"), None)
        self.ov_filter_box.currentIndexChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_box)

        self.ov_filter_cell = QComboBox()
        self.ov_filter_cell.addItem(tr("overview.allCells"), None)
        self.ov_filter_cell.currentIndexChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_cell, 1)

        self.ov_filter_show_empty = QCheckBox(tr("overview.showEmpty"))
        self.ov_filter_show_empty.setChecked(True)
        self.ov_filter_show_empty.stateChanged.connect(self._apply_filters)
        advanced_filter_row.addWidget(self.ov_filter_show_empty)

        # Clear filter button with icon
        clear_filter_btn = QPushButton(tr("overview.clearFilter"))
        clear_filter_btn.setIcon(get_icon(Icons.X))
        clear_filter_btn.setIconSize(QSize(14, 14))
        clear_filter_btn.clicked.connect(self.on_clear_filters)
        advanced_filter_row.addWidget(clear_filter_btn)
        advanced_filter_row.addStretch()

        self.ov_filter_advanced_widget = QWidget()
        self.ov_filter_advanced_widget.setLayout(advanced_filter_row)
        self.ov_filter_advanced_widget.setVisible(False)
        layout.addWidget(self.ov_filter_advanced_widget)

        self.ov_status = QLabel(tr("overview.statusReady"))
        layout.addWidget(self.ov_status)

        self.ov_hover_hint = QLabel(tr("overview.hoverHint"))
        self.ov_hover_hint.setObjectName("overviewHoverHint")
        self.ov_hover_hint.setProperty("state", "default")
        self.ov_hover_hint.setWordWrap(True)
        layout.addWidget(self.ov_hover_hint)

        # Combined Action Row: Refresh + View Toggle + Box Navigation + Zoom Controls
        # This row is placed right above the view stack for better space efficiency
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        # Refresh button with icon
        refresh_btn = QPushButton(tr("overview.refresh"))
        refresh_btn.setIcon(get_icon(Icons.REFRESH_CW))
        refresh_btn.setIconSize(QSize(16, 16))
        refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(refresh_btn)

        # View mode toggle buttons (segmented control style) with icons
        view_toggle_container = QWidget()
        view_toggle_container.setObjectName("overviewViewToggle")
        view_toggle_container.setAttribute(Qt.WA_StyledBackground, True)
        view_toggle_layout = QHBoxLayout(view_toggle_container)
        view_toggle_layout.setContentsMargins(0, 0, 0, 0)
        view_toggle_layout.setSpacing(0)

        self._view_mode_group = QButtonGroup(self)
        self._view_mode_group.setExclusive(True)

        # Grid view button with icon only (no text)
        self.ov_view_grid_btn = QPushButton()
        self.ov_view_grid_btn.setIconSize(QSize(18, 18))
        self.ov_view_grid_btn.setToolTip(tr("overview.viewGrid"))
        self.ov_view_grid_btn.setCheckable(True)
        self.ov_view_grid_btn.setChecked(True)
        self.ov_view_grid_btn.setProperty("segmented", "left")
        self.ov_view_grid_btn.setFocusPolicy(Qt.NoFocus)
        self._view_mode_group.addButton(self.ov_view_grid_btn)
        self.ov_view_grid_btn.clicked.connect(lambda: self._on_view_mode_changed("grid"))
        self.ov_view_grid_btn.toggled.connect(lambda: self._update_view_toggle_icons())
        view_toggle_layout.addWidget(self.ov_view_grid_btn)

        # Table view button with icon only (no text)
        self.ov_view_table_btn = QPushButton()
        self.ov_view_table_btn.setIconSize(QSize(18, 18))
        self.ov_view_table_btn.setToolTip(tr("overview.viewTable"))
        self.ov_view_table_btn.setCheckable(True)
        self.ov_view_table_btn.setProperty("segmented", "right")
        self.ov_view_table_btn.setFocusPolicy(Qt.NoFocus)
        self._view_mode_group.addButton(self.ov_view_table_btn)
        self.ov_view_table_btn.clicked.connect(lambda: self._on_view_mode_changed("table"))
        self.ov_view_table_btn.toggled.connect(lambda: self._update_view_toggle_icons())
        view_toggle_layout.addWidget(self.ov_view_table_btn)

        # Set initial icons
        self._update_view_toggle_icons()

        action_row.addWidget(view_toggle_container)

        # Box quick navigation (populated after refresh)
        self._box_nav_container = QWidget()
        self._box_nav_layout = QHBoxLayout(self._box_nav_container)
        self._box_nav_layout.setContentsMargins(0, 0, 0, 0)
        self._box_nav_layout.setSpacing(2)
        action_row.addWidget(self._box_nav_container)

        action_row.addStretch()

        # Zoom controls - unified component with smart zoom features
        self._zoom_level = 1.0
        self._base_cell_size = 36  # recalculated on refresh

        self._zoom_container = QWidget()
        self._zoom_container.setObjectName("zoomControls")
        zoom_layout = QHBoxLayout(self._zoom_container)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(4)

        # Manual zoom controls with icons
        zoom_out_btn = QPushButton()
        zoom_out_btn.setIcon(get_icon(Icons.ZOOM_OUT))
        zoom_out_btn.setIconSize(QSize(16, 16))
        zoom_out_btn.setFixedSize(28, 28)
        zoom_out_btn.setObjectName("overviewIconButton")
        zoom_out_btn.setToolTip(tr("overview.zoomOut"))
        zoom_out_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level - 0.1))
        zoom_layout.addWidget(zoom_out_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("overviewZoomLabel")
        self._zoom_label.setFixedWidth(42)
        self._zoom_label.setAlignment(Qt.AlignCenter)
        zoom_layout.addWidget(self._zoom_label)

        zoom_in_btn = QPushButton()
        zoom_in_btn.setIcon(get_icon(Icons.ZOOM_IN))
        zoom_in_btn.setIconSize(QSize(16, 16))
        zoom_in_btn.setFixedSize(28, 28)
        zoom_in_btn.setObjectName("overviewIconButton")
        zoom_in_btn.setToolTip(tr("overview.zoomIn"))
        zoom_in_btn.clicked.connect(lambda: self._set_zoom(self._zoom_level + 0.1))
        zoom_layout.addWidget(zoom_in_btn)

        # Separator
        separator = QLabel("|")
        separator.setObjectName("overviewZoomSeparator")
        zoom_layout.addWidget(separator)

        # Smart zoom: Fit One Box (expand/maximize single box to 90% viewport)
        fit_one_btn = QPushButton()
        fit_one_btn.setIcon(get_icon(Icons.MAXIMIZE))
        fit_one_btn.setIconSize(QSize(16, 16))
        fit_one_btn.setFixedSize(28, 28)
        fit_one_btn.setObjectName("overviewIconButton")
        fit_one_btn.setToolTip(tr("overview.fitOneBox"))
        fit_one_btn.clicked.connect(self._fit_one_box)
        zoom_layout.addWidget(fit_one_btn)

        # Smart zoom: Fit All Boxes (collapse/minimize to show all boxes in viewport)
        fit_all_btn = QPushButton()
        fit_all_btn.setIcon(get_icon(Icons.MINIMIZE))
        fit_all_btn.setIconSize(QSize(16, 16))
        fit_all_btn.setFixedSize(28, 28)
        fit_all_btn.setObjectName("overviewIconButton")
        fit_all_btn.setToolTip(tr("overview.fitAllBoxes"))
        fit_all_btn.clicked.connect(self._fit_all_boxes)
        zoom_layout.addWidget(fit_all_btn)

        action_row.addWidget(self._zoom_container)

        layout.addLayout(action_row)

        # Grid Area
        self.ov_scroll = QScrollArea()
        self.ov_scroll.setWidgetResizable(True)
        self.ov_scroll.installEventFilter(self)
        self.ov_boxes_widget = QWidget()
        self.ov_boxes_layout = QGridLayout(self.ov_boxes_widget)
        self.ov_boxes_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.ov_boxes_layout.setContentsMargins(0, 0, 0, 0)
        self.ov_boxes_layout.setHorizontalSpacing(4)
        self.ov_boxes_layout.setVerticalSpacing(6)
        self.ov_scroll.setWidget(self.ov_boxes_widget)

        # Table Area
        self.ov_table = QTableWidget()
        self.ov_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ov_table.verticalHeader().setVisible(False)
        self.ov_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ov_table.setSelectionMode(QTableWidget.SingleSelection)
        self.ov_table.setItemDelegate(_OverviewTableTintDelegate(self.ov_table))
        self.ov_table.cellClicked.connect(self.on_table_row_double_clicked)

        # Replace horizontal header with filterable header
        self.ov_table_header = _FilterableHeaderView(Qt.Horizontal, self.ov_table)
        self.ov_table.setHorizontalHeader(self.ov_table_header)
        self.ov_table_header.filterClicked.connect(self._on_column_filter_clicked)

        self.ov_view_stack = QStackedWidget()
        self.ov_view_stack.addWidget(self.ov_scroll)  # grid
        self.ov_view_stack.addWidget(self.ov_table)   # table
        layout.addWidget(self.ov_view_stack, 1)

    def _build_card(self, layout, title):
        card = QGroupBox(title)
        card.setObjectName("overviewStatCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        value_label = QLabel("-")
        value_label.setObjectName("overviewStatValue")
        value_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(value_label)
        layout.addWidget(card)
        return value_label

    def _is_dark_theme(self):
        """Detect if current theme is dark based on palette."""
        app = QApplication.instance()
        if app is None:
            return True
        window = app.palette().color(QPalette.Window)
        return window.lightness() < 128

    def _update_view_toggle_icons(self):
        """Update view toggle button icons based on checked state and theme."""
        is_dark = self._is_dark_theme()
        mode = "dark" if is_dark else "light"

        # Unchecked buttons use theme color (black for light, white for dark)
        # Checked buttons always use white (because of blue background)
        unchecked_color = resolve_theme_token("icon-default", mode=mode, fallback="#ffffff" if is_dark else "#000000")
        checked_color = resolve_theme_token("icon-on-primary", mode=mode, fallback="#ffffff")

        # Update grid button icon
        grid_color = checked_color if self.ov_view_grid_btn.isChecked() else unchecked_color
        self.ov_view_grid_btn.setIcon(get_icon(Icons.GRID_3X3, size=18, color=grid_color))

        # Update table button icon
        table_color = checked_color if self.ov_view_table_btn.isChecked() else unchecked_color
        self.ov_view_table_btn.setIcon(get_icon(Icons.TABLE, size=18, color=table_color))

    def _on_view_mode_changed(self, mode):
        if mode not in {"grid", "table"}:
            mode = "grid"

        # Update button states
        self.ov_view_grid_btn.setChecked(mode == "grid")
        self.ov_view_table_btn.setChecked(mode == "table")

        # Update icons based on checked state
        self._update_view_toggle_icons()

        self._overview_view_mode = mode
        self.ov_view_stack.setCurrentIndex(0 if mode == "grid" else 1)

        is_table_mode = mode == "table"
        self.ov_filter_show_empty.setEnabled(not is_table_mode)
        self.ov_filter_show_empty.setToolTip(
            tr("overview.showEmptyGridOnly") if is_table_mode else ""
        )

        # Show/hide zoom controls and box navigation based on view mode
        # Only show in grid mode, hide in table mode
        is_grid_mode = mode == "grid"
        self._zoom_container.setVisible(is_grid_mode)
        self._box_nav_container.setVisible(is_grid_mode)

        self._apply_filters()

    def _set_table_columns(self, headers):
        self.ov_table.setRowCount(0)
        self.ov_table.setColumnCount(len(headers))
        self.ov_table.setHorizontalHeaderLabels(headers)
        header = self.ov_table.horizontalHeader()
        # Enable interactive column resizing
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Make header sections movable (optional, allows reordering columns)
        header.setSectionsMovable(False)  # Keep columns in fixed order for now
        # Enable click-to-sort on column headers
        header.setSectionsClickable(True)
        # Disable sorting during data population (will be enabled after)
        self.ov_table.setSortingEnabled(False)

        # Set reasonable default column widths
        default_widths = {
            "id": 60,
            "location": 80,
            "frozen_at": 100,
            "thaw_events": 200,
            "cell_line": 100,
            "note": 180,
            "short_name": 150,
        }
        for idx, col_name in enumerate(headers):
            if col_name in default_widths:
                self.ov_table.setColumnWidth(idx, default_widths[col_name])
            else:
                # Default width for custom fields
                self.ov_table.setColumnWidth(idx, 120)

    def _rebuild_table_rows(self, records):
        meta = getattr(self, "_current_meta", {})
        from lib.custom_fields import get_color_key

        payload = build_export_rows(records or [], meta=meta)
        self._table_columns = list(payload.get("columns") or [])

        color_key = get_color_key(meta)
        rows = []
        for values in payload.get("rows") or []:
            rid_raw = values.get("id")
            record = None
            if rid_raw not in (None, ""):
                try:
                    record = self.overview_records_by_id.get(int(rid_raw))
                except (TypeError, ValueError):
                    record = None

            # Get box from record (not from values, since we merged box:position into location)
            box_number = None
            if isinstance(record, dict):
                with suppress(TypeError, ValueError):
                    box_number = int(record.get("box"))

            color_value = ""
            if isinstance(record, dict):
                color_value = str(record.get(color_key) or "")
            elif color_key in values:
                color_value = str(values.get(color_key) or "")

            search_text = " ".join(str(values.get(col, "")) for col in self._table_columns).lower()
            rows.append(
                {
                    "values": values,
                    "record": record,
                    "box": box_number,
                    "color_value": color_value,
                    "search_text": search_text,
                }
            )

        self._table_rows = rows
        self._set_table_columns(self._table_columns)
        self._table_row_records = []

    def _render_table_rows(self, rows):
        # Disable sorting during data population for performance
        self.ov_table.setSortingEnabled(False)
        self.ov_table.setRowCount(0)
        self._table_row_records = []

        # Custom role for storing record reference in each row
        RECORD_ROLE = Qt.UserRole + 100

        for row_index, row_data in enumerate(rows):
            self.ov_table.insertRow(row_index)
            values = row_data.get("values") or {}
            color_value = str(row_data.get("color_value") or "")
            row_tint = cell_color(color_value or None)
            record = row_data.get("record")

            for col_index, column in enumerate(self._table_columns):
                value = values.get(column, "")
                item = QTableWidgetItem(str(value))
                item.setData(TABLE_ROW_TINT_ROLE, row_tint)

                # Store record reference in first column for easy retrieval after sorting
                if col_index == 0:
                    item.setData(RECORD_ROLE, record)

                # Set numeric data for proper sorting of numeric columns
                if column == "id":
                    with suppress(ValueError, TypeError):
                        item.setData(Qt.UserRole, int(value))
                elif column == "location":
                    # Parse "box:position" for sorting (e.g., "1:2" -> 1002)
                    try:
                        parts = str(value).split(":")
                        if len(parts) == 2:
                            box, pos = int(parts[0]), int(parts[1])
                            # Create sortable key: box * 1000 + position
                            item.setData(Qt.UserRole, box * 1000 + pos)
                    except (ValueError, TypeError):
                        pass

                self.ov_table.setItem(row_index, col_index, item)
            self._table_row_records.append(record)

        # Enable sorting after data is populated
        self.ov_table.setSortingEnabled(True)

    def on_table_row_double_clicked(self, row, _col):
        if row < 0 or row >= self.ov_table.rowCount():
            return

        # Get record from first column item (works even after sorting)
        RECORD_ROLE = Qt.UserRole + 100
        first_item = self.ov_table.item(row, 0)
        if not first_item:
            return

        record = first_item.data(RECORD_ROLE)
        if not isinstance(record, dict):
            return

        position = record.get("position")
        if position is None:
            return

        try:
            record_id = int(record.get("id"))
            box_num = int(record.get("box"))
            position = int(position)
        except (TypeError, ValueError):
            return

        self._set_selected_cell(box_num, position)
        self._emit_takeout_prefill_background(box_num, position, record_id)

    def _emit_takeout_prefill_background(self, box_num, position, record_id):
        payload = {
            "box": int(box_num),
            "position": int(position),
            "record_id": int(record_id),
        }
        self.request_prefill_background.emit(payload)
        self.status_message.emit(t("overview.prefillTakeoutAuto", id=payload["record_id"]), 2000)

    def _emit_add_prefill_background(self, box_num, position):
        payload = {
            "box": int(box_num),
            "position": int(position),
        }
        self.request_add_prefill_background.emit(payload)
        self.status_message.emit(
            t("overview.prefillAddAuto", box=payload["box"], position=payload["position"]),
            2000,
        )

    def _emit_add_prefill(self, box_num, position):
        payload = {
            "box": int(box_num),
            "position": int(position),
        }
        self.request_add_prefill.emit(payload)
        self.status_message.emit(
            t("overview.prefillAdd", box=payload["box"], position=payload["position"]),
            2000,
        )

    def eventFilter(self, obj, event):
        # Ctrl+Wheel zoom on scroll area
        if obj is self.ov_scroll and event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._set_zoom(self._zoom_level + 0.1)
            elif delta < 0:
                self._set_zoom(self._zoom_level - 0.1)
            return True  # consume event
        if event.type() in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
            box_num = obj.property("overview_box")
            position = obj.property("overview_position")
            if box_num is not None and position is not None:
                self.on_cell_hovered(int(box_num), int(position))
        return super().eventFilter(obj, event)


    _set_zoom = _ov_zoom._set_zoom
    _apply_zoom = _ov_zoom._apply_zoom
    _animate_scroll_to = _ov_zoom._animate_scroll_to
    _calc_fit_zoom = staticmethod(_ov_zoom._calc_fit_zoom)
    _calc_center_scroll_targets = staticmethod(_ov_zoom._calc_center_scroll_targets)
    _schedule_center_scroll = _ov_zoom._schedule_center_scroll
    _fit_one_box = _ov_zoom._fit_one_box
    _fit_all_boxes = _ov_zoom._fit_all_boxes
    _update_box_navigation = _ov_zoom._update_box_navigation
    _jump_to_box = _ov_zoom._jump_to_box

    def _repaint_all_cells(self):
        """Repaint all cell buttons using cached data."""
        records = getattr(self, "_current_records", [])
        record_map = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            box = rec.get("box")
            pos = rec.get("position")
            if box is not None and pos is not None:
                record_map[(box, pos)] = rec
        for (box_num, position), button in self.overview_cells.items():
            record = record_map.get((box_num, position))
            self._paint_cell(button, box_num, position, record)

    def _warm_hover_animation(self):
        """Pre-create hover proxy and animation to eliminate first-hover cold-start delay.

        Called once after initial data load via QTimer to avoid blocking UI render.
        Finds the first visible CellButton and creates its hover proxy/animation,
        which warms up Qt's QPropertyAnimation and style parsing subsystems.
        """
        if self._hover_warmed or not self.overview_cells:
            return
        self._hover_warmed = True

        # Pick a representative cell (first visible one) to warm the animation system.
        for button in self.overview_cells.values():
            if isinstance(button, CellButton) and button.isVisible():
                # Trigger proxy and animation creation without showing anything.
                button._ensure_hover_proxy()
                # Pre-warm animation with a no-op to initialize QPropertyAnimation internals.
                if button._hover_anim is not None:
                    button._hover_anim.setDuration(1)
                    button._hover_anim.setStartValue(QRect(0, 0, 1, 1))
                    button._hover_anim.setEndValue(QRect(0, 0, 1, 1))
                    button._hover_anim.start()
                    button._hover_anim.stop()
                break

    def refresh(self):
        yaml_path = self.yaml_path_getter()
        self.ov_status.setText(tr("overview.statusLoading"))
        if not yaml_path or not os.path.isfile(yaml_path):
            self.ov_status.setText(t("main.fileNotFound", path=yaml_path or ""))
            self.overview_records_by_id = {}
            self.overview_selected_key = None
            self._reset_detail()
            return

        stats_response = self.bridge.generate_stats(yaml_path)
        if not stats_response.get("ok"):
            self.ov_status.setText(t("overview.loadFailed", error=stats_response.get('message', 'unknown error')))
            self.overview_records_by_id = {}
            self.overview_selected_key = None
            self._reset_detail()
            return

        payload = stats_response.get("result", {})
        data = payload.get("data", {})
        records = data.get("inventory", [])
        self._current_meta = data.get("meta", {})
        self._current_records = records

        # Build color palette from meta
        from lib.custom_fields import get_color_key_options
        build_color_palette(get_color_key_options(self._current_meta))
        
        self.overview_records_by_id = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            with suppress(ValueError, TypeError):
                self.overview_records_by_id[int(rec.get("id"))] = rec
        
        self.data_loaded.emit(self.overview_records_by_id)

        layout = payload.get("layout", {})
        stats = payload.get("stats", {})
        overall = stats.get("overall", {})
        box_stats = stats.get("boxes", {})

        rows = int(layout.get("rows", 9))
        cols = int(layout.get("cols", 9))
        self._current_layout = layout
        box_numbers = sorted([int(k) for k in box_stats], key=int)
        if not box_numbers:
            box_count = get_box_count(layout)
            box_numbers = list(range(1, box_count + 1))

        shape = (rows, cols, tuple(box_numbers))
        if self.overview_shape != shape:
            self._rebuild_boxes(rows, cols, box_numbers)

        pos_map = {}
        for rec in records:
            box = rec.get("box")
            pos = rec.get("position")
            if box is None or pos is None:
                continue
            pos_map[(int(box), int(pos))] = rec

        self.overview_pos_map = pos_map

        total_records = len(records)
        total_occupied = overall.get("total_occupied", 0)
        total_empty = overall.get("total_empty", 0)
        occupancy_rate = overall.get("occupancy_rate", 0)
        self.ov_total_records_value.setText(str(total_records))
        self.ov_occupied_value.setText(str(total_occupied))
        self.ov_empty_value.setText(str(total_empty))
        self.ov_rate_value.setText(f"{occupancy_rate:.1f}%")

        # Emit stats for status bar
        self.stats_changed.emit({
            "total": total_records,
            "occupied": total_occupied,
            "empty": total_empty,
            "rate": occupancy_rate,
        })

        if len(records) == 0:
            self.ov_hover_hint.setText(tr("overview.emptyHint"))
            self.ov_hover_hint.setProperty("state", "warning")
            self.ov_hover_hint.style().unpolish(self.ov_hover_hint)
            self.ov_hover_hint.style().polish(self.ov_hover_hint)
        else:
            self.ov_hover_hint.setText(tr("overview.hoverHint"))
            self.ov_hover_hint.setProperty("state", "default")
            self.ov_hover_hint.style().unpolish(self.ov_hover_hint)
            self.ov_hover_hint.style().polish(self.ov_hover_hint)

        for box_num in box_numbers:
            stats_item = box_stats.get(str(box_num), {})
            occupied = stats_item.get("occupied", 0)
            empty = stats_item.get("empty", rows * cols)
            total = stats_item.get("total", rows * cols)
            live = self.overview_box_live_labels.get(box_num)
            if live is not None:
                live.setText(t("overview.occupiedCount", occupied=occupied, total=total, empty=empty))

        for key, button in self.overview_cells.items():
            box_num, position = key
            rec = pos_map.get(key)
            self._paint_cell(button, box_num, position, rec)

        self._rebuild_table_rows(records)
        self._refresh_filter_options(records, box_numbers)
        self._apply_filters()

        self.ov_status.setText(
            t("overview.loadedStatus", count=len(records), time=datetime.now().strftime("%H:%M:%S"))
        )

        # Update box navigation buttons
        self._update_box_navigation(box_numbers)

        # Warm hover animation system after initial UI render to eliminate first-hover delay.
        if not self._hover_warmed and self.overview_cells:
            QTimer.singleShot(50, self._warm_hover_animation)

    def _rebuild_boxes(self, rows, cols, box_numbers):
        # clear layout
        while self.ov_boxes_layout.count():
            item = self.ov_boxes_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.overview_cells = {}
        self.overview_box_live_labels = {}
        self.overview_box_groups = {}
        self.overview_selected_key = None
        self._reset_detail()

        layout = getattr(self, "_current_layout", {})
        total_slots = rows * cols
        # Base cell size scaled with FONT_SIZE_CELL increase for better readability
        self._base_cell_size = max(30, min(45, 375 // max(rows, cols)))
        cell_size = max(12, int(self._base_cell_size * self._zoom_level))
        columns = 3
        for idx, box_num in enumerate(box_numbers):
            box_label = box_to_display(box_num, layout)
            group = QGroupBox(t("overview.boxLabel", box=box_label))
            group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            group_layout.setSpacing(4)

            live_label = QLabel(t("overview.occupiedCount", occupied=0, total=total_slots, empty=total_slots))
            group_layout.addWidget(live_label)
            self.overview_box_live_labels[box_num] = live_label

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(1)
            grid.setVerticalSpacing(1)
            for position in range(1, total_slots + 1):
                r = (position - 1) // cols
                c = (position - 1) % cols
                display_text = pos_to_display(position, layout)
                button = CellButton(display_text, box_num, position)
                button.setFixedSize(cell_size, cell_size)
                button.setMouseTracking(True)
                button.setProperty("overview_box", box_num)
                button.setProperty("overview_position", position)
                button.installEventFilter(self)
                
                # Single click
                button.clicked.connect(
                    lambda _checked=False, b=box_num, p=position: self.on_cell_clicked(b, p)
                )
                
                # Double click
                button.doubleClicked.connect(self.on_cell_double_clicked)
                
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda point, b=box_num, p=position, btn=button: self.on_cell_context_menu(
                        b, p, btn.mapToGlobal(point)
                    )
                )
                button.dropReceived.connect(self._on_cell_drop)
                self.overview_cells[(box_num, position)] = button
                grid.addWidget(button, r, c)

            group_layout.addLayout(grid)
            self.ov_boxes_layout.addWidget(group, idx // columns, idx % columns)
            self.overview_box_groups[box_num] = group


        self.overview_shape = (rows, cols, tuple(box_numbers))

    def _paint_cell(self, button, box_num, position, record):
        from lib.custom_fields import get_display_key, get_color_key, get_effective_fields, STRUCTURAL_FIELD_KEYS
        is_selected = self.overview_selected_key == (box_num, position)
        layout = getattr(self, "_current_layout", {})
        meta = getattr(self, "_current_meta", {})
        display_pos = pos_to_display(position, layout)
        fs_occ, fs_empty = getattr(self, "_current_font_sizes", (9, 8))
        if record:
            dk = get_display_key(meta)
            ck = get_color_key(meta)
            dk_val = str(record.get(dk) or "")
            ck_val = str(record.get(ck) or "")
            # Scale label truncation with zoom
            max_chars = max(4, int(8 * self._zoom_level))
            label = dk_val[:max_chars] if dk_val else display_pos
            # Color based on color_key field
            color = cell_color(ck_val or None)
            button.setText(label)

            # Dynamic tooltip from effective fields
            cl = record.get("cell_line")
            tt = [
                f"{tr('overview.tooltipId')}: {record.get('id', '-')}",
                f"{tr('overview.tooltipPos')}: {box_num}:{position}",
            ]
            if cl:
                tt.append(f"{tr('overview.tooltipCellLine')}: {cl}")
            note_value = record.get("note")
            if note_value is not None and str(note_value).strip():
                tt.append(f"{tr('operations.note')}: {note_value}")
            for fdef in get_effective_fields(meta):
                fk = fdef["key"]
                fv = record.get(fk)
                if fv is not None and str(fv):
                    tt.append(f"{fdef.get('label', fk)}: {fv}")
            tt.append(f"{tr('overview.tooltipDate')}: {record.get('frozen_at', '-')}")

            button.setToolTip("\n".join(tt))
            button.setStyleSheet(cell_occupied_style(color, is_selected, font_size=fs_occ))
            # Dynamic search text 鈥?include cell_line + all user fields
            parts = [str(record.get("id", "")), str(box_num), str(position),
                     str(record.get("cell_line") or ""),
                     str(record.get("note") or ""),
                     str(record.get("frozen_at") or "")]
            for k, v in record.items():
                if k not in STRUCTURAL_FIELD_KEYS and k != "id":
                    parts.append(str(v or ""))
            button.setProperty("search_text", " ".join(parts).lower())
            button.setProperty("display_key_value", dk_val)
            button.setProperty("color_key_value", ck_val)
            button.setProperty("is_empty", False)
            button.set_record_id(int(record.get("id", 0)))
        else:
            button.setText(display_pos)
            button.setToolTip(t("overview.emptyCellTooltip", box=box_num, position=position))
            button.setStyleSheet(cell_empty_style(is_selected, font_size=fs_empty))
            button.setProperty("search_text", f"empty box {box_num} position {position}".lower())
            button.setProperty("color_key_value", "")
            button.setProperty("is_empty", True)
            button.set_record_id(None)

    def _set_selected_cell(self, box_num, position):
        new_key = (box_num, position)
        old_key = self.overview_selected_key
        if old_key == new_key:
            return

        self.overview_selected_key = new_key
        for key in (old_key, new_key):
            if key is None:
                continue
            button = self.overview_cells.get(key)
            if button is None:
                continue
            rec = self.overview_pos_map.get(key)
            self._paint_cell(button, key[0], key[1], rec)

    def _clear_selected_cell(self):
        key = self.overview_selected_key
        self.overview_selected_key = None
        if key is not None:
            button = self.overview_cells.get(key)
            if button is not None:
                rec = self.overview_pos_map.get(key)
                self._paint_cell(button, key[0], key[1], rec)


    _refresh_filter_options = _ov_filters._refresh_filter_options
    _apply_filters = _ov_filters._apply_filters
    _apply_filters_grid = _ov_filters._apply_filters_grid
    _apply_filters_table = _ov_filters._apply_filters_table
    on_toggle_filters = _ov_filters.on_toggle_filters
    on_clear_filters = _ov_filters.on_clear_filters
    _on_column_filter_clicked = _ov_filters._on_column_filter_clicked
    _detect_column_type = _ov_filters._detect_column_type
    _get_unique_column_values = _ov_filters._get_unique_column_values
    _match_column_filter = _ov_filters._match_column_filter


    on_cell_clicked = _ov_interactions.on_cell_clicked
    on_cell_double_clicked = _ov_interactions.on_cell_double_clicked
    on_cell_hovered = _ov_interactions.on_cell_hovered
    _reset_detail = _ov_interactions._reset_detail
    _normalize_preview_value = staticmethod(_ov_interactions._normalize_preview_value)
    _resolve_preview_values = _ov_interactions._resolve_preview_values
    _emit_hover_stats = _ov_interactions._emit_hover_stats
    _show_detail = _ov_interactions._show_detail
    on_cell_context_menu = _ov_interactions.on_cell_context_menu
    _create_takeout_plan_item = _ov_interactions._create_takeout_plan_item
    _on_cell_drop = _ov_interactions._on_cell_drop

    def set_summary_cards_visible(self, visible):
        """Show or hide the summary cards (used when displaying stats in status bar instead)."""
        self._show_summary_cards = visible
        self._summary_container.setVisible(visible)



