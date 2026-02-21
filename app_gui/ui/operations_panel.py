import os
from contextlib import suppress
from datetime import datetime
from PySide6.QtCore import Qt, Signal, Slot, QDate, QSize, QSortFilterProxyModel
from PySide6.QtGui import QDesktopServices, QValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCompleter,
    QStackedWidget, QTableWidget,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox,
    QFormLayout, QDateEdit, QSpinBox, QDoubleSpinBox, QTextBrowser
)
from app_gui.ui.theme import (
    get_theme_color,
    resolve_theme_token,
)
from app_gui.ui.icons import get_icon, Icons
from app_gui.gui_config import load_gui_config
from app_gui.i18n import tr
from app_gui.error_localizer import localize_error_payload
from lib.tool_api import parse_batch_entries
from lib.plan_item_factory import (
    build_add_plan_item,
    build_record_plan_item,
    iter_batch_entries,
    resolve_record_box,
)
from lib.validators import parse_positions
from lib.position_fmt import display_to_pos, pos_to_display
from lib.plan_store import PlanStore
from app_gui.ui import operations_panel_execution as _ops_exec
from app_gui.ui import operations_panel_actions as _ops_actions
from app_gui.ui import operations_panel_plan_table as _ops_plan_table
from app_gui.ui import operations_panel_results as _ops_results
from app_gui.ui import operations_panel_plan_store as _ops_plan_store

# Keep these Qt symbols imported here as stable monkeypatch targets used by
# operations_panel_actions and related tests.
_MONKEYPATCH_EXPORTS = (QDesktopServices, QFileDialog)

_ACTION_I18N_KEY = {
    "takeout": "overview.takeout",
    "move": "operations.move",
    "add": "operations.add",
    "edit": "operations.edit",
    "rollback": "operations.rollback",
}


def _localized_action(action: str) -> str:
    """Return localized display text for a canonical action name."""
    key = _ACTION_I18N_KEY.get(action.lower())
    return tr(key) if key else action.capitalize()


class _PrefixListValidator(QValidator):
    """Allow only prefixes/exact values from a finite option list."""

    def __init__(self, options=None, allow_empty=True, parent=None):
        super().__init__(parent)
        self._options = []
        self._lower_options = []
        self._allow_empty = bool(allow_empty)
        self.set_rules(options or [], allow_empty=allow_empty)

    def set_rules(self, options, allow_empty=True):
        normalized = []
        seen = set()
        for raw in options or []:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        self._options = normalized
        self._lower_options = [item.casefold() for item in normalized]
        self._allow_empty = bool(allow_empty)

    def validate(self, input_text, pos):
        text = str(input_text or "")
        if not text:
            if self._allow_empty:
                return (QValidator.Acceptable, input_text, pos)
            return (QValidator.Intermediate, input_text, pos)

        lowered = text.casefold()
        if lowered in self._lower_options:
            return (QValidator.Acceptable, input_text, pos)

        for opt in self._lower_options:
            if opt.startswith(lowered):
                return (QValidator.Intermediate, input_text, pos)

        return (QValidator.Invalid, input_text, pos)


_CHOICE_HINT_ROLE = int(Qt.UserRole) + 101


