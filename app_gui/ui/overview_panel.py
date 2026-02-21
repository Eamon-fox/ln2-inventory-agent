from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget, QMenu
from app_gui.ui.theme import FONT_SIZE_CELL
from app_gui.i18n import tr
from app_gui.ui import overview_panel_filters as _ov_filters
from app_gui.ui import overview_panel_grid as _ov_grid
from app_gui.ui import overview_panel_interactions as _ov_interactions
from app_gui.ui import overview_panel_zoom as _ov_zoom
from app_gui.ui import overview_panel_table as _ov_table
from app_gui.ui import overview_panel_widgets as _ov_widgets
from app_gui.ui import overview_panel_cell_button as _ov_cell_button
from app_gui.ui import overview_panel_ui as _ov_ui
from app_gui.ui import overview_panel_refresh as _ov_refresh

MIME_TYPE_MOVE = _ov_cell_button.MIME_TYPE_MOVE
TABLE_ROW_TINT_ROLE = Qt.UserRole + 41
_MONKEYPATCH_EXPORTS = (QMenu, FONT_SIZE_CELL)


_OverviewTableTintDelegate = _ov_widgets._OverviewTableTintDelegate
_FilterableHeaderView = _ov_widgets._FilterableHeaderView
_ColumnFilterDialog = _ov_widgets._ColumnFilterDialog

CellButton = _ov_cell_button.CellButton

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

    setup_ui = _ov_ui.setup_ui
    _build_card = _ov_ui._build_card
    _is_dark_theme = _ov_ui._is_dark_theme
    _update_view_toggle_icons = _ov_ui._update_view_toggle_icons

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


    _set_table_columns = _ov_table._set_table_columns
    _rebuild_table_rows = _ov_table._rebuild_table_rows
    _render_table_rows = _ov_table._render_table_rows
    on_table_row_double_clicked = _ov_table.on_table_row_double_clicked
    _emit_takeout_prefill_background = _ov_table._emit_takeout_prefill_background
    _emit_add_prefill_background = _ov_table._emit_add_prefill_background
    _emit_add_prefill = _ov_table._emit_add_prefill

    _repaint_all_cells = _ov_grid._repaint_all_cells
    _warm_hover_animation = _ov_grid._warm_hover_animation
    _rebuild_boxes = _ov_grid._rebuild_boxes
    _paint_cell = _ov_grid._paint_cell
    _set_selected_cell = _ov_grid._set_selected_cell
    _clear_selected_cell = _ov_grid._clear_selected_cell

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

    refresh = _ov_refresh.refresh

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
