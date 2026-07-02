from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import QWidget, QMenu
from app_gui.ui.theme import FONT_SIZE_CELL
from app_gui.ui import overview_panel_filters as _ov_filters
from app_gui.ui import overview_panel_grid as _ov_grid
from app_gui.ui import overview_panel_interactions as _ov_interactions
from app_gui.ui import overview_panel_zoom as _ov_zoom
from app_gui.ui import overview_panel_table as _ov_table
from app_gui.ui import overview_panel_widgets as _ov_widgets
from app_gui.ui import overview_panel_cell_button as _ov_cell_button
from app_gui.ui import overview_panel_ui as _ov_ui
from app_gui.ui import overview_panel_refresh as _ov_refresh
from app_gui.ui import overview_panel_runtime as _ov_runtime
from app_gui.ui.table_entry_draft_store import TableEntryDraftStore

# Module map for maintainers.
#
# Behavioral collaborators — OverviewPanel constructs one instance of each and
# delegates to it (composition, not cross-file method binding):
# - _ov_zoom.OverviewZoomController: zoom + box navigation (owns animation objects).
# - _ov_runtime.OverviewRuntimeController: event filter, grid nav, view-mode, filter debounce.
# - _ov_refresh.OverviewRefreshController: read-snapshot data-load pipeline.
# - _ov_filters.OverviewFilterController: grid/table filtering + column filter dialogs.
# - _ov_interactions.OverviewInteractionController: cell click/hover/context-menu, drag-drop.
#
# Still bound as partial-class methods (deep shared-state entanglement / heavy
# test pinning): _ov_grid (grid render + selection state), _ov_table (table render
# + data projection), _ov_ui (widget tree construction).
# Reusable Qt widget classes: _ov_widgets, _ov_cell_button.
MIME_TYPE_MOVE = _ov_cell_button.MIME_TYPE_MOVE
TABLE_ROW_TINT_ROLE = Qt.UserRole + 41
TABLE_ROW_KIND_ROLE = Qt.UserRole + 42
TABLE_ROW_BOX_ROLE = Qt.UserRole + 43
TABLE_ROW_POSITION_ROLE = Qt.UserRole + 44
TABLE_COLUMN_NAME_ROLE = Qt.UserRole + 45
TABLE_EDITOR_KIND_ROLE = Qt.UserRole + 46
TABLE_EDITOR_OPTIONS_ROLE = Qt.UserRole + 47
TABLE_EDITOR_REQUIRED_ROLE = Qt.UserRole + 48
TABLE_ROW_LOCKED_ROLE = Qt.UserRole + 49
TABLE_ROW_CONFIRMED_ROLE = Qt.UserRole + 50
_MONKEYPATCH_EXPORTS = (QMenu, FONT_SIZE_CELL)


_OverviewTableTintDelegate = _ov_widgets._OverviewTableTintDelegate
_FilterableHeaderView = _ov_widgets._FilterableHeaderView
_ColumnFilterDialog = _ov_widgets._ColumnFilterDialog

CellButton = _ov_cell_button.CellButton