class _ChoiceHintProxyModel(QSortFilterProxyModel):
    """Filter normal options by prefix while always keeping hint rows visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix = ""

    def set_prefix(self, prefix_text):
        prefix = str(prefix_text or "").strip().casefold()
        if prefix == self._prefix:
            return
        self._prefix = prefix
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        if bool(index.data(_CHOICE_HINT_ROLE)):
            return True
        text = str(index.data(Qt.DisplayRole) or "")
        if not self._prefix:
            return True
        return text.casefold().startswith(self._prefix)


class OperationsPanel(QWidget):
    operation_completed = Signal(bool)
    operation_event = Signal(dict)
    status_message = Signal(str, int, str)

    def __init__(self, bridge, yaml_path_getter, plan_store=None, overview_panel=None):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        self._plan_store = plan_store if plan_store is not None else PlanStore()
        self._overview_panel_ref = overview_panel  # Store reference for grid state extraction

        self.records_cache = {}
        self.current_operation_mode = "takeout"
        self.t_prefill_source = None
        self._default_date_anchor = QDate.currentDate()
        self._last_operation_backup = None
        self._last_executed_plan = []
        self._plan_preflight_report = None
        self._plan_validation_by_key = {}
        self._undo_timer = None
        self._undo_remaining = 0
        self._current_custom_fields = []
        self._current_meta = {}
        self._current_layout = {}

        self.setup_ui()

    @property
    def plan_items(self):
        """Read-only snapshot for backward compatibility (tests, external reads)."""
        return self._plan_store.list_items()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        layout.addLayout(self._build_mode_row())
        layout.addWidget(self._build_operation_stack(), 2)
        layout.addLayout(self._build_feedback_row())
        # Plan Queue is always visible to reduce context switching.
        self.plan_panel = self._build_plan_tab()
        layout.addWidget(self.plan_panel, 3)
        layout.addLayout(self._build_result_row())

        self._sync_result_actions()
        self.set_mode("takeout")

    def _build_mode_row(self):
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(9, 0, 9, 0)

        self.op_mode_combo = QComboBox()
        self.op_mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        modes = [
            ("takeout", tr("overview.takeout")),
            ("move", tr("operations.move")),
            ("add", tr("operations.add")),
        ]
        for mode_key, mode_label in modes:
            self.op_mode_combo.addItem(mode_label, mode_key)
        self.op_mode_combo.currentIndexChanged.connect(self.on_mode_changed)

        self.quick_add_btn = QPushButton(tr("overview.quickAdd"))
        self.quick_add_btn.setIcon(get_icon(Icons.PLUS))
        self.quick_add_btn.setIconSize(QSize(16, 16))
        self.quick_add_btn.clicked.connect(lambda: self.set_mode("add"))
        mode_row.addWidget(self.quick_add_btn)

        self.export_full_csv_btn = QPushButton(tr("operations.exportFullCsv"))
        self.export_full_csv_btn.setIcon(get_icon(Icons.DOWNLOAD))
        self.export_full_csv_btn.setIconSize(QSize(16, 16))
        self.export_full_csv_btn.setToolTip(tr("operations.exportFullCsvHint"))
        self.export_full_csv_btn.clicked.connect(self.on_export_inventory_csv)
        mode_row.addWidget(self.export_full_csv_btn)

        mode_row.addStretch()
        mode_row.addWidget(self.op_mode_combo)
        return mode_row

    def _build_operation_stack(self):
        self.op_stack = QStackedWidget()
        self.op_mode_indexes = {
            "add": self.op_stack.addWidget(self._build_add_tab()),
            "takeout": self.op_stack.addWidget(self._build_takeout_tab()),
            "move": self.op_stack.addWidget(self._build_move_tab()),
        }
        return self.op_stack

    def _build_feedback_row(self):
        # Inline feedback near operation forms (more visible than status bar).
        self.plan_feedback_label = QLabel("")
        self.plan_feedback_label.setObjectName("operationsPlanFeedback")
        self.plan_feedback_label.setProperty("level", "info")
        self.plan_feedback_label.setWordWrap(True)
        self.plan_feedback_label.setVisible(False)

        feedback_row = QHBoxLayout()
        feedback_row.setContentsMargins(9, 0, 9, 0)
        feedback_row.addWidget(self.plan_feedback_label)
        return feedback_row

    def _build_result_row(self):
        self.result_card = QWidget()
        self.result_card.setObjectName("resultCard")
        self.result_card.setProperty("state", "default")
        result_card_layout = QVBoxLayout(self.result_card)
        result_card_layout.setContentsMargins(9, 6, 9, 8)
        result_card_layout.setSpacing(4)

        result_header = QHBoxLayout()
        result_title = QLabel(tr("operations.lastResult"))
        result_title.setObjectName("operationsResultTitle")
        result_header.addWidget(result_title)
        result_header.addStretch()
        self._result_hide_btn = QPushButton(tr("operations.hideResult"))
        self._result_hide_btn.clicked.connect(self._on_hide_result_card)
        result_header.addWidget(self._result_hide_btn)
        result_card_layout.addLayout(result_header)

        self.result_summary = QTextBrowser()
        self.result_summary.setObjectName("operationsResultSummary")
        self.result_summary.setOpenExternalLinks(False)
        self.result_summary.setMaximumHeight(180)
        self.result_summary.setHtml(tr("operations.noOperations"))
        result_card_layout.addWidget(self.result_summary)

        self.result_actions = QWidget()
        self.result_actions.setObjectName("operationsResultActions")
        result_actions_layout = QHBoxLayout(self.result_actions)
        result_actions_layout.setContentsMargins(0, 2, 0, 0)
        result_actions_layout.setSpacing(8)
        result_actions_layout.addStretch()

        self.undo_btn = QPushButton(tr("operations.undoLast"))
        self.undo_btn.setIcon(get_icon(Icons.ROTATE_CCW))
        self.undo_btn.clicked.connect(self.on_undo_last)
        result_actions_layout.addWidget(self.undo_btn)

        self.print_last_result_btn = QPushButton(tr("operations.printLastResult"))
        self.print_last_result_btn.setIcon(get_icon(Icons.DOWNLOAD))
        self.print_last_result_btn.clicked.connect(self.print_last_executed)
        result_actions_layout.addWidget(self.print_last_result_btn)

        self.result_actions.setVisible(False)
        result_card_layout.addWidget(self.result_actions)

        self.result_card.setVisible(False)
        result_row = QHBoxLayout()
        result_row.setContentsMargins(9, 0, 9, 0)
        result_row.addWidget(self.result_card)
        return result_row

    def _is_dark_theme(self):
        return load_gui_config().get("theme", "dark") != "light"

    def _status_color_hex(self, name):
        return get_theme_color(name, self._is_dark_theme()).name()

    def _set_result_summary_html(self, lines):
        if isinstance(lines, (list, tuple)):
            html = "<br/>".join(str(line) for line in lines)
        else:
            html = str(lines)

        replacements = {
            "var(--status-success)": self._status_color_hex("success"),
            "var(--status-warning)": self._status_color_hex("warning"),
            "var(--status-error)": self._status_color_hex("error"),
            "var(--status-muted)": self._status_color_hex("muted"),
        }
        for token, color_hex in replacements.items():
            html = html.replace(token, color_hex)

        self.result_summary.setText(html)

    def _set_result_card_state(self, state):
        self.result_card.setProperty("state", str(state or "default"))
        self.result_card.style().unpolish(self.result_card)
        self.result_card.style().polish(self.result_card)
        self.result_card.setVisible(True)

    def _show_result_card(self, lines, state):
        self._set_result_summary_html(lines)
        self._set_result_card_state(state)

    def _on_hide_result_card(self):
        """Hide last result card and dismiss quick actions."""
        self.result_card.setVisible(False)
        self._disable_undo(clear_last_executed=True)

    def _sync_result_actions(self):
        """Sync visibility/enabled state of result-card action buttons."""
        has_last_executed = bool(self._last_executed_plan)
        has_undo = bool(self._last_operation_backup)

        self.print_last_result_btn.setVisible(has_last_executed)
        self.print_last_result_btn.setEnabled(has_last_executed)

        self.undo_btn.setVisible(has_undo)
        self.undo_btn.setEnabled(has_undo)
        if has_undo and self._undo_remaining > 0:
            self._update_undo_button_text()
        else:
            self.undo_btn.setText(tr("operations.undoLast"))

        self.result_actions.setVisible(has_last_executed or has_undo)

    def set_mode(self, mode):
        self._ensure_today_defaults()
        target = mode if mode in self.op_mode_indexes else "takeout"
        self.op_stack.setCurrentIndex(self.op_mode_indexes[target])
        self.current_operation_mode = target

        idx = self.op_mode_combo.findData(target)
        if idx >= 0 and idx != self.op_mode_combo.currentIndex():
            self.op_mode_combo.blockSignals(True)
            self.op_mode_combo.setCurrentIndex(idx)
            self.op_mode_combo.blockSignals(False)

    def on_mode_changed(self, _index=None):
        self.set_mode(self.op_mode_combo.currentData())

    def on_toggle_batch_section(self, checked):
        visible = bool(checked)
        if hasattr(self, "t_batch_group"):
            self.t_batch_group.setVisible(visible)
        if hasattr(self, "t_batch_toggle_btn"):
            self.t_batch_toggle_btn.setText(tr("operations.hideBatch") if visible else tr("operations.showBatch"))

    def update_records_cache(self, records_dict):
        normalized = {}

        if isinstance(records_dict, dict):
            items = list(records_dict.items())
        elif isinstance(records_dict, list):
            items = []
            for record in records_dict:
                if isinstance(record, dict):
                    items.append((record.get("id"), record))
        else:
            items = []

        for key, record in items:
            if not isinstance(record, dict):
                continue

            rid = key if key is not None else record.get("id")
            try:
                normalized[int(rid)] = record
            except (TypeError, ValueError):
                continue

        self.records_cache = normalized
        self._refresh_takeout_record_context()
        self._refresh_move_record_context()
        self._refresh_custom_fields()

    def _refresh_custom_fields(self):
        """Reload custom field definitions from YAML meta and rebuild dynamic forms."""
        from lib.yaml_ops import load_yaml
        try:
            yaml_path = self.yaml_path_getter()
            data = load_yaml(yaml_path)
            meta = data.get("meta", {})
        except Exception:
            meta = {}
        self.apply_meta_update(meta)

    def apply_meta_update(self, meta=None):
        """Apply latest YAML meta to forms immediately (no restart needed)."""
        from lib.custom_fields import get_effective_fields

        if not isinstance(meta, dict):
            from lib.yaml_ops import load_yaml

            try:
                yaml_path = self.yaml_path_getter()
                data = load_yaml(yaml_path)
                meta = data.get("meta", {})
            except Exception:
                meta = {}

        self._current_meta = meta
        self._current_layout = dict((meta or {}).get("box_layout") or {})
        custom_fields = get_effective_fields(meta)
        self._current_custom_fields = custom_fields
        self._rebuild_custom_add_fields(custom_fields)
        self._rebuild_ctx_user_fields("takeout", custom_fields)
        self._rebuild_ctx_user_fields("move", custom_fields)
        # Refresh cell_line dropdown options
        self._refresh_cell_line_options(meta)

        # Re-evaluate staged plan immediately against latest rules.
        if self._plan_store.count() > 0:
            self._run_plan_preflight(trigger="meta_updated")
        else:
            self._plan_preflight_report = None
            self._plan_validation_by_key = {}
            self._refresh_plan_table()
            self._update_execute_button_state()

    def _refresh_cell_line_options(self, meta):
        """Populate the cell_line combo box from meta.cell_line_options."""
        from lib.custom_fields import get_cell_line_options, is_cell_line_required

        combo = getattr(self, "a_cell_line", None)
        if combo is None:
            return

        required = is_cell_line_required(meta)
        options = []
        seen = set()
        for raw in get_cell_line_options(meta):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            options.append(text)
        hint_lines = self._cell_line_hint_lines()
        prev = combo.currentText()

        combo.blockSignals(True)

        display_options = []
        if not required:
            display_options.append("")
        display_options.extend(options)

        combo_model = self._build_choice_display_model(
            display_options,
            hint_lines=hint_lines,
            parent=combo,
        )
        combo.setModel(combo_model)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo_row_count = combo_model.rowCount()
        combo.setMaxVisibleItems(max(1, combo_row_count))
        try:
            view = combo.view()
            if view is not None:
                view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                popup_height = self._popup_height_for_rows(view, combo_row_count)
                if popup_height > 0:
                    view.setMinimumHeight(popup_height)
                    view.setMaximumHeight(popup_height)
        except Exception:
            pass

        target_index = -1
        if prev:
            idx = combo.findText(prev, Qt.MatchFixedString)
            if idx >= 0:
                model_item = combo_model.item(idx, 0)
                if model_item is not None and not bool(model_item.data(_CHOICE_HINT_ROLE)):
                    target_index = idx

        if target_index < 0 and not required and combo.count() > 0:
            target_index = 0

        if target_index < 0 and required and options:
            target_index = 0

        if target_index >= 0:
            combo.setCurrentIndex(target_index)

        combo.blockSignals(False)

        combo_line = combo.lineEdit()
        if combo_line is not None:
            self._configure_choice_line_edit(
                combo_line,
                options=options,
                allow_empty=(not required),
                hint_lines=hint_lines,
                show_all_popup=True,
            )

        self._refresh_context_cell_line_constraints()

    @staticmethod
    def _build_choice_display_model(options, *, hint_lines=None, parent=None):
        model = QStandardItemModel(parent)

        for raw in options or []:
            text = str(raw or "")
            item = QStandardItem(text)
            item.setEditable(False)
            item.setData(False, _CHOICE_HINT_ROLE)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            model.appendRow(item)

        for raw_hint in hint_lines or []:
            hint_text = str(raw_hint or "").strip()
            if not hint_text:
                continue
            hint_item = QStandardItem(hint_text)
            hint_item.setEditable(False)
            hint_item.setData(True, _CHOICE_HINT_ROLE)
            # Show as read-only guidance row in dropdown/completer popup.
            hint_item.setFlags(Qt.ItemIsEnabled)
            model.appendRow(hint_item)

        return model

    @staticmethod
    def _cell_line_hint_lines():
        lines = []
        for key in (
            "operations.cellLineOptionsHintLine1",
            "operations.cellLineOptionsHintLine2",
        ):
            text = str(tr(key) or "").strip()
            if text and text not in lines:
                lines.append(text)
        return lines

    def _cell_line_choice_config(self):
        from lib.custom_fields import get_cell_line_options, is_cell_line_required

        meta = self._current_meta if isinstance(self._current_meta, dict) else {}
        required = is_cell_line_required(meta)
        options = []
        seen = set()
        for raw in get_cell_line_options(meta):
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            options.append(text)
        return options, (not required)

    @staticmethod
    def _canonicalize_choice(value, options):
        text = str(value or "").strip()
        if not text:
            return ""
        for opt in options:
            if opt == text:
                return opt
        lower = text.casefold()
        for opt in options:
            if opt.casefold() == lower:
                return opt
        return None

    def _configure_choice_line_edit(
        self,
        line_edit,
        *,
        options,
        allow_empty,
        hint_lines=None,
        show_all_popup=False,
    ):
        if not isinstance(line_edit, QLineEdit):
            return

        validator = getattr(line_edit, "_choice_validator", None)
        if not isinstance(validator, _PrefixListValidator):
            validator = _PrefixListValidator(options, allow_empty=allow_empty, parent=line_edit)
            line_edit._choice_validator = validator
        else:
            validator.set_rules(options, allow_empty=allow_empty)
        line_edit.setValidator(validator)

        completer = line_edit.completer()
        if not isinstance(completer, QCompleter):
            completer = QCompleter(line_edit)
            line_edit.setCompleter(completer)

        hint_lines = list(hint_lines or self._cell_line_hint_lines())
        source_model = self._build_choice_display_model(options, hint_lines=hint_lines, parent=completer)

        proxy_model = getattr(line_edit, "_choice_proxy_model", None)
        if not isinstance(proxy_model, _ChoiceHintProxyModel):
            proxy_model = _ChoiceHintProxyModel(line_edit)
            line_edit._choice_proxy_model = proxy_model

        proxy_model.setSourceModel(source_model)
        proxy_model.set_prefix(line_edit.text())

        if not getattr(line_edit, "_choice_prefix_hooked", False):
            def _on_choice_text_changed(text, edit=line_edit):
                proxy = getattr(edit, "_choice_proxy_model", None)
                if isinstance(proxy, _ChoiceHintProxyModel):
                    proxy.set_prefix(text)

            line_edit.textChanged.connect(_on_choice_text_changed)
            line_edit._choice_prefix_hooked = True

        completer.setModel(proxy_model)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        if show_all_popup:
            completer.setMaxVisibleItems(max(1, proxy_model.rowCount()))
        else:
            completer.setMaxVisibleItems(10)

        popup = completer.popup()
        if popup is not None:
            if show_all_popup:
                popup.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                popup_height = self._popup_height_for_rows(popup, proxy_model.rowCount())
                if popup_height > 0:
                    popup.setMinimumHeight(popup_height)
                    popup.setMaximumHeight(popup_height)
            else:
                popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                popup.setMaximumHeight(240)

    @staticmethod
    def _popup_height_for_rows(view, row_count):
        count = int(row_count or 0)
        if view is None or count <= 0:
            return 0

        try:
            row_height = int(view.sizeHintForRow(0))
        except Exception:
            row_height = 0
        if row_height <= 0:
            row_height = max(18, int(view.fontMetrics().height()) + 6)

        try:
            frame = int(view.frameWidth()) * 2
        except Exception:
            frame = 0

        return max(1, count * row_height + frame)

    def _refresh_context_cell_line_constraints(self):
        options, allow_empty = self._cell_line_choice_config()
        for field in (getattr(self, "t_ctx_cell_line", None), getattr(self, "m_ctx_cell_line", None)):
            if isinstance(field, QLineEdit):
                self._configure_choice_line_edit(
                    field,
                    options=options,
                    allow_empty=allow_empty,
                    show_all_popup=True,
                )

    def _takeout_record_id(self):
        return self.t_id.value()

    def _move_record_id(self):
        return self.m_id.value()

    def _rebuild_ctx_user_fields(self, prefix, custom_fields):
        """Rebuild user field context rows in takeout/move form."""
        if prefix == "takeout":
            form = getattr(self, "_takeout_ctx_form", None)
            widgets = getattr(self, "_takeout_ctx_widgets", {})
            rid_fn = self._takeout_record_id
            refresh_fn = self._refresh_takeout_record_context
        else:
            form = getattr(self, "_move_ctx_form", None)
            widgets = getattr(self, "_move_ctx_widgets", {})
            rid_fn = self._move_record_id
            refresh_fn = self._refresh_move_record_context
        if form is None:
            return
        # Remove old user field rows
        for key, (container, label) in widgets.items():
            form.removeRow(container)
        widgets.clear()
        # Insert new user field rows
        for fdef in (custom_fields or []):
            key = fdef["key"]
            flabel = fdef.get("label", key)
            container, lbl_widget = self._make_editable_field(key, rid_fn, refresh_fn)
            form.insertRow(form.rowCount(), flabel, container)
            widgets[key] = (container, lbl_widget)
        if prefix == "takeout":
            self._takeout_ctx_widgets = widgets
        else:
            self._move_ctx_widgets = widgets

    def _collect_custom_add_values(self):
        """Collect values from custom field widgets in the add form."""
        from lib.custom_fields import coerce_value
        custom_fields = getattr(self, "_current_custom_fields", [])
        if not custom_fields:
            return None
        result = {}
        for field_def in custom_fields:
            key = field_def["key"]
            widget = self._add_custom_widgets.get(key)
            if widget is None:
                continue
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                raw = widget.value()
            elif isinstance(widget, QDateEdit):
                raw = widget.date().toString("yyyy-MM-dd")
            else:
                raw = widget.text().strip()
            try:
                val = coerce_value(raw, field_def.get("type", "str"))
            except (ValueError, TypeError):
                val = raw if raw else None
            if val is not None:
                result[key] = val
        return result if result else None

    def _position_to_display(self, position):
        if position in (None, ""):
            return ""
        try:
            return pos_to_display(int(position), self._current_layout)
        except Exception:
            return str(position)

    def _parse_position_text(self, raw_text, *, allow_empty=False):
        text = str(raw_text or "").strip()
        if not text:
            if allow_empty:
                return None
            raise ValueError("Position is required")
        try:
            return int(display_to_pos(text, self._current_layout))
        except Exception as exc:
            if allow_empty:
                return None
            raise ValueError(f"Invalid position: {text}") from exc

    def _positions_to_display_text(self, positions):
        return ",".join(self._position_to_display(pos) for pos in (positions or []))

    def _apply_takeout_prefill(self, source_info):
        payload = dict(source_info or {})
        self.t_prefill_source = payload

        # If record_id is provided directly, set it
        if "record_id" in payload:
            self.t_id.blockSignals(True)
            self.t_id.setValue(int(payload["record_id"]))
            self.t_id.blockSignals(False)

        # Fill source box + position (will auto-lookup record ID if not provided)
        if "box" in payload:
            self.t_from_box.setValue(int(payload["box"]))
        if "position" in payload:
            self.t_from_position.setText(self._position_to_display(payload["position"]))
        self.t_action.setCurrentIndex(0)
        self._refresh_takeout_record_context()
        self.set_mode("takeout")

    def set_prefill(self, source_info):
        self.set_prefill_background(source_info)

    def set_prefill_background(self, source_info):
        self._apply_takeout_prefill(source_info)

    def set_move_prefill(self, source_info):
        self._m_prefill_position = source_info.get("position")
        # Fill source box + position (will auto-lookup record ID)
        if "box" in source_info:
            self.m_from_box.setValue(int(source_info["box"]))
        if "position" in source_info:
            self.m_from_position.setText(self._position_to_display(source_info["position"]))
        # Fill target box + position (mark as user-specified)
        if "to_box" in source_info:
            self._m_to_box_user_specified = True
            self.m_to_box.setValue(int(source_info["to_box"]))
        if "to_position" in source_info:
            self.m_to_position.setText(self._position_to_display(source_info["to_position"]))
        self._refresh_move_record_context()
        self.set_mode("move")

    def _apply_add_prefill(self, source_info):
        payload = dict(source_info or {})
        if "box" in payload:
            self.a_box.setValue(int(payload["box"]))
        if "position" in payload:
            self.a_positions.setText(self._position_to_display(payload["position"]))
        self.set_mode("add")

    def set_add_prefill(self, source_info):
        """Pre-fill the Add Entry form with box and position from overview."""
        self.set_add_prefill_background(source_info)

    def set_add_prefill_background(self, source_info):
        """Pre-fill the Add Entry form and switch to Add mode."""
        self._apply_add_prefill(source_info)

    def _setup_table(self, table, headers, sortable=True):
        table.setRowCount(0)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        for idx in range(len(headers)):
            mode = QHeaderView.Stretch if idx == len(headers) - 1 else QHeaderView.ResizeToContents
            header.setSectionResizeMode(idx, mode)
        table.setSortingEnabled(bool(sortable))

    def _make_readonly_field(self):
        label = QLabel("-")
        label.setWordWrap(False)
        label.setProperty("role", "readonlyField")
        return label

    def _make_readonly_history_label(self):
        label = QLabel("-")
        label.setWordWrap(False)
        label.setProperty("role", "readonlyField")
        return label

    def _make_editable_field(self, field_name, record_id_getter, refresh_callback=None, choices_provider=None):
        """Create a read-only field with lock/unlock/confirm inline edit controls.

        Args:
            field_name: YAML record key (e.g. 'cell_line', 'short_name').
            record_id_getter: callable returning current record ID (int).
            refresh_callback: callable to restore original value on cancel.
        Returns:
            (container_widget, field_widget) - add container to form, use field for setText.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        field = QLineEdit()
        field.setReadOnly(True)
        field.setProperty("role", "contextEditable")
        row.addWidget(field, 1)

        lock_btn = QPushButton("\U0001F512")  # lock icon
        lock_btn.setObjectName("inlineLockBtn")
        lock_btn.setFixedSize(16, 16)
        lock_btn.setToolTip(tr("operations.edit"))
        row.addWidget(lock_btn)

        confirm_btn = QPushButton("\u2713")  # confirm icon
        confirm_btn.setObjectName("inlineConfirmBtn")
        confirm_btn.setFixedSize(16, 16)
        confirm_btn.setVisible(False)
        row.addWidget(confirm_btn)

        def _apply_choices():
            if not callable(choices_provider):
                return [], True
            try:
                payload = choices_provider()
            except Exception:
                return [], True

            raw_options = []
            allow_empty = True
            if isinstance(payload, tuple) and len(payload) == 2:
                raw_options, allow_empty = payload
            elif isinstance(payload, list):
                raw_options = payload

            options = []
            seen = set()
            for raw in raw_options or []:
                text = str(raw or "").strip()
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                options.append(text)

            self._configure_choice_line_edit(
                field,
                options=options,
                allow_empty=bool(allow_empty),
                show_all_popup=(field_name == "cell_line"),
            )
            return options, bool(allow_empty)

        def on_lock_toggle():
            if field.isReadOnly():
                # Unlock
                _apply_choices()
                field.setReadOnly(False)
                lock_btn.setText("\U0001F513")  # 濡絽鍟弲?                confirm_btn.setVisible(True)
                field.setFocus()
                field.selectAll()
            else:
                # Re-lock without saving
                field.setReadOnly(True)
                lock_btn.setText("\U0001F512")  # 濡絽鍟弲?                confirm_btn.setVisible(False)
                # Restore original value
                if refresh_callback:
                    refresh_callback()

        def on_confirm():
            rid = record_id_getter()
            new_value = field.text().strip() or None
            options, _allow_empty = _apply_choices()
            if options and new_value:
                canonical = self._canonicalize_choice(new_value, options)
                if canonical is not None:
                    new_value = canonical
            record = self._lookup_record(rid)
            if not record:
                self.status_message.emit(tr("operations.recordNotFound"), 3000, "error")
                return
            old_value = record.get(field_name) or None
            old_str = str(old_value) if old_value is not None else ""
            new_str = str(new_value) if new_value is not None else ""
            if old_str == new_str:
                self.status_message.emit(tr("operations.editNoChange"), 2000, "info")
                # Re-lock
                field.setReadOnly(True)
                lock_btn.setText("\U0001F512")
                confirm_btn.setVisible(False)
                return
            yaml_path = self.yaml_path_getter()
            if not yaml_path:
                return
            result = self.bridge.edit_entry(
                yaml_path=yaml_path,
                record_id=rid,
                fields={field_name: new_value},
                execution_mode="execute",
            )
            if result.get("ok"):
                field.setReadOnly(True)
                lock_btn.setText("\U0001F512")
                confirm_btn.setVisible(False)
                self._publish_system_notice(
                    code="record.edit.saved",
                    text=tr("operations.editFieldSaved", field=field_name, before=old_str, after=new_str),
                    level="success",
                    timeout=4000,
                    data={
                        "record_id": rid,
                        "field": field_name,
                        "before": old_str,
                        "after": new_str,
                    },
                )
                self.operation_completed.emit(True)
            else:
                error_text = localize_error_payload(result)
                self._publish_system_notice(
                    code="record.edit.failed",
                    text=tr("operations.editFieldFailed", error=error_text),
                    level="error",
                    timeout=5000,
                    data={
                        "record_id": rid,
                        "field": field_name,
                        "error_code": result.get("error_code"),
                        "message": error_text,
                    },
                )

        lock_btn.clicked.connect(on_lock_toggle)
        confirm_btn.clicked.connect(on_confirm)

        return container, field

    # --- ADD TAB ---
    def _build_add_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        # Target selection: Box + Positions (inline)
        target_row = QHBoxLayout()
        box_label = QLabel("Box")
        box_label.setProperty("role", "mutedInline")
        target_row.addWidget(box_label)

        self.a_box = QSpinBox()
        self.a_box.setRange(1, 99)
        self.a_box.setFixedWidth(60)
        target_row.addWidget(self.a_box)

        colon_label = QLabel(":")
        colon_label.setProperty("role", "mutedInline")
        target_row.addWidget(colon_label)

        self.a_positions = QLineEdit()
        self.a_positions.setPlaceholderText(tr("operations.positionsPh"))
        target_row.addWidget(self.a_positions)

        form.addRow(tr("operations.to"), target_row)

        # Other fields
        self.a_date = QDateEdit()
        self.a_date.setCalendarPopup(True)
        self.a_date.setDisplayFormat("yyyy-MM-dd")
        self.a_date.setDate(QDate.currentDate())

        # Cell line dropdown (structural, optional)
        self.a_cell_line = QComboBox()
        self.a_cell_line.setEditable(True)
        self.a_cell_line.addItem("")  # allow empty
        self.a_note = QLineEdit()

        form.addRow(tr("operations.frozenDate"), self.a_date)
        form.addRow(tr("operations.cellLine"), self.a_cell_line)
        form.addRow(tr("operations.note"), self.a_note)

        # User fields placeholder -?populated by _rebuild_custom_add_fields()
        self._add_custom_form = form
        self._add_custom_widgets = {}

        self.a_apply_btn, a_btn_row = self._build_stage_action_button(
            tr("operations.add"),
            self.on_add_entry,
        )
        form.addRow("", a_btn_row)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _rebuild_custom_add_fields(self, custom_fields):
        """Rebuild user field rows in the add form based on effective fields."""
        form = self._add_custom_form
        # Remove old user field widgets
        for key, widget in self._add_custom_widgets.items():
            form.removeRow(widget)
        self._add_custom_widgets = {}

        if not custom_fields:
            return

        # Insert before the button row (last row)
        for field_def in custom_fields:
            key = field_def["key"]
            label = field_def.get("label", key)
            ftype = field_def.get("type", "str")
            default = field_def.get("default")

            if ftype == "int":
                widget = QSpinBox()
                widget.setRange(-999999, 999999)
                if default is not None:
                    with suppress(ValueError, TypeError):
                        widget.setValue(int(default))
            elif ftype == "float":
                widget = QDoubleSpinBox()
                widget.setRange(-999999.0, 999999.0)
                widget.setDecimals(3)
                if default is not None:
                    with suppress(ValueError, TypeError):
                        widget.setValue(float(default))
            elif ftype == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setDisplayFormat("yyyy-MM-dd")
                widget.setDate(QDate.currentDate())
            else:
                widget = QLineEdit()
                if default is not None:
                    widget.setText(str(default))

            # Insert before the last row (button row)
            btn_row_idx = form.rowCount() - 1
            form.insertRow(btn_row_idx, label, widget)
            self._add_custom_widgets[key] = widget

    # --- TAKEOUT TAB ---
    def _build_takeout_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        # Source selection: Box + Position
        source_row = QHBoxLayout()
        box_label = QLabel("Box")
        box_label.setProperty("role", "mutedInline")
        source_row.addWidget(box_label)

        self.t_from_box = QSpinBox()
        self.t_from_box.setRange(1, 99)
        self.t_from_box.setFixedWidth(60)
        self.t_from_box.valueChanged.connect(self._refresh_takeout_record_context)
        source_row.addWidget(self.t_from_box)

        colon_label = QLabel(":")
        colon_label.setProperty("role", "mutedInline")
        source_row.addWidget(colon_label)

        self.t_from_position = QLineEdit()
        self.t_from_position.setFixedWidth(60)
        self.t_from_position.textChanged.connect(self._refresh_takeout_record_context)
        source_row.addWidget(self.t_from_position)

        source_row.addStretch()

        form.addRow(tr("operations.from"), source_row)

        # Hidden internal record ID (auto-filled from box:position lookup)
        self.t_id = QSpinBox()
        self.t_id.setRange(1, 999999)
        self.t_id.setVisible(False)
        # Connect signal to refresh context when ID is changed (for reverse lookup)
        self.t_id.valueChanged.connect(self._refresh_takeout_record_context)

        _t_rid = self._takeout_record_id
        _t_refresh = self._refresh_takeout_record_context

        # Editable context fields -?frozen_at/note are core fields.
        t_frozen_w, self.t_ctx_frozen = self._make_editable_field("frozen_at", _t_rid, _t_refresh)
        t_note_w, self.t_ctx_note = self._make_editable_field("note", _t_rid, _t_refresh)
        t_cell_line_w, self.t_ctx_cell_line = self._make_editable_field(
            "cell_line",
            _t_rid,
            _t_refresh,
            choices_provider=self._cell_line_choice_config,
        )

        # Dynamic user field context widgets (populated by _rebuild_takeout_ctx_fields)
        self._takeout_ctx_form = form
        self._takeout_ctx_widgets = {}  # key -> (container_widget, label_widget)

        # Read-only context fields (not editable via inline edit) - kept for compatibility
        self.t_ctx_box = self._make_readonly_field()
        self.t_ctx_position = self._make_readonly_field()
        self.t_ctx_events = self._make_readonly_history_label()
        self.t_ctx_source = self._make_readonly_field()

        # User fields placeholder -?will be rebuilt dynamically
        self._takeout_ctx_insert_row = form.rowCount()

        form.addRow(tr("overview.ctxFrozen"), t_frozen_w)
        form.addRow(tr("operations.note"), t_note_w)
        form.addRow(tr("operations.cellLine"), t_cell_line_w)
        form.addRow(tr("overview.ctxHistory"), self.t_ctx_events)

        # Editable: target position (hidden, kept for compat - single value now)
        self.t_position = QComboBox()
        self.t_position.setVisible(False)

        # Editable fields
        self.t_date = QDateEdit()
        self.t_date.setCalendarPopup(True)
        self.t_date.setDisplayFormat("yyyy-MM-dd")
        self.t_date.setDate(QDate.currentDate())

        form.addRow(tr("operations.date"), self.t_date)

        # Status
        self.t_ctx_status = QLabel(tr("operations.noPrefill"))
        self.t_ctx_status.setWordWrap(True)
        self.t_ctx_status.setVisible(False)
        form.addRow(tr("overview.ctxStatus"), self.t_ctx_status)

        # Kept for compatibility
        self.t_ctx_id = self.t_id
        self.t_ctx_target = self.t_position
        self.t_ctx_check = QLabel()
        self.t_action = QComboBox()  # hidden, kept for compat
        self.t_action.addItem(tr("overview.takeout"), "Takeout")

        # Action button at bottom
        self.t_takeout_btn, btn_row = self._build_stage_action_button(
            tr("overview.takeout"),
            lambda: self._record_takeout_with_action("Takeout"),
        )
        # Keep t_apply_btn as alias for the first button (compat)
        self.t_apply_btn = self.t_takeout_btn
        form.addRow("", btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_takeout_controls(tab)
        layout.addStretch(1)
        return tab

    # --- MOVE TAB ---
    def _build_move_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        # Source selection: Box + Position
        source_row = QHBoxLayout()
        box_label = QLabel("Box")
        box_label.setProperty("role", "mutedInline")
        source_row.addWidget(box_label)

        self.m_from_box = QSpinBox()
        self.m_from_box.setRange(1, 99)
        self.m_from_box.setFixedWidth(60)
        self.m_from_box.valueChanged.connect(self._on_move_source_changed)
        source_row.addWidget(self.m_from_box)

        colon_label = QLabel(":")
        colon_label.setProperty("role", "mutedInline")
        source_row.addWidget(colon_label)

        self.m_from_position = QLineEdit()
        self.m_from_position.setFixedWidth(60)
        self.m_from_position.textChanged.connect(self._on_move_source_changed)
        source_row.addWidget(self.m_from_position)

        source_row.addStretch()

        form.addRow(tr("operations.from"), source_row)

        # Target selection: Box + Position
        target_row = QHBoxLayout()
        box_label2 = QLabel("Box")
        box_label2.setProperty("role", "mutedInline")
        target_row.addWidget(box_label2)

        self.m_to_box = QSpinBox()
        self.m_to_box.setRange(1, 99)
        self.m_to_box.setFixedWidth(60)
        target_row.addWidget(self.m_to_box)

        colon_label2 = QLabel(":")
        colon_label2.setProperty("role", "mutedInline")
        target_row.addWidget(colon_label2)

        self.m_to_position = QLineEdit()
        self.m_to_position.setFixedWidth(60)
        target_row.addWidget(self.m_to_position)

        target_row.addStretch()

        form.addRow(tr("operations.to"), target_row)

        # Hidden internal record ID (auto-filled from box:position lookup)
        self.m_id = QSpinBox()
        self.m_id.setRange(1, 999999)
        self.m_id.setVisible(False)

        _m_rid = self._move_record_id
        _m_refresh = self._refresh_move_record_context

        # Editable context fields -?frozen_at/note are core fields.
        m_frozen_w, self.m_ctx_frozen = self._make_editable_field("frozen_at", _m_rid, _m_refresh)
        m_note_w, self.m_ctx_note = self._make_editable_field("note", _m_rid, _m_refresh)
        m_cell_line_w, self.m_ctx_cell_line = self._make_editable_field(
            "cell_line",
            _m_rid,
            _m_refresh,
            choices_provider=self._cell_line_choice_config,
        )

        # Dynamic user field context widgets (populated by _rebuild_move_ctx_fields)
        self._move_ctx_form = form
        self._move_ctx_widgets = {}  # key -> (container_widget, label_widget)

        # Read-only context fields (not editable via inline edit) - kept for compat
        self.m_ctx_box = self._make_readonly_field()
        self.m_ctx_position = self._make_readonly_field()
        self.m_ctx_events = self._make_readonly_history_label()

        # User fields placeholder -?will be rebuilt dynamically
        self._move_ctx_insert_row = form.rowCount()

        form.addRow(tr("overview.ctxFrozen"), m_frozen_w)
        form.addRow(tr("operations.note"), m_note_w)
        form.addRow(tr("operations.cellLine"), m_cell_line_w)
        form.addRow(tr("overview.ctxHistory"), self.m_ctx_events)

        # Editable fields
        self.m_date = QDateEdit()
        self.m_date.setCalendarPopup(True)
        self.m_date.setDisplayFormat("yyyy-MM-dd")
        self.m_date.setDate(QDate.currentDate())

        form.addRow(tr("operations.date"), self.m_date)

        # Status
        self.m_ctx_status = QLabel(tr("operations.noPrefill"))
        self.m_ctx_status.setWordWrap(True)
        self.m_ctx_status.setVisible(False)
        form.addRow(tr("overview.ctxStatus"), self.m_ctx_status)

        # Kept for compatibility
        self.m_ctx_id = self.m_id
        self.m_ctx_check = QLabel()  # hidden, kept for refresh method compat

        # Action button at bottom
        self.m_apply_btn, m_btn_row = self._build_stage_action_button(
            tr("operations.move"),
            self.on_record_move,
        )
        form.addRow("", m_btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_move_controls(tab)
        layout.addStretch(1)
        return tab

    def _init_hidden_batch_takeout_controls(self, parent):
        self.t_batch_toggle_btn = QPushButton(tr("operations.showBatch"), parent)
        self.t_batch_toggle_btn.setCheckable(True)
        self.t_batch_toggle_btn.toggled.connect(self.on_toggle_batch_section)
        self.t_batch_toggle_btn.setVisible(False)

        self.t_batch_group = QGroupBox(tr("operations.batchOp"), parent)
        self.t_batch_group.setVisible(False)
        batch_form = QFormLayout(self.t_batch_group)
        self.b_entries = QLineEdit(self.t_batch_group)
        self.b_entries.setPlaceholderText(tr("operations.entriesPh"))
        self.b_date = QDateEdit(self.t_batch_group)
        self.b_date.setCalendarPopup(True)
        self.b_date.setDisplayFormat("yyyy-MM-dd")
        self.b_date.setDate(QDate.currentDate())
        self.b_action = QComboBox(self.t_batch_group)
        self.b_action.addItems([tr("overview.takeout")])
        self.b_table = QTableWidget(self.t_batch_group)
        self.b_table.setColumnCount(2)
        self.b_table.setHorizontalHeaderLabels([tr("operations.recordId"), tr("operations.position")])
        self.b_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.b_table.setRowCount(1)
        self.b_apply_btn = QPushButton(tr("operations.addPlan"), self.t_batch_group)
        self.b_apply_btn.clicked.connect(self.on_batch_takeout)

        batch_form.addRow(tr("operations.entriesText"), self.b_entries)
        batch_form.addRow(tr("operations.orUseTable"), self.b_table)
        batch_form.addRow(tr("operations.date"), self.b_date)
        batch_form.addRow(tr("operations.action"), self.b_action)
        batch_form.addRow("", self.b_apply_btn)

    def _init_hidden_batch_move_controls(self, parent):
        self.m_batch_toggle_btn = QPushButton(tr("operations.showBatchMove"), parent)
        self.m_batch_toggle_btn.setCheckable(True)
        self.m_batch_toggle_btn.toggled.connect(self._on_toggle_move_batch_section)
        self.m_batch_toggle_btn.setVisible(False)

        self.m_batch_group = QGroupBox(tr("operations.batchMove"), parent)
        self.m_batch_group.setVisible(False)
        batch_form = QFormLayout(self.m_batch_group)
        self.bm_entries = QLineEdit(self.m_batch_group)
        self.bm_entries.setPlaceholderText(tr("operations.entriesMovePh"))
        self.bm_date = QDateEdit(self.m_batch_group)
        self.bm_date.setCalendarPopup(True)
        self.bm_date.setDisplayFormat("yyyy-MM-dd")
        self.bm_date.setDate(QDate.currentDate())
        self.bm_table = QTableWidget(self.m_batch_group)
        self.bm_table.setColumnCount(4)
        self.bm_table.setHorizontalHeaderLabels([tr("operations.recordId"), tr("operations.from"), tr("operations.to"), tr("operations.toBox")])
        self.bm_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bm_table.setRowCount(1)
        self.bm_apply_btn = QPushButton(tr("operations.addPlan"), self.m_batch_group)
        self.bm_apply_btn.clicked.connect(self.on_batch_move)

        batch_form.addRow(tr("operations.entriesText"), self.bm_entries)
        batch_form.addRow(tr("operations.orUseTable"), self.bm_table)
        batch_form.addRow(tr("operations.date"), self.bm_date)
        batch_form.addRow("", self.bm_apply_btn)

    # --- PLAN TAB ---
    def _build_plan_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(9, 0, 9, 0)

        self.plan_empty_label = QLabel(tr("operations.emptyPlan"))
        self.plan_empty_label.setObjectName("operationsPlanEmptyLabel")
        self.plan_empty_label.setAlignment(Qt.AlignCenter)
        self.plan_empty_label.setWordWrap(True)
        layout.addWidget(self.plan_empty_label)

        self.plan_table = QTableWidget()
        self.plan_table.setObjectName("operationsPlanTable")
        self.plan_table.setMouseTracking(True)
        self._setup_table(
            self.plan_table,
            [
                tr("operations.colAction"),
                tr("operations.colPosition"),
                tr("operations.date"),
                tr("operations.colChanges"),
                tr("operations.colStatus"),
            ],
            sortable=False,
        )
        self.plan_table.setVisible(False)
        self.plan_table.selectionModel().selectionChanged.connect(
            lambda *_args: self._refresh_plan_toolbar_state()
        )
        layout.addWidget(self.plan_table, 1)

        toolbar = QHBoxLayout()
        self.plan_remove_selected_btn = QPushButton(tr("operations.removeSelected"))
        self.plan_remove_selected_btn.setIcon(get_icon(Icons.TRASH))
        self.plan_remove_selected_btn.setIconSize(QSize(16, 16))
        self.plan_remove_selected_btn.setEnabled(False)
        self.plan_remove_selected_btn.clicked.connect(self.remove_selected_plan_items)
        toolbar.addWidget(self.plan_remove_selected_btn)

        self.plan_exec_btn = QPushButton(tr("operations.executeAll"))
        self.plan_exec_btn.setIcon(
            get_icon(
                Icons.PLAY,
                color=resolve_theme_token("icon-on-danger", fallback="#ffffff"),
            )
        )
        self.plan_exec_btn.setIconSize(QSize(16, 16))
        self._style_execute_button(self.plan_exec_btn)
        self.plan_exec_btn.clicked.connect(self.execute_plan)
        self.plan_exec_btn.setEnabled(False)
        toolbar.addWidget(self.plan_exec_btn)

        self.plan_print_btn = QPushButton(tr("operations.print"))
        self.plan_print_btn.clicked.connect(self.print_plan)
        toolbar.addWidget(self.plan_print_btn)

        self.plan_clear_btn = QPushButton(tr("operations.clear"))
        self.plan_clear_btn.setIcon(get_icon(Icons.X))
        self.plan_clear_btn.setIconSize(QSize(16, 16))
        self.plan_clear_btn.setEnabled(False)
        self.plan_clear_btn.clicked.connect(self.clear_plan)
        toolbar.addWidget(self.plan_clear_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        return tab

    def _on_toggle_move_batch_section(self, checked):
        visible = bool(checked)
        if hasattr(self, "m_batch_group"):
            self.m_batch_group.setVisible(visible)
        if hasattr(self, "m_batch_toggle_btn"):
            self.m_batch_toggle_btn.setText(
                tr("operations.hideBatchMove") if visible else tr("operations.showBatchMove")
            )

    # --- AUDIT BACKUP ROLLBACK PANEL ---
    # --- LOGIC ---

    def _style_execute_button(self, btn):
        btn.setProperty("variant", "danger")

    def _style_stage_button(self, btn):
        btn.setProperty("variant", "primary")
        btn.setMinimumWidth(96)
        btn.setMinimumHeight(28)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _build_stage_action_button(self, label, callback):
        """Create a standardized primary action button row for operation forms."""
        btn = QPushButton(label)
        self._style_stage_button(btn)
        btn.clicked.connect(callback)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        return btn, row

    def _set_plan_feedback(self, text="", level="info"):
        label = getattr(self, "plan_feedback_label", None)
        if label is None:
            return
        message = str(text or "").strip()
        if not message:
            label.clear()
            label.setVisible(False)
            return
        level_value = level if level in {"error", "warning", "info"} else "info"
        label.setProperty("level", level_value)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setText(message)
        label.setVisible(True)

    def _ensure_today_defaults(self):
        today = QDate.currentDate()
        anchor = getattr(self, "_default_date_anchor", today)
        if today == anchor:
            return

        for attr in ("a_date", "t_date", "b_date", "m_date", "bm_date"):
            widget = getattr(self, attr, None)
            if widget is not None and widget.date() == anchor:
                widget.setDate(today)

        self._default_date_anchor = today

    def _lookup_record(self, rid):
        try:
            return self.records_cache.get(int(rid))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _clear_context_label_groups(base_labels, extra_widgets):
        for lbl in base_labels or []:
            lbl.setText("-")
        for _key, widget_pair in (extra_widgets or {}).items():
            if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
                widget_pair[1].setText("-")

    def _populate_record_context_labels(
        self,
        *,
        record,
        box_label,
        position_label,
        frozen_label,
        note_label,
        cell_line_label,
        extra_widgets,
    ):
        box = str(record.get("box") or "-")
        position = record.get("position")
        box_label.setText(box)
        position_label.setText(self._position_to_display(position) if position is not None else "-")
        frozen_label.setText(str(record.get("frozen_at") or "-"))
        note_label.setText(str(record.get("note") or "-"))
        cell_line_label.setText(str(record.get("cell_line") or "-"))
        for key, widget_pair in (extra_widgets or {}).items():
            if isinstance(widget_pair, (tuple, list)) and len(widget_pair) >= 2:
                widget_pair[1].setText(str(record.get(key) or "-"))
        return box, position

    def _set_last_event_summary_label(self, label_widget, events):
        event_list = events or []
        if event_list:
            last = event_list[-1]
            label_widget.setText(
                tr(
                    "operations.historySummary",
                    count=len(event_list),
                    date=str(last.get("date") or "-"),
                    action=str(last.get("action") or "-"),
                    positions=str(last.get("position") or "-"),
                )
            )
            return
        label_widget.setText(tr("operations.noHistory"))

    def _refresh_takeout_record_context(self):
        # Lookup record by box + position, or by ID if box/position not set
        from_box = self.t_from_box.value()
        from_pos = self._parse_position_text(self.t_from_position.text(), allow_empty=True)

        # Find record at this position
        record = None
        record_id = None

        # First try lookup by box + position
        if from_box > 0 and from_pos is not None:
            for rid, rec in self.records_cache.items():
                if rec.get("box") == from_box and rec.get("position") == from_pos:
                    record = rec
                    record_id = rid
                    break

        # If not found and ID is set, try reverse lookup by ID
        if not record and self.t_id.value() > 0:
            record_id = self.t_id.value()
            record = self.records_cache.get(record_id)
            if record:
                # Update box/position fields from record
                rec_box = record.get("box")
                rec_pos = record.get("position")
                if rec_box is not None:
                    self.t_from_box.blockSignals(True)
                    self.t_from_box.setValue(int(rec_box))
                    self.t_from_box.blockSignals(False)
                if rec_pos is not None:
                    self.t_from_position.blockSignals(True)
                    self.t_from_position.setText(self._position_to_display(rec_pos))
                    self.t_from_position.blockSignals(False)

        # Update internal ID
        if record_id:
            self.t_id.blockSignals(True)
            self.t_id.setValue(record_id)
            self.t_id.blockSignals(False)

        source_text = "-"
        if self.t_prefill_source:
            source_box = self.t_prefill_source.get("box")
            source_prefill = self.t_prefill_source.get("position")
            if source_box is not None and source_prefill is not None:
                source_text = tr(
                    "operations.boxSourceText",
                    box=source_box,
                    position=self._position_to_display(source_prefill),
                )
        self.t_ctx_source.setText(source_text)

        if not record:
            self.t_ctx_status.setText(tr("operations.recordNotFound"))
            self.t_ctx_status.setProperty("role", "statusWarning")
            self.t_ctx_status.setVisible(True)
            self.t_position.clear()
            self._clear_context_label_groups(
                [
                    self.t_ctx_box,
                    self.t_ctx_position,
                    self.t_ctx_frozen,
                    self.t_ctx_note,
                    self.t_ctx_cell_line,
                    self.t_ctx_events,
                ],
                self._takeout_ctx_widgets,
            )
            return

        self.t_ctx_status.setVisible(False)

        _box, position = self._populate_record_context_labels(
            record=record,
            box_label=self.t_ctx_box,
            position_label=self.t_ctx_position,
            frozen_label=self.t_ctx_frozen,
            note_label=self.t_ctx_note,
            cell_line_label=self.t_ctx_cell_line,
            extra_widgets=self._takeout_ctx_widgets,
        )

        # Set single position (hidden combo, kept for compat)
        self.t_position.blockSignals(True)
        self.t_position.clear()
        if position is not None:
            self.t_position.addItem(self._position_to_display(position), position)
            self.t_position.setCurrentIndex(0)
        self.t_position.blockSignals(False)

        self._set_last_event_summary_label(self.t_ctx_events, record.get("thaw_events"))

    def _confirm_warning_dialog(self, *, title, text, informative_text, detailed_text=None):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setInformativeText(informative_text)
        if detailed_text:
            msg.setDetailedText(detailed_text)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        return msg.exec() == QMessageBox.Yes

    def _confirm_execute(self, title, details):
        return self._confirm_warning_dialog(
            title=title,
            text=tr("operations.confirmModify"),
            informative_text=details,
        )

    @staticmethod
    def _format_size_bytes(size_bytes):
        try:
            value = float(size_bytes)
        except (TypeError, ValueError):
            return "-"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while value >= 1024.0 and idx < len(units) - 1:
            value /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(value)} {units[idx]}"
        return f"{value:.1f} {units[idx]}"

    def _build_rollback_confirmation_lines(
        self,
        *,
        backup_path,
        yaml_path,
        source_event=None,
        include_action_prefix=True,
    ):
        yaml_abs = os.path.abspath(str(yaml_path or ""))
        raw_backup = str(backup_path or "").strip()
        backup_abs = os.path.abspath(raw_backup) if raw_backup else ""
        backup_label = os.path.basename(backup_abs) if backup_abs else tr("operations.planRollbackLatest")

        lines = []
        restore_line = tr("operations.planRollbackRestore", backup=backup_label)
        if include_action_prefix:
            restore_line = f"{tr('operations.rollback')}: {restore_line}"
        lines.append(restore_line)
        lines.append(tr("operations.planRollbackYamlPath", path=yaml_abs or "-"))

        if backup_abs:
            lines.append(tr("operations.planRollbackBackupPath", path=backup_abs))
            try:
                stat = os.stat(backup_abs)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = self._format_size_bytes(stat.st_size)
                lines.append(tr("operations.planRollbackBackupMeta", mtime=mtime, size=size))
            except Exception:
                lines.append(tr("operations.planRollbackBackupMissing", path=backup_abs))

        if isinstance(source_event, dict) and source_event:
            timestamp = str(source_event.get("timestamp") or "-")
            action = str(source_event.get("action") or "-")
            trace_id = str(source_event.get("trace_id") or "-")
            lines.append(
                tr(
                    "operations.planRollbackSourceEvent",
                    timestamp=timestamp,
                    action=action,
                    trace_id=trace_id,
                )
            )
        return lines

    def _emit_exception_status(self, exc, timeout, level="error"):
        self.status_message.emit(str(exc), int(timeout), str(level))

    def on_add_entry(self):
        self._ensure_today_defaults()
        positions_text = self.a_positions.text().strip()

        try:
            positions = parse_positions(positions_text, layout=self._current_layout)
        except ValueError as exc:
            self._emit_exception_status(exc, 5000)
            return

        # Collect all user field values into a single dict
        fields = self._collect_custom_add_values() or {}

        # cell_line is structural but passed through fields (tool_api extracts it)
        cl = self.a_cell_line.currentText().strip()
        if cl:
            fields["cell_line"] = cl
        note = self.a_note.text().strip()
        if note:
            fields["note"] = note

        item = build_add_plan_item(
            box=self.a_box.value(),
            positions=positions,
            frozen_at=self.a_date.date().toString("yyyy-MM-dd"),
            fields=fields,
            source="human",
        )
        self.add_plan_items([item])

    def _record_takeout_with_action(self, action_text):
        action_text = str(action_text or "Takeout")
        idx = self.t_action.findData(action_text)
        if idx >= 0:
            self.t_action.setCurrentIndex(idx)
        else:
            self.t_action.setCurrentText(str(action_text))
        self.on_record_takeout()

    def on_record_takeout(self):
        self._ensure_today_defaults()
        action_text = self.t_action.currentData() or self.t_action.currentText()

        fallback_box = int((self.t_prefill_source or {}).get("box", 0) or 0)

        position = self.t_position.currentData()
        if position is None:
            self._show_error(tr("operations.positionRequired"))
            return

        item = self._build_human_record_plan_item(
            action=action_text,
            record_id=self.t_id.value(),
            position=position,
            date_str=self.t_date.date().toString("yyyy-MM-dd"),
            payload_action=action_text,
            fallback_box=fallback_box,
        )

        self.add_plan_items([item])

    def on_record_move(self):
        self._ensure_today_defaults()

        record = self._lookup_record(self.m_id.value())
        if not record:
            return

        from_pos = record.get("position")
        from_box = resolve_record_box(record, fallback_box=0)
        try:
            to_pos = self._parse_position_text(self.m_to_position.text())
        except ValueError as exc:
            self._emit_exception_status(exc, 4000)
            return
        to_box = self.m_to_box.value()

        # Check if move is to same position
        if from_pos == to_pos and from_box == to_box:
            self.status_message.emit(tr("operations.moveMustDiffer"), 4000, "error")
            return

        # Only set to_box if different from source
        to_box_param = to_box if to_box != from_box else None

        item = self._build_human_record_plan_item(
            action="move",
            record_id=self.m_id.value(),
            position=from_pos,
            date_str=self.m_date.date().toString("yyyy-MM-dd"),
            payload_action="Move",
            to_position=to_pos,
            to_box=to_box_param,
            fallback_box=from_box,
        )
        self.add_plan_items([item])

    @staticmethod
    def _read_required_table_texts(table, row, required_columns):
        texts = []
        for col in required_columns:
            cell_item = table.item(row, col)
            if not cell_item:
                return None
            cell_text = str(cell_item.text() or "").strip()
            if not cell_text:
                return None
            texts.append(cell_text)
        return texts

    def _collect_move_batch_from_table(self):
        """Collect move entries from the move batch table. Returns list of 3- or 4-tuples or None."""
        entries = []
        for row in range(self.bm_table.rowCount()):
            required_texts = self._read_required_table_texts(self.bm_table, row, (0, 1, 2))
            if not required_texts:
                continue
            id_text, from_text, to_text = required_texts
            to_box_item = self.bm_table.item(row, 3)

            try:
                entry = (
                    int(id_text),
                    self._parse_position_text(from_text),
                    self._parse_position_text(to_text),
                )
                if to_box_item:
                    tb_text = to_box_item.text().strip()
                    if tb_text:
                        entry = entry + (int(tb_text),)
                entries.append(entry)
            except ValueError as exc:
                raise ValueError(
                    tr("operations.invalidMoveRow", row=row + 1)
                ) from exc

        return entries if entries else None

    def on_batch_move(self):
        self._ensure_today_defaults()

        entries = self._resolve_batch_entries_with_fallback(
            table_collector=self._collect_move_batch_from_table,
            raw_entries_text=self.bm_entries.text(),
            timeout=3000,
        )
        if entries is None:
            return

        date_str = self.bm_date.date().toString("yyyy-MM-dd")
        items = self._build_move_batch_plan_items(entries, date_str=date_str)
        self.add_plan_items(items)

    def _on_move_source_changed(self):
        """Called when user manually changes source box/position."""
        # Reset user-specified flag so target box can auto-fill
        self._m_to_box_user_specified = False
        self._refresh_move_record_context()

    def _refresh_move_record_context(self):
        if not hasattr(self, "m_ctx_status"):
            return

        # Lookup record by box + position
        from_box = self.m_from_box.value()
        from_pos = self._parse_position_text(self.m_from_position.text(), allow_empty=True)

        # Find record at this position
        record = None
        record_id = None
        if from_pos is not None:
            for rid, rec in self.records_cache.items():
                if rec.get("box") == from_box and rec.get("position") == from_pos:
                    record = rec
                    record_id = rid
                    break

        # Update internal ID
        if record_id:
            self.m_id.blockSignals(True)
            self.m_id.setValue(record_id)
            self.m_id.blockSignals(False)

        if not record:
            self.m_ctx_status.setText(tr("operations.recordNotFound"))
            self.m_ctx_status.setProperty("role", "statusWarning")
            self.m_ctx_status.setVisible(True)
            self._clear_context_label_groups(
                [
                    self.m_ctx_box,
                    self.m_ctx_position,
                    self.m_ctx_frozen,
                    self.m_ctx_note,
                    self.m_ctx_cell_line,
                    self.m_ctx_events,
                ],
                self._move_ctx_widgets,
            )
            return

        self.m_ctx_status.setVisible(False)

        box = str(record.get("box") or "-")

        # Auto-fill target box with source box (only if not user-specified)
        if not getattr(self, "_m_to_box_user_specified", False):
            try:
                box_num = int(box)
                self.m_to_box.blockSignals(True)
                self.m_to_box.setValue(box_num)
                self.m_to_box.blockSignals(False)
            except (ValueError, TypeError):
                pass

        self._populate_record_context_labels(
            record=record,
            box_label=self.m_ctx_box,
            position_label=self.m_ctx_position,
            frozen_label=self.m_ctx_frozen,
            note_label=self.m_ctx_note,
            cell_line_label=self.m_ctx_cell_line,
            extra_widgets=self._move_ctx_widgets,
        )
        self._set_last_event_summary_label(self.m_ctx_events, record.get("thaw_events"))

    def _collect_batch_from_table(self):
        """Collect entries from the mini-table. Returns list of tuples or None if empty."""
        entries = []
        for row in range(self.b_table.rowCount()):
            required_texts = self._read_required_table_texts(self.b_table, row, (0, 1))
            if not required_texts:
                continue
            id_text, pos_text = required_texts

            try:
                entries.append((int(id_text), self._parse_position_text(pos_text)))
            except ValueError as exc:
                raise ValueError(
                    tr("operations.invalidBatchRow", row=row + 1)
                ) from exc

        return entries if entries else None

    def _resolve_batch_entries_with_fallback(
        self,
        *,
        table_collector,
        raw_entries_text,
        timeout=3000,
    ):
        """Collect batch entries from table first, then fallback to text parser."""
        try:
            entries = table_collector()
        except ValueError as exc:
            self._emit_exception_status(exc, timeout)
            return None

        if entries is not None:
            return entries

        try:
            return parse_batch_entries(
                str(raw_entries_text or "").strip(),
                layout=self._current_layout,
            )
        except ValueError as exc:
            self._emit_exception_status(exc, timeout)
            return None

    def _build_human_record_plan_item(
        self,
        *,
        action,
        record_id,
        position,
        date_str,
        payload_action,
        to_position=None,
        to_box=None,
        fallback_box=0,
    ):
        record = self._lookup_record(int(record_id))
        box = resolve_record_box(record, fallback_box=int(fallback_box or 0))
        payload = {
            "action": action,
            "record_id": int(record_id),
            "position": int(position),
            "box": box,
            "date_str": date_str,
            "source": "human",
            "payload_action": payload_action,
        }
        if to_position is not None:
            payload["to_position"] = to_position
            payload["to_box"] = to_box
        return build_record_plan_item(**payload)

    def _build_move_batch_plan_items(self, entries, *, date_str):
        """Build staged move plan items from normalized batch entries."""
        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            from_pos = int(normalized.get("position", 0) or 0)
            to_pos = normalized.get("to_position")
            to_box = normalized.get("to_box")
            if to_pos is None:
                continue

            items.append(
                self._build_human_record_plan_item(
                    action="move",
                    record_id=rid,
                    position=from_pos,
                    date_str=date_str,
                    payload_action="Move",
                    to_position=to_pos,
                    to_box=to_box,
                )
            )
        return items

    def _build_takeout_batch_plan_items(self, entries, *, date_str, action_text):
        """Build staged takeout plan items from normalized batch entries."""
        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            pos = int(normalized.get("position", 0) or 0)
            items.append(
                self._build_human_record_plan_item(
                    action=action_text,
                    record_id=rid,
                    position=pos,
                    date_str=date_str,
                    payload_action=action_text,
                )
            )
        return items

    def on_batch_takeout(self):
        self._ensure_today_defaults()

        entries = self._resolve_batch_entries_with_fallback(
            table_collector=self._collect_batch_from_table,
            raw_entries_text=self.b_entries.text(),
            timeout=3000,
        )
        if entries is None:
            return

        action_text = self.b_action.currentText()
        date_str = self.b_date.date().toString("yyyy-MM-dd")
        items = self._build_takeout_batch_plan_items(
            entries,
            date_str=date_str,
            action_text=action_text,
        )
        self.add_plan_items(items)

    _handle_response = _ops_results._handle_response
    _result_header_html = staticmethod(_ops_results._result_header_html)
    _build_add_entry_result_lines = _ops_results._build_add_entry_result_lines
    _build_single_operation_result_lines = _ops_results._build_single_operation_result_lines
    _build_batch_operation_result_lines = staticmethod(_ops_results._build_batch_operation_result_lines)
    _build_restore_result_lines = staticmethod(_ops_results._build_restore_result_lines)
    _build_success_result_lines = _ops_results._build_success_result_lines
    _display_result_summary = _ops_results._display_result_summary

    # --- PLAN OPERATIONS ---

    def _get_selected_plan_rows(self):
        if not hasattr(self, "plan_table") or self.plan_table is None:
            return []
        model = self.plan_table.selectionModel()
        if model is None:
            return []
        rows = set()
        for model_index in model.selectedIndexes():
            row = model_index.row()
            if 0 <= row < self._plan_store.count():
                rows.add(row)
        return sorted(rows)

    def _refresh_plan_toolbar_state(self):
        if not hasattr(self, "plan_table"):
            return

        rows = self._get_selected_plan_rows()
        has_selected = bool(rows)
        has_items = bool(self._plan_store.count())
        self.plan_remove_selected_btn.setEnabled(has_selected)
        self.plan_clear_btn.setEnabled(has_items)

    @Slot()
    def _on_store_changed(self):
        """Slot invoked (via QueuedConnection) when PlanStore mutates from any thread."""
        self._refresh_after_plan_items_changed()

    def _refresh_after_plan_items_changed(self):
        self._refresh_plan_table()
        self._update_execute_button_state()
        self._refresh_plan_toolbar_state()

    def remove_selected_plan_items(self):
        rows = self._get_selected_plan_rows()
        if not rows:
            self.status_message.emit(tr("operations.planNoSelection"), 2000, "warning")
            return

        items = self._plan_store.list_items()
        removed_items = [items[r] for r in rows if 0 <= r < len(items)]
        removed_count = self._plan_store.remove_by_indices(rows)
        if removed_count == 0:
            self.status_message.emit(tr("operations.planNoRemoved"), 2000, "warning")
            return

        self._publish_plan_items_notice(
            code="plan.removed",
            text=tr("operations.planRemovedCount", count=removed_count),
            level="info",
            timeout=2000,
            items=removed_items,
            count_key="removed_count",
            count_value=removed_count,
            include_total_count=True,
        )

    _plan_item_key = _ops_plan_store._plan_item_key
    _build_notice_plan_item_desc = _ops_plan_store._build_notice_plan_item_desc
    _collect_notice_action_counts_and_sample = _ops_plan_store._collect_notice_action_counts_and_sample
    _collect_plan_notice_summary = _ops_plan_store._collect_plan_notice_summary
    _publish_plan_items_notice = _ops_plan_store._publish_plan_items_notice
    _apply_preflight_report = _ops_plan_store._apply_preflight_report
    _reset_plan_feedback_and_validation = _ops_plan_store._reset_plan_feedback_and_validation
    add_plan_items = _ops_plan_store.add_plan_items
    _run_plan_preflight = _ops_plan_store._run_plan_preflight
    _update_execute_button_state = _ops_plan_store._update_execute_button_state

    _plan_value_text = staticmethod(_ops_plan_table._plan_value_text)
    _summarize_change_parts = staticmethod(_ops_plan_table._summarize_change_parts)
    _build_plan_action_text = _ops_plan_table._build_plan_action_text
    _build_plan_target_text = _ops_plan_table._build_plan_target_text
    _build_plan_date_text = _ops_plan_table._build_plan_date_text
    _build_plan_changes = _ops_plan_table._build_plan_changes
    _build_plan_status = _ops_plan_table._build_plan_status
    _refresh_plan_table = _ops_plan_table._refresh_plan_table

    execute_plan = _ops_exec.execute_plan
    _build_execute_confirmation_lines = _ops_exec._build_execute_confirmation_lines
    _confirm_execute_plan = _ops_exec._confirm_execute_plan
    _collect_execution_results = staticmethod(_ops_exec._collect_execution_results)
    _finalize_plan_store_after_execution = _ops_exec._finalize_plan_store_after_execution
    _build_execution_result_sample = _ops_exec._build_execution_result_sample
    _attempt_atomic_rollback = _ops_exec._attempt_atomic_rollback
    _emit_operation_event = _ops_exec._emit_operation_event
    _publish_system_notice = _ops_exec._publish_system_notice
    emit_external_operation_event = _ops_exec.emit_external_operation_event
    _build_execution_summary_text = _ops_exec._build_execution_summary_text
    _build_execution_rollback_notice = _ops_exec._build_execution_rollback_notice
    _build_execution_failure_lines = _ops_exec._build_execution_failure_lines
    _show_plan_result = _ops_exec._show_plan_result
    print_plan = _ops_actions.print_plan
    print_last_executed = _ops_actions.print_last_executed
    _print_items_with_grid = _ops_actions._print_items_with_grid
    _build_print_grid_state = _ops_actions._build_print_grid_state
    _print_operation_sheet_with_grid = _ops_actions._print_operation_sheet_with_grid
    clear_plan = _ops_actions.clear_plan
    reset_for_dataset_switch = _ops_actions.reset_for_dataset_switch
    on_export_inventory_csv = _ops_actions.on_export_inventory_csv
    _enable_undo = _ops_actions._enable_undo
    _update_undo_button_text = _ops_actions._update_undo_button_text
    _undo_tick = _ops_actions._undo_tick
    _disable_undo = _ops_actions._disable_undo
    on_undo_last = _ops_actions.on_undo_last





