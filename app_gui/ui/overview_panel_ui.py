"""UI construction helpers for OverviewPanel."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon
from app_gui.ui.theme import resolve_theme_token
from app_gui.ui import overview_panel_widgets as _ov_widgets


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
    self.ov_table.setItemDelegate(_ov_widgets._OverviewTableTintDelegate(self.ov_table))
    self.ov_table.cellClicked.connect(self.on_table_row_double_clicked)

    # Replace horizontal header with filterable header
    self.ov_table_header = _ov_widgets._FilterableHeaderView(Qt.Horizontal, self.ov_table)
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