class OverviewPanel(QWidget):
    status_message = Signal(str, int)
    operation_event = Signal(dict)
    request_prefill = Signal(dict)
    request_prefill_background = Signal(dict)
    request_quick_add = Signal()
    request_export_inventory_csv = Signal()
    request_add_prefill = Signal(dict)
    request_add_prefill_background = Signal(dict)
    # Use object to preserve non-string dict keys (Qt map coercion can drop int keys).
    data_loaded = Signal(object)
    plan_items_requested = Signal(list)
    plan_item_removal_requested = Signal(list)
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
        self.overview_empty_multi_selected_keys = set()
        self.overview_hover_key = None
        self._overview_selection_anchor_key = None
        self.overview_records_by_id = {}
        self._current_records = []
        self._current_font_sizes = (9, 8)
        self._overview_view_mode = "grid"
        self._grid_include_empty_slots = True
        self._table_include_inactive = False
        self._stats_include_inactive_loaded = False
        self._table_rows = []
        self._table_columns = []
        self._table_data_columns = []
        self._table_header_labels = {}
        self._table_column_types = {}
        self._table_row_records = []
        self._table_draft_by_slot = {}
        self._draft_store = TableEntryDraftStore(parent=self)
        self._table_version = 0
        self._table_sort_by = "location"
        self._table_sort_order = "asc"
        self._ignore_table_sort_change = False
        self._ignore_table_item_change = False
        self._column_unique_cache = {}
        self._hover_warmed = False
        self._show_summary_cards = True  # Can be set to False to hide cards
        self._column_filters = {}  # {column_name: filter_config}
        self._plan_store_ref = None
        self._operation_markers = {}
        self._stats_response_cache = {}
        self._last_stats_cache_key = None
        self._cell_render_signatures = {}
        self._filter_debounce_ms = 120
        self._filter_apply_timer = QTimer(self)
        self._filter_apply_timer.setSingleShot(True)
        self._filter_apply_timer.timeout.connect(self._on_filter_debounce_timeout)

        # Behavioral collaborators. Zoom owns its animation objects; runtime is
        # stateless glue that drives the panel through its reference.
        self._zoom = _ov_zoom.OverviewZoomController(self)
        self._runtime = _ov_runtime.OverviewRuntimeController(self)
        self._refresh = _ov_refresh.OverviewRefreshController(self)
        self._filters = _ov_filters.OverviewFilterController(self)
        self._interactions = _ov_interactions.OverviewInteractionController(self)

        self.setup_ui()

    setup_ui = _ov_ui.setup_ui
    _build_card = _ov_ui._build_card
    _is_dark_theme = _ov_ui._is_dark_theme
    _update_view_toggle_icons = _ov_ui._update_view_toggle_icons
    _position_floating_actions = _ov_ui._position_floating_actions

    # Runtime event/view-mode/filter-debounce glue delegates to ``self._runtime``.
    def _on_view_mode_changed(self, mode):
        return self._runtime._on_view_mode_changed(mode)

    def _emit_export_inventory_csv_request(self, checked=False):
        return self._runtime._emit_export_inventory_csv_request(checked)

    def _on_filter_keyword_changed(self, _text=""):
        return self._runtime._on_filter_keyword_changed(_text)

    def _on_filter_debounce_timeout(self):
        return self._runtime._on_filter_debounce_timeout()


    _resolve_table_header_labels = _ov_table._resolve_table_header_labels
    _display_table_columns = _ov_table._display_table_columns
    _active_table_column_filters = _ov_table._active_table_column_filters
    _set_table_columns = _ov_table._set_table_columns
    _table_query_payload = _ov_table._table_query_payload
    _query_table_rows = _ov_table._query_table_rows
    _sync_table_sort_indicator = _ov_table._sync_table_sort_indicator
    _on_table_sort_changed = _ov_table._on_table_sort_changed
    _render_table_rows = _ov_table._render_table_rows
    on_table_cell_clicked = _ov_table.on_table_cell_clicked
    on_table_row_double_clicked = _ov_table.on_table_row_double_clicked
    _on_table_item_changed = _ov_table._on_table_item_changed
    _emit_takeout_prefill_background = _ov_table._emit_takeout_prefill_background
    _emit_add_prefill_background = _ov_table._emit_add_prefill_background
    _emit_add_prefill = _ov_table._emit_add_prefill
    _on_table_context_menu = _ov_table._on_table_context_menu

    _repaint_all_cells = _ov_grid._repaint_all_cells
    _repaint_cells = _ov_grid._repaint_cells
    _update_box_titles = _ov_grid._update_box_titles
    _warm_hover_animation = _ov_grid._warm_hover_animation
    _rebuild_boxes = _ov_grid._rebuild_boxes
    _build_cell_render_signature = _ov_grid._build_cell_render_signature
    _paint_cell = _ov_grid._paint_cell
    _update_cell_label_visibility = _ov_grid._update_cell_label_visibility
    _cell_is_empty_slot = _ov_grid._cell_is_empty_slot
    _is_cell_selected = _ov_grid._is_cell_selected
    _selected_empty_keys_for_box = _ov_grid._selected_empty_keys_for_box
    _set_empty_multi_selection = _ov_grid._set_empty_multi_selection
    _clear_empty_multi_selection = _ov_grid._clear_empty_multi_selection
    _prune_empty_multi_selection = _ov_grid._prune_empty_multi_selection
    _set_selected_cell = _ov_grid._set_selected_cell
    _clear_selected_cell = _ov_grid._clear_selected_cell
    _select_grid_cell = _ov_grid._select_grid_cell
    _resolve_grid_navigation_target = _ov_grid._resolve_grid_navigation_target
    _set_plan_store_ref = _ov_grid._set_plan_store_ref
    _set_plan_markers_from_items = _ov_grid._set_plan_markers_from_items

    def eventFilter(self, obj, event):
        return self._runtime.event_filter(obj, event)

    @Slot()
    def _on_plan_store_changed(self):
        _ov_grid._on_plan_store_changed(self)
        _ov_table._on_plan_store_changed(self)

    def bind_plan_store(self, plan_store):
        self._set_plan_store_ref(plan_store)

    @Slot()
    def refresh_plan_store_view(self):
        if not bool(getattr(self, "_coalesce_plan_store_refresh", False)):
            self._on_plan_store_changed()
            return
        if getattr(self, "_plan_store_refresh_pending", False):
            return
        self._plan_store_refresh_pending = True

        def _flush():
            self._plan_store_refresh_pending = False
            self._on_plan_store_changed()

        QTimer.singleShot(50, _flush)


    # Zoom + box navigation delegate to the collaborator held in ``self._zoom``.
    def _set_zoom(self, level, animated=False):
        return self._zoom._set_zoom(level, animated)

    def _fit_one_box(self):
        return self._zoom._fit_one_box()

    def _fit_all_boxes(self):
        return self._zoom._fit_all_boxes()

    def _update_box_navigation(self, box_numbers):
        return self._zoom._update_box_navigation(box_numbers)

    def refresh(self):
        return self._refresh.refresh()

    # Filtering delegates to the collaborator held in ``self._filters``.
    def _refresh_filter_options(self, records, box_numbers):
        return self._filters._refresh_filter_options(records, box_numbers)

    def _apply_filters(self):
        return self._filters._apply_filters()

    def _apply_filters_table(self, keyword, selected_box, selected_cell):
        return self._filters._apply_filters_table(keyword, selected_box, selected_cell)

    def on_toggle_filters(self, checked):
        return self._filters.on_toggle_filters(checked)

    def on_clear_filters(self):
        return self._filters.on_clear_filters()

    def _on_column_filter_clicked(self, column_index, column_name):
        return self._filters._on_column_filter_clicked(column_index, column_name)

    def _detect_column_type(self, column_name):
        return self._filters._detect_column_type(column_name)

    def _get_unique_column_values(self, column_name):
        return self._filters._get_unique_column_values(column_name)

    def _match_column_filter(self, row_data, column_name, filter_config):
        return self._filters._match_column_filter(row_data, column_name, filter_config)


    # Cell interaction / hover preview / drag-drop delegate to ``self._interactions``.
    def on_cell_clicked(self, box_num, position, modifiers=None):
        return self._interactions.on_cell_clicked(box_num, position, modifiers)

    def on_cell_double_clicked(self, box_num, position):
        return self._interactions.on_cell_double_clicked(box_num, position)

    def on_cell_hovered(self, box_num, position, force=False):
        return self._interactions.on_cell_hovered(box_num, position, force)

    def _reset_detail(self):
        return self._interactions._reset_detail()

    def _show_detail(self, box_num, position, record):
        return self._interactions._show_detail(box_num, position, record)

    def _navigate_grid_selection(self, direction):
        return self._interactions._navigate_grid_selection(direction)

    def on_cell_context_menu(self, box_num, position, global_pos):
        return self._interactions.on_cell_context_menu(box_num, position, global_pos)

    def on_box_context_menu(self, box_num, global_pos):
        return self._interactions.on_box_context_menu(box_num, global_pos)

    def _on_cell_drop(self, from_box, from_pos, to_box, to_pos, record_id):
        return self._interactions._on_cell_drop(from_box, from_pos, to_box, to_pos, record_id)

    def set_summary_cards_visible(self, visible):
        """Show or hide the summary cards (used when displaying stats in status bar instead)."""
        self._show_summary_cards = visible
        self._summary_container.setVisible(visible)
