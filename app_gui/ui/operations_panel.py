import json
import os
import tempfile
from datetime import date, datetime
from PySide6.QtCore import Qt, Signal, Slot, QDate, QEvent, QTimer, QUrl, QSize, QSortFilterProxyModel
from PySide6.QtGui import QDesktopServices, QValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCompleter,
    QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox,
    QAbstractItemView, QSizePolicy,
    QFormLayout, QDateEdit, QSpinBox, QDoubleSpinBox, QScrollArea, QTextBrowser
)
from app_gui.ui.utils import positions_to_text, cell_color
from app_gui.ui.theme import get_theme_color, FONT_SIZE_XS, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG
from app_gui.ui.icons import get_icon, Icons
from app_gui.gui_config import load_gui_config
from app_gui.i18n import tr
from app_gui.plan_model import render_operation_sheet
from app_gui.plan_gate import validate_stage_request
from app_gui.plan_outcome import summarize_plan_execution
from app_gui.plan_executor import preflight_plan, run_plan
from app_gui.system_notice import build_system_notice, coerce_system_notice
from lib.tool_api import parse_batch_entries
from lib.plan_item_factory import (
    build_add_plan_item,
    build_record_plan_item,
    build_rollback_plan_item,
    iter_batch_entries,
    resolve_record_box,
)
from lib.validators import parse_positions
from lib.position_fmt import display_to_pos, pos_to_display
from lib.plan_store import PlanStore

_ACTION_I18N_KEY = {
    "takeout": "overview.takeout",
    "thaw": "overview.thaw",
    "discard": "overview.discard",
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
        self.current_operation_mode = "thaw"
        self.t_prefill_source = None
        self._default_date_anchor = QDate.currentDate()
        self._last_operation_backup = None
        self._last_executed_plan = []
        self._plan_preflight_report = None
        self._plan_validation_by_key = {}
        self._plan_hover_row = None
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

        # Mode Selection
        self.op_mode_combo = QComboBox()
        self.op_mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        modes = [
            ("thaw", tr("operations.thaw")),
            ("move", tr("operations.move")),
            ("add", tr("operations.add")),
        ]
        for mode_key, mode_label in modes:
            self.op_mode_combo.addItem(mode_label, mode_key)
        self.op_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(9, 0, 9, 0)

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
        layout.addLayout(mode_row)

        # Stack
        self.op_stack = QStackedWidget()
        self.op_mode_indexes = {
            "add": self.op_stack.addWidget(self._build_add_tab()),
            "thaw": self.op_stack.addWidget(self._build_thaw_tab()),
            "move": self.op_stack.addWidget(self._build_move_tab()),
        }
        layout.addWidget(self.op_stack, 2)

        # Inline feedback near operation forms (more visible than status bar).
        self.plan_feedback_label = QLabel("")
        self.plan_feedback_label.setObjectName("operationsPlanFeedback")
        self.plan_feedback_label.setProperty("level", "info")
        self.plan_feedback_label.setWordWrap(True)
        self.plan_feedback_label.setVisible(False)
        feedback_row = QHBoxLayout()
        feedback_row.setContentsMargins(9, 0, 9, 0)
        feedback_row.addWidget(self.plan_feedback_label)
        layout.addLayout(feedback_row)

        # Plan Queue is always visible to reduce context switching.
        self.plan_panel = self._build_plan_tab()
        layout.addWidget(self.plan_panel, 3)

        # Result Summary Card
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
        layout.addLayout(result_row)

        self._sync_result_actions()

        self.set_mode("thaw")

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
        target = mode if mode in self.op_mode_indexes else "thaw"
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
        self._refresh_thaw_record_context()
        self._refresh_move_record_context()
        self._refresh_custom_fields()

    def _refresh_custom_fields(self):
        """Reload custom field definitions from YAML meta and rebuild dynamic forms."""
        from lib.custom_fields import get_effective_fields
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
        self._rebuild_ctx_user_fields("thaw", custom_fields)
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

    def _rebuild_ctx_user_fields(self, prefix, custom_fields):
        """Rebuild user field context rows in thaw/move form."""
        if prefix == "thaw":
            form = getattr(self, "_thaw_ctx_form", None)
            widgets = getattr(self, "_thaw_ctx_widgets", {})
            rid_fn = lambda: self.t_id.value()
            refresh_fn = lambda: self._refresh_thaw_record_context()
        else:
            form = getattr(self, "_move_ctx_form", None)
            widgets = getattr(self, "_move_ctx_widgets", {})
            rid_fn = lambda: self.m_id.value()
            refresh_fn = lambda: self._refresh_move_record_context()
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
        if prefix == "thaw":
            self._thaw_ctx_widgets = widgets
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
            if isinstance(widget, QSpinBox):
                raw = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
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

    def _apply_thaw_prefill(self, source_info, switch_mode=True):
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
        self._refresh_thaw_record_context()
        if switch_mode:
            self.set_mode("thaw")

    def set_prefill(self, source_info):
        self._apply_thaw_prefill(source_info, switch_mode=True)

    def set_prefill_background(self, source_info):
        self._apply_thaw_prefill(source_info, switch_mode=True)

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

    def _apply_add_prefill(self, source_info, switch_mode=True):
        payload = dict(source_info or {})
        if "box" in payload:
            self.a_box.setValue(int(payload["box"]))
        if "position" in payload:
            self.a_positions.setText(self._position_to_display(payload["position"]))
        if switch_mode:
            self.set_mode("add")

    def set_add_prefill(self, source_info):
        """Pre-fill the Add Entry form with box and position from overview."""
        self._apply_add_prefill(source_info, switch_mode=True)

    def set_add_prefill_background(self, source_info):
        """Pre-fill the Add Entry form and switch to Add mode."""
        self._apply_add_prefill(source_info, switch_mode=True)

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
            (container_widget, field_widget) — add container to form, use field for setText.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        field = QLineEdit()
        field.setReadOnly(True)
        field.setProperty("role", "contextEditable")
        row.addWidget(field, 1)

        lock_btn = QPushButton("\U0001F512")  # 🔒
        lock_btn.setObjectName("inlineLockBtn")
        lock_btn.setFixedSize(16, 16)
        lock_btn.setToolTip(tr("operations.edit"))
        row.addWidget(lock_btn)

        confirm_btn = QPushButton("\u2713")  # ✓
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
                lock_btn.setText("\U0001F513")  # 🔓
                confirm_btn.setVisible(True)
                field.setFocus()
                field.selectAll()
            else:
                # Re-lock without saving
                field.setReadOnly(True)
                lock_btn.setText("\U0001F512")  # 🔒
                confirm_btn.setVisible(False)
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
                self._publish_system_notice(
                    code="record.edit.failed",
                    text=tr("operations.editFieldFailed", error=result.get("message", "?")),
                    level="error",
                    timeout=5000,
                    data={
                        "record_id": rid,
                        "field": field_name,
                        "error_code": result.get("error_code"),
                        "message": result.get("message"),
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

        # User fields placeholder — populated by _rebuild_custom_add_fields()
        self._add_custom_form = form
        self._add_custom_widgets = {}

        self.a_apply_btn = QPushButton(tr("operations.add"))
        self._style_stage_button(self.a_apply_btn)
        self.a_apply_btn.clicked.connect(self.on_add_entry)
        a_btn_row = QHBoxLayout()
        a_btn_row.addWidget(self.a_apply_btn)
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
                    try:
                        widget.setValue(int(default))
                    except (ValueError, TypeError):
                        pass
            elif ftype == "float":
                widget = QDoubleSpinBox()
                widget.setRange(-999999.0, 999999.0)
                widget.setDecimals(3)
                if default is not None:
                    try:
                        widget.setValue(float(default))
                    except (ValueError, TypeError):
                        pass
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

    # --- THAW TAB ---
    def _build_thaw_tab(self):
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
        self.t_from_box.valueChanged.connect(self._refresh_thaw_record_context)
        source_row.addWidget(self.t_from_box)

        colon_label = QLabel(":")
        colon_label.setProperty("role", "mutedInline")
        source_row.addWidget(colon_label)

        self.t_from_position = QLineEdit()
        self.t_from_position.setFixedWidth(60)
        self.t_from_position.textChanged.connect(self._refresh_thaw_record_context)
        source_row.addWidget(self.t_from_position)

        source_row.addStretch()

        form.addRow(tr("operations.from"), source_row)

        # Hidden internal record ID (auto-filled from box:position lookup)
        self.t_id = QSpinBox()
        self.t_id.setRange(1, 999999)
        self.t_id.setVisible(False)
        # Connect signal to refresh context when ID is changed (for reverse lookup)
        self.t_id.valueChanged.connect(self._refresh_thaw_record_context)

        _t_rid = lambda: self.t_id.value()
        _t_refresh = lambda: self._refresh_thaw_record_context()

        # Editable context fields — frozen_at/note are core fields.
        t_frozen_w, self.t_ctx_frozen = self._make_editable_field("frozen_at", _t_rid, _t_refresh)
        t_note_w, self.t_ctx_note = self._make_editable_field("note", _t_rid, _t_refresh)
        t_cell_line_w, self.t_ctx_cell_line = self._make_editable_field(
            "cell_line",
            _t_rid,
            _t_refresh,
            choices_provider=self._cell_line_choice_config,
        )

        # Dynamic user field context widgets (populated by _rebuild_thaw_ctx_fields)
        self._thaw_ctx_form = form
        self._thaw_ctx_widgets = {}  # key -> (container_widget, label_widget)

        # Read-only context fields (not editable via inline edit) - kept for compatibility
        self.t_ctx_box = self._make_readonly_field()
        self.t_ctx_position = self._make_readonly_field()
        self.t_ctx_events = self._make_readonly_history_label()
        self.t_ctx_source = self._make_readonly_field()

        # User fields placeholder — will be rebuilt dynamically
        self._thaw_ctx_insert_row = form.rowCount()

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

        # Action buttons at bottom
        btn_row = QHBoxLayout()
        self.t_takeout_btn = QPushButton(tr("overview.takeout"))
        for btn in (self.t_takeout_btn,):
            self._style_stage_button(btn)
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        self.t_takeout_btn.clicked.connect(lambda: self._record_thaw_with_action("Takeout"))
        # Keep t_apply_btn as alias for the first button (compat)
        self.t_apply_btn = self.t_takeout_btn
        form.addRow("", btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_thaw_controls(tab)
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

        _m_rid = lambda: self.m_id.value()
        _m_refresh = lambda: self._refresh_move_record_context()

        # Editable context fields — frozen_at/note are core fields.
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

        # User fields placeholder — will be rebuilt dynamically
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

        # Button at bottom
        m_btn_row = QHBoxLayout()
        self.m_apply_btn = QPushButton(tr("operations.move"))
        self._style_stage_button(self.m_apply_btn)
        self.m_apply_btn.clicked.connect(self.on_record_move)
        m_btn_row.addWidget(self.m_apply_btn)
        form.addRow("", m_btn_row)

        layout.addLayout(form)

        # Keep batch controls instantiated for programmatic/API paths, but hide from manual UI.
        self._init_hidden_batch_move_controls(tab)
        layout.addStretch(1)
        return tab

    def _init_hidden_batch_thaw_controls(self, parent):
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
        self.b_apply_btn.clicked.connect(self.on_batch_thaw)

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
        self.plan_table.cellEntered.connect(self._on_plan_cell_entered)
        self._setup_table(
            self.plan_table,
            [
                tr("operations.colAction"),
                tr("operations.colPosition"),
                tr("operations.date"),
                tr("operations.colChanges"),
                tr("operations.colNote"),
                tr("operations.colStatus"),
            ],
            sortable=False,
        )
        self.plan_table.viewport().installEventFilter(self)
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
        self.plan_exec_btn.setIcon(get_icon(Icons.PLAY, color="#ffffff"))  # White icon for danger variant
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
        btn.setMinimumWidth(80)

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

    def _refresh_thaw_record_context(self):
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
            for lbl in [self.t_ctx_box, self.t_ctx_position, self.t_ctx_frozen, self.t_ctx_note,
                        self.t_ctx_cell_line, self.t_ctx_events]:
                lbl.setText("-")
            for key, (container, lbl) in self._thaw_ctx_widgets.items():
                lbl.setText("-")
            return

        self.t_ctx_status.setVisible(False)

        box = str(record.get("box") or "-")
        position = record.get("position")

        self.t_ctx_box.setText(box)
        self.t_ctx_position.setText(self._position_to_display(position) if position is not None else "-")
        self.t_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
        self.t_ctx_note.setText(str(record.get("note") or "-"))
        self.t_ctx_cell_line.setText(str(record.get("cell_line") or "-"))
        # Populate dynamic user field context
        for key, (container, lbl) in self._thaw_ctx_widgets.items():
            lbl.setText(str(record.get(key) or "-"))

        # Set single position (hidden combo, kept for compat)
        self.t_position.blockSignals(True)
        self.t_position.clear()
        if position is not None:
            self.t_position.addItem(self._position_to_display(position), position)
            self.t_position.setCurrentIndex(0)
        self.t_position.blockSignals(False)

        # History
        events = record.get("thaw_events") or []
        if events:
            last = events[-1]
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_pos = str(last.get("position") or "-")
            self.t_ctx_events.setText(
                tr(
                    "operations.historySummary",
                    count=len(events),
                    date=last_date,
                    action=last_action,
                    positions=last_pos,
                )
            )
        else:
            self.t_ctx_events.setText(tr("operations.noHistory"))

    def _confirm_execute(self, title, details):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText(tr("operations.confirmModify"))
        msg.setInformativeText(details)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        return msg.exec() == QMessageBox.Yes

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

    def on_add_entry(self):
        self._ensure_today_defaults()
        positions_text = self.a_positions.text().strip()

        try:
            positions = parse_positions(positions_text, layout=self._current_layout)
        except ValueError as exc:
            self.status_message.emit(str(exc), 5000, "error")
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

    def _record_thaw_with_action(self, action_text):
        action_alias = {"Thaw": "Takeout", "Discard": "Takeout"}
        action_text = action_alias.get(str(action_text), str(action_text or "Takeout"))
        idx = self.t_action.findData(action_text)
        if idx >= 0:
            self.t_action.setCurrentIndex(idx)
        else:
            self.t_action.setCurrentText(str(action_text))
        self.on_record_thaw()

    def on_record_thaw(self):
        self._ensure_today_defaults()
        action_text = self.t_action.currentData() or self.t_action.currentText()

        record = self._lookup_record(self.t_id.value())
        fallback_box = int((self.t_prefill_source or {}).get("box", 0) or 0)
        box = resolve_record_box(record, fallback_box=fallback_box)
        item = build_record_plan_item(
            action=action_text,
            record_id=self.t_id.value(),
            position=self.t_position.currentData(),
            box=box,
            date_str=self.t_date.date().toString("yyyy-MM-dd"),
            source="human",
            payload_action=action_text,
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
            self.status_message.emit(str(exc), 4000, "error")
            return
        to_box = self.m_to_box.value()

        # Check if move is to same position
        if from_pos == to_pos and from_box == to_box:
            self.status_message.emit(tr("operations.moveMustDiffer"), 4000, "error")
            return

        # Only set to_box if different from source
        to_box_param = to_box if to_box != from_box else None

        item = build_record_plan_item(
            action="move",
            record_id=self.m_id.value(),
            position=from_pos,
            box=from_box,
            date_str=self.m_date.date().toString("yyyy-MM-dd"),
            to_position=to_pos,
            to_box=to_box_param,
            source="human",
            payload_action="Move",
        )
        self.add_plan_items([item])

    def _collect_move_batch_from_table(self):
        """Collect move entries from the move batch table. Returns list of 3- or 4-tuples or None."""
        entries = []
        for row in range(self.bm_table.rowCount()):
            id_item = self.bm_table.item(row, 0)
            from_item = self.bm_table.item(row, 1)
            to_item = self.bm_table.item(row, 2)
            to_box_item = self.bm_table.item(row, 3)

            if not id_item or not from_item or not to_item:
                continue

            id_text = id_item.text().strip()
            from_text = from_item.text().strip()
            to_text = to_item.text().strip()

            if not id_text or not from_text or not to_text:
                continue

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

        try:
            entries = self._collect_move_batch_from_table()
        except ValueError as exc:
            self.status_message.emit(str(exc), 3000, "error")
            return

        if entries is None:
            entries_text = self.bm_entries.text().strip()
            try:
                entries = parse_batch_entries(entries_text, layout=self._current_layout)
            except ValueError as exc:
                self.status_message.emit(str(exc), 3000, "error")
                return

        date_str = self.bm_date.date().toString("yyyy-MM-dd")

        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            from_pos = int(normalized.get("position", 0) or 0)
            to_pos = normalized.get("to_position")
            to_box = normalized.get("to_box")
            if to_pos is None:
                continue

            record = self._lookup_record(rid)
            box = resolve_record_box(record, fallback_box=0)
            items.append(
                build_record_plan_item(
                    action="move",
                    record_id=rid,
                    position=from_pos,
                    box=box,
                    date_str=date_str,
                    to_position=to_pos,
                    to_box=to_box,
                    source="human",
                    payload_action="Move",
                )
            )

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
            for lbl in [self.m_ctx_box, self.m_ctx_position, self.m_ctx_frozen, self.m_ctx_note,
                        self.m_ctx_cell_line, self.m_ctx_events]:
                lbl.setText("-")
            for key, (container, lbl) in self._move_ctx_widgets.items():
                lbl.setText("-")
            return

        self.m_ctx_status.setVisible(False)

        box = str(record.get("box") or "-")
        position = record.get("position")

        # Auto-fill target box with source box (only if not user-specified)
        if not getattr(self, "_m_to_box_user_specified", False):
            try:
                box_num = int(box)
                self.m_to_box.blockSignals(True)
                self.m_to_box.setValue(box_num)
                self.m_to_box.blockSignals(False)
            except (ValueError, TypeError):
                pass

        self.m_ctx_box.setText(box)
        self.m_ctx_position.setText(self._position_to_display(position) if position is not None else "-")
        self.m_ctx_frozen.setText(str(record.get("frozen_at") or "-"))
        self.m_ctx_note.setText(str(record.get("note") or "-"))
        self.m_ctx_cell_line.setText(str(record.get("cell_line") or "-"))
        # Populate dynamic user field context
        for key, (container, lbl) in self._move_ctx_widgets.items():
            lbl.setText(str(record.get(key) or "-"))

        events = record.get("thaw_events") or []
        if events:
            last = events[-1]
            last_date = str(last.get("date") or "-")
            last_action = str(last.get("action") or "-")
            last_pos = str(last.get("position") or "-")
            self.m_ctx_events.setText(
                tr(
                    "operations.historySummary",
                    count=len(events),
                    date=last_date,
                    action=last_action,
                    positions=last_pos,
                )
            )
        else:
            self.m_ctx_events.setText(tr("operations.noHistory"))

    def _collect_batch_from_table(self):
        """Collect entries from the mini-table. Returns list of tuples or None if empty."""
        entries = []
        for row in range(self.b_table.rowCount()):
            id_item = self.b_table.item(row, 0)
            pos_item = self.b_table.item(row, 1)

            if not id_item or not pos_item:
                continue

            id_text = id_item.text().strip()
            pos_text = pos_item.text().strip()

            if not id_text or not pos_text:
                continue

            try:
                entries.append((int(id_text), self._parse_position_text(pos_text)))
            except ValueError as exc:
                raise ValueError(
                    tr("operations.invalidBatchRow", row=row + 1)
                ) from exc

        return entries if entries else None

    def on_batch_thaw(self):
        self._ensure_today_defaults()

        # Try table first, fall back to text input
        try:
            entries = self._collect_batch_from_table()
        except ValueError as exc:
            self.status_message.emit(str(exc), 3000, "error")
            return

        if entries is None:
            entries_text = self.b_entries.text().strip()
            try:
                entries = parse_batch_entries(entries_text, layout=self._current_layout)
            except ValueError as exc:
                self.status_message.emit(str(exc), 3000, "error")
                return

        action_text = self.b_action.currentText()
        date_str = self.b_date.date().toString("yyyy-MM-dd")

        items = []
        for normalized in iter_batch_entries(entries):
            rid = int(normalized.get("record_id", 0) or 0)
            pos = int(normalized.get("position", 0) or 0)
            record = self._lookup_record(rid)
            box = resolve_record_box(record, fallback_box=0)
            items.append(
                build_record_plan_item(
                    action=action_text,
                    record_id=rid,
                    position=pos,
                    box=box,
                    date_str=date_str,
                    source="human",
                    payload_action=action_text,
                )
            )

        self.add_plan_items(items)

    def _handle_response(self, response, context, *, notice_code=None, notice_data=None):
        payload = response if isinstance(response, dict) else {}
        self._display_result_summary(response, context)

        ok = payload.get("ok", False)
        msg = payload.get("message", tr("operations.unknownResult"))
        code = str(notice_code or ("operation.success" if ok else "operation.failed"))

        if ok:
            self._publish_system_notice(
                code=code,
                text=tr("operations.contextSuccess", context=context),
                level="success",
                timeout=3000,
                data=notice_data if isinstance(notice_data, dict) else None,
            )
            self.operation_completed.emit(True)
            # Enable undo if backup_path available
            backup_path = payload.get("backup_path")
            if backup_path:
                self._last_operation_backup = backup_path
                self._enable_undo(timeout_sec=30)
        else:
            self._publish_system_notice(
                code=code,
                text=tr("operations.contextFailed", context=context, error=msg),
                level="error",
                timeout=5000,
                data=notice_data if isinstance(notice_data, dict) else {"message": msg, "error_code": payload.get("error_code")},
            )
            self.operation_completed.emit(False)

    def _display_result_summary(self, response, context):
        """Show a human-readable summary card for the operation result."""
        payload = response if isinstance(response, dict) else {}
        ok = payload.get("ok", False)
        preview = payload.get("preview", {}) or {}
        result = payload.get("result", {}) or {}

        if ok:
            lines = [f"<b style='color: var(--status-success);'>{tr('operations.contextResultSuccess', context=context)}</b>"]

            if context == "Add Entry":
                new_ids = result.get("new_ids") or []
                new_id = result.get("new_id", "?")
                fields = preview.get("fields") or {}
                from lib.custom_fields import get_display_key
                dk = get_display_key(None)
                cell = str(fields.get("cell_line", ""))
                short = str(fields.get(dk, ""))
                box = preview.get("box", "")
                positions = preview.get("positions", [])
                pos_text = self._positions_to_display_text(positions)
                if new_ids:
                    ids_text = ", ".join(str(i) for i in new_ids)
                    lines.append(
                        tr(
                            "operations.addedTubesSummary",
                            count=len(new_ids),
                            ids=ids_text,
                            cell=cell,
                            short=short,
                            box=box,
                            positions=pos_text,
                        )
                    )
                else:
                    lines.append(
                        tr(
                            "operations.addedTubeSummary",
                            id=new_id,
                            cell=cell,
                            short=short,
                            box=box,
                            positions=pos_text,
                        )
                    )

            elif context == "Single Operation":
                rid = preview.get("record_id", "?")
                action = preview.get("action_en", preview.get("action_cn", ""))
                pos = self._position_to_display(preview.get("position", "?"))
                to_pos = preview.get("to_position")
                before = preview.get("positions_before", [])
                after = preview.get("positions_after", [])
                if to_pos is not None:
                    lines.append(
                        tr(
                            "operations.operationRowActionWithTarget",
                            rid=rid,
                            action=action,
                            pos=pos,
                            to_pos=self._position_to_display(to_pos),
                        )
                    )
                else:
                    lines.append(
                        tr("operations.operationRowActionWithPosition", rid=rid, action=action, pos=pos)
                    )
                if before or after:
                    lines.append(
                        tr(
                            "operations.operationPositionsTransition",
                            before=self._positions_to_display_text(before),
                            after=self._positions_to_display_text(after),
                        )
                    )

            elif context == "Batch Operation":
                count = result.get("count", preview.get("count", 0))
                ids = result.get("record_ids", [])
                lines.append(
                    tr(
                        "operations.processedBatchEntries",
                        count=count,
                        ids=", ".join(str(i) for i in ids),
                    )
                )

            elif context == "Rollback" or context == "Undo":
                restored = result.get("restored_from", "?")
                lines.append(
                    tr("operations.restoredFrom", path=os.path.basename(str(restored)))
                )

            self._set_result_summary_html(lines)
            self.result_card.setProperty("state", "success")
            self.result_card.style().unpolish(self.result_card)
            self.result_card.style().polish(self.result_card)
        else:
            msg = payload.get("message", tr("operations.unknownError"))
            error_code = payload.get("error_code", "")
            lines = [f"<b style='color: var(--status-error);'>{tr('operations.contextResultFailed', context=context)}</b>"]
            lines.append(str(msg))
            if error_code:
                lines.append(f"<span style='color: var(--status-muted);'>{tr('operations.codeLabel', code=error_code)}</span>")
            self._set_result_summary_html(lines)
            self.result_card.setProperty("state", "error")
            self.result_card.style().unpolish(self.result_card)
            self.result_card.style().polish(self.result_card)

        self.result_card.setVisible(True)

    # --- PLAN OPERATIONS ---

    def eventFilter(self, obj, event):
        """Handle plan table hover-leave to clear Overview execution preview."""
        try:
            if hasattr(self, "plan_table") and obj is self.plan_table.viewport():
                if event.type() == QEvent.Leave:
                    pass  # Preview system removed
        except Exception:
            pass
        return super().eventFilter(obj, event)

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
        first = rows[0] if has_selected else -1
        last = rows[-1] if has_selected else -1

        if not has_selected:
            self.plan_remove_selected_btn.setEnabled(False)
        else:
            self.plan_remove_selected_btn.setEnabled(True)

        self.plan_clear_btn.setEnabled(has_items)

    def _select_plan_rows(self, rows):
        if not hasattr(self, "plan_table"):
            return

        self.plan_table.clearSelection()
        for row in sorted(set(rows)):
            if 0 <= row < self.plan_table.rowCount():
                self.plan_table.selectRow(row)

    @Slot()
    def _on_store_changed(self):
        """Slot invoked (via QueuedConnection) when PlanStore mutates from any thread."""
        self._refresh_after_plan_items_changed(emit_preview=True)

    def _refresh_after_plan_items_changed(self, emit_preview=True):
        self._plan_hover_row = None
        self._refresh_plan_table()
        self._update_execute_button_state()
        self._refresh_plan_toolbar_state()

    def _on_plan_cell_entered(self, row, _col):
        if row < 0 or row >= self._plan_store.count():
            return
        if row == self._plan_hover_row:
            return
        self._plan_hover_row = row
        # Preview system removed

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

        action_counts, sample = self._collect_notice_action_counts_and_sample(removed_items)

        self._publish_system_notice(
            code="plan.removed",
            text=tr("operations.planRemovedCount", count=removed_count),
            level="info",
            timeout=2000,
            details="\n".join(sample[:8]) if sample else None,
            data={
                "removed_count": removed_count,
                "total_count": self._plan_store.count(),
                "action_counts": action_counts,
                "sample": sample,
            },
        )

    def _remove_plan_rows(self, rows):
        if not rows:
            return 0
        removed_count = self._plan_store.remove_by_indices(rows)
        return removed_count

    def _plan_item_key(self, item):
        """Generate a unique key for plan item deduplication."""
        return PlanStore.item_key(item)

    def _build_notice_plan_item_desc(self, item):
        """Build a compact action/target summary for notices."""
        payload = item.get("payload") if isinstance(item, dict) else {}
        payload = payload if isinstance(payload, dict) else {}

        action = str((item or {}).get("action") or "?")
        label = (item or {}).get("label")
        record_id = (item or {}).get("record_id")
        subject = "-"
        if label not in (None, ""):
            subject = str(label)
        elif record_id not in (None, ""):
            subject = str(record_id)

        desc = f"{action} {subject}"
        box = (item or {}).get("box")
        pos = (item or {}).get("position")
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        if box not in (None, "") and pos not in (None, ""):
            desc += f" @ Box {box}:{self._position_to_display(pos)}"
        elif box not in (None, "") and positions:
            preview = ",".join(self._position_to_display(p) for p in positions[:4])
            if len(positions) > 4:
                preview += f",+{len(positions) - 4}"
            desc += f" @ Box {box}:{preview}"

        to_pos = (item or {}).get("to_position")
        to_box = (item or {}).get("to_box")
        if to_pos not in (None, ""):
            if to_box not in (None, ""):
                desc += f" -> Box {to_box}:{self._position_to_display(to_pos)}"
            else:
                desc += f" -> {self._position_to_display(to_pos)}"
        return desc

    def _collect_notice_action_counts_and_sample(self, items, max_sample=8):
        """Return (action_counts, sample_lines) for notice payloads."""
        action_counts = {}
        sample = []
        for item in items or []:
            action = str(item.get("action") or "?")
            action_counts[action] = action_counts.get(action, 0) + 1
            if len(sample) < max_sample:
                sample.append(self._build_notice_plan_item_desc(item))
        return action_counts, sample

    def add_plan_items(self, items):
        """Validate and add items to the plan staging area atomically."""
        incoming = list(items or [])
        if not incoming:
            return

        self._set_plan_feedback("")

        gate = validate_stage_request(
            existing_items=self._plan_store.list_items(),
            incoming_items=incoming,
            yaml_path=self.yaml_path_getter(),
            bridge=self.bridge,
            run_preflight=True,
        )

        report = gate.get("preflight_report")
        self._plan_preflight_report = report if isinstance(report, dict) else None
        self._plan_validation_by_key = {}
        if isinstance(self._plan_preflight_report, dict):
            for report_item in self._plan_preflight_report.get("items") or []:
                item = report_item.get("item") if isinstance(report_item, dict) else None
                if not isinstance(item, dict):
                    continue
                key = self._plan_item_key(item)
                self._plan_validation_by_key[key] = {
                    "ok": report_item.get("ok"),
                    "blocked": report_item.get("blocked"),
                    "error_code": report_item.get("error_code"),
                    "message": report_item.get("message"),
                }

        blocked_messages = []
        for blocked in gate.get("blocked_items", []):
            err = blocked.get("message") or blocked.get("error_code") or "invalid plan item"
            if err not in blocked_messages:
                blocked_messages.append(str(err))

        if blocked_messages:
            first = blocked_messages[0]
            user_text = tr("operations.planRejected", error=first)
            preview = blocked_messages[:3]
            feedback = "\n".join(f"- {msg}" for msg in preview)
            if len(blocked_messages) > 3:
                feedback += f"\n... +{len(blocked_messages) - 3}"
            self._set_plan_feedback(feedback, level="error")
            self._publish_system_notice(
                code="plan.stage.blocked",
                text=user_text,
                level="error",
                timeout=5000,
                details=feedback,
                data={
                    "blocked_items": gate.get("blocked_items") if isinstance(gate.get("blocked_items"), list) else [],
                    "errors": gate.get("errors") if isinstance(gate.get("errors"), list) else [],
                    "stats": gate.get("stats") if isinstance(gate.get("stats"), dict) else {},
                    "incoming_items": incoming,
                },
            )
            return

        accepted = list(gate.get("accepted_items") or [])
        if not accepted:
            return

        added = self._plan_store.add(accepted)

        if added:
            self._refresh_after_plan_items_changed(emit_preview=False)
            self._set_plan_feedback("")

            action_counts, sample = self._collect_notice_action_counts_and_sample(accepted)

            self._publish_system_notice(
                code="plan.stage.accepted",
                text=tr("operations.planAddedCount", count=added),
                level="info",
                timeout=2000,
                details="\n".join(sample[:8]) if sample else None,
                data={
                    "added_count": added,
                    "total_count": self._plan_store.count(),
                    "action_counts": action_counts,
                    "sample": sample,
                    "items": accepted,
                },
            )

    def _run_plan_preflight(self, trigger="manual"):
        """Run preflight validation on current plan items."""
        self._plan_validation_by_key = {}
        plan_items = self._plan_store.list_items()
        if not plan_items:
            self._plan_preflight_report = None
            return

        yaml_path = self.yaml_path_getter()
        if not os.path.isfile(yaml_path):
            self._plan_preflight_report = {"ok": True, "blocked": False, "items": [], "stats": {"total": len(plan_items), "ok": len(plan_items), "blocked": 0}}
            return

        report = preflight_plan(yaml_path, plan_items, self.bridge)

        self._plan_preflight_report = report
        report_items = report.get("items") if isinstance(report.get("items"), list) else []
        for r in report_items:
            item = r.get("item")
            if item:
                key = self._plan_item_key(item)
                self._plan_validation_by_key[key] = {
                    "ok": r.get("ok"),
                    "blocked": r.get("blocked"),
                    "error_code": r.get("error_code"),
                    "message": r.get("message"),
                }

    def _update_execute_button_state(self):
        """Enable/disable Execute button based on preflight results."""
        if not self._plan_store.count():
            self.plan_exec_btn.setEnabled(False)
            return

        has_blocked = any(
            v.get("blocked") for v in self._plan_validation_by_key.values()
        )
        self.plan_exec_btn.setEnabled(not has_blocked)
        if has_blocked:
            blocked_count = sum(1 for v in self._plan_validation_by_key.values() if v.get("blocked"))
            self.plan_exec_btn.setText(
                tr("operations.executePlanBlocked", count=blocked_count)
            )
        else:
            self.plan_exec_btn.setText(tr("operations.executeAll"))

    @staticmethod
    def _plan_value_text(value):
        """Render field values in table-friendly text form."""
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(value)
        return str(value)

    @staticmethod
    def _summarize_change_parts(parts, max_parts=3):
        """Build short summary + full detail for the Changes column."""
        cleaned = [str(part).strip() for part in parts if str(part).strip()]
        if not cleaned:
            return "-", ""

        shown = cleaned[:max_parts]
        summary = "; ".join(shown)
        if len(cleaned) > max_parts:
            summary += f"; ... +{len(cleaned) - max_parts}"
        return summary, "\n".join(cleaned)

    def _build_plan_action_text(self, action_norm, item):
        record_id = item.get("record_id")
        if action_norm == "rollback":
            return tr("operations.rollback")
        if action_norm == "add":
            return tr("operations.add")

        action_label = _localized_action(str(item.get("action", "") or ""))
        return f"{action_label} (ID {record_id})" if record_id else action_label

    def _build_plan_target_text(self, action_norm, item, payload):
        if action_norm == "rollback":
            return "-"

        box = item.get("box", "")
        pos = item.get("position", "")
        pos_text = self._position_to_display(pos)

        if action_norm == "add":
            positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
            if not positions:
                return f"{box}: ?"
            shown = ", ".join(self._position_to_display(p) for p in positions[:6])
            suffix = f", ... +{len(positions) - 6}" if len(positions) > 6 else ""
            return f"{box}: [{shown}{suffix}]"

        to_pos = item.get("to_position")
        to_box = item.get("to_box")
        to_pos_text = self._position_to_display(to_pos)
        if to_pos and (to_box is None or to_box == box):
            return f"{box}:{pos_text} -> {to_pos_text}"
        if to_pos and to_box:
            return f"{box}:{pos_text} -> {to_box}:{to_pos_text}"
        return f"{box}:{pos_text}"

    def _build_plan_date_text(self, action_norm, payload):
        if action_norm == "rollback":
            source_event = payload.get("source_event") if isinstance(payload, dict) else None
            if isinstance(source_event, dict) and source_event.get("timestamp"):
                return str(source_event.get("timestamp"))
            return ""
        if action_norm == "add":
            return str(payload.get("frozen_at", ""))
        return str(payload.get("date_str", ""))

    def _build_plan_changes(self, action_norm, item, payload, custom_fields):
        record_id = item.get("record_id")
        record = self.records_cache.get(record_id) if record_id in self.records_cache else {}
        label_map = {
            str(fdef.get("key")): str(fdef.get("label") or fdef.get("key"))
            for fdef in custom_fields
            if isinstance(fdef, dict) and fdef.get("key")
        }
        # Keep human-friendly labels for common built-in keys even when
        # custom_fields is empty.
        label_map.setdefault("short_name", tr("operations.shortName"))
        label_map.setdefault("cell_line", tr("operations.cellLine"))
        label_map.setdefault("frozen_at", tr("operations.frozenDate"))
        label_map.setdefault("box", tr("operations.box"))
        label_map.setdefault("position", tr("operations.position"))
        label_map.setdefault("note", tr("operations.note"))

        parts = []
        detail_parts = []  # For tooltip

        if action_norm == "rollback":
            source_event = payload.get("source_event") if isinstance(payload, dict) else None
            if isinstance(source_event, dict) and source_event:
                parts.append(
                    tr(
                        "operations.planRollbackSourceEvent",
                        timestamp=str(source_event.get("timestamp") or "-"),
                        action=str(source_event.get("action") or "-"),
                        trace_id=str(source_event.get("trace_id") or "-"),
                    )
                )
            backup_path = payload.get("backup_path") if isinstance(payload, dict) else None
            if backup_path:
                parts.append(tr("operations.planRollbackBackupPath", path=os.path.basename(str(backup_path))))
                # Add backup file metadata to tooltip
                backup_abs = os.path.abspath(str(backup_path))
                try:
                    stat = os.stat(backup_abs)
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size = self._format_size_bytes(stat.st_size)
                    detail_parts.append(tr("operations.planRollbackBackupMeta", mtime=mtime, size=size))
                except Exception:
                    detail_parts.append(tr("operations.planRollbackBackupMissing", path=backup_abs))

        elif action_norm == "add":
            fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
            for key, value in fields.items():
                value_text = self._plan_value_text(value)
                if not value_text:
                    continue
                label = label_map.get(str(key), str(key))
                parts.append(f"{label}={value_text}")

        elif action_norm == "edit":
            fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
            for key, new_value in fields.items():
                label = label_map.get(str(key), str(key))
                old_value = record.get(key, "") if isinstance(record, dict) else ""
                old_text = self._plan_value_text(old_value)
                new_text = self._plan_value_text(new_value)
                if old_text == new_text:
                    parts.append(f"{label}: {new_text}")
                else:
                    parts.append(f"{label}: {old_text} -> {new_text}")

        else:
            if isinstance(record, dict) and record:
                cell_line = self._plan_value_text(record.get("cell_line", ""))
                if cell_line:
                    parts.append(f"cell_line={cell_line}")
                for fdef in custom_fields:
                    key = str((fdef or {}).get("key") or "")
                    if not key or key == "note":
                        continue
                    value_text = self._plan_value_text(record.get(key, ""))
                    if value_text:
                        label = str((fdef or {}).get("label") or key)
                        parts.append(f"{label}={value_text}")

        summary, base_detail = self._summarize_change_parts(parts, max_parts=3)
        # Combine base detail with additional detail parts
        if detail_parts:
            combined_detail = base_detail + "\n" + "\n".join(detail_parts) if base_detail else "\n".join(detail_parts)
            return summary, combined_detail
        return summary, base_detail

    def _build_plan_note(self, action_norm, payload, yaml_path_for_rollback):
        if action_norm != "rollback":
            return "", ""

        backup_path = payload.get("backup_path") if isinstance(payload, dict) else None
        source_event = payload.get("source_event") if isinstance(payload, dict) else None
        note = ""
        if isinstance(source_event, dict) and source_event:
            note = tr(
                "operations.planRollbackSourceEvent",
                timestamp=str(source_event.get("timestamp") or "-"),
                action=str(source_event.get("action") or "-"),
                trace_id=str(source_event.get("trace_id") or "-"),
            )
        elif backup_path:
            backup_abs = os.path.abspath(str(backup_path))
            try:
                stat = os.stat(backup_abs)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = self._format_size_bytes(stat.st_size)
                note = tr("operations.planRollbackBackupMeta", mtime=mtime, size=size)
            except Exception:
                note = tr("operations.planRollbackBackupMissing", path=backup_abs)

        tooltip = ""
        if backup_path or source_event:
            rollback_lines = self._build_rollback_confirmation_lines(
                backup_path=backup_path,
                yaml_path=yaml_path_for_rollback,
                source_event=source_event,
                include_action_prefix=False,
            )
            tooltip = "\n".join(rollback_lines)
        return str(note), tooltip

    def _build_plan_status(self, item):
        validation = self._plan_validation_by_key.get(self._plan_item_key(item)) or {}
        if validation.get("blocked"):
            return tr("operations.planStatusBlocked"), str(validation.get("message") or "")
        return tr("operations.planStatusReady"), str(validation.get("message") or "")

    def _refresh_plan_table(self):
        from lib.custom_fields import get_color_key
        from PySide6.QtGui import QColor

        has_items = bool(self._plan_store.count())
        self.plan_empty_label.setVisible(not has_items)
        self.plan_table.setVisible(has_items)
        self._plan_hover_row = None

        # Unified mixed-action preview table: fixed columns + Changes summary.
        custom_fields = self._current_custom_fields
        meta = self._current_meta
        color_key = get_color_key(meta)
        headers = [
            tr("operations.colAction"),
            tr("operations.colPosition"),
            tr("operations.date"),
            tr("operations.colChanges"),
            tr("operations.colStatus"),
        ]

        self._setup_table(
            self.plan_table,
            headers,
            sortable=False,
        )

        header = self.plan_table.horizontalHeader()
        # Enable interactive column resizing (like Overview table)
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Set initial column widths
        for idx in range(len(headers)):
            if idx == 3:  # Changes column - wider (includes rollback details)
                self.plan_table.setColumnWidth(idx, 250)
            else:
                self.plan_table.setColumnWidth(idx, 120)

        plan_items = self._plan_store.list_items()
        yaml_path_for_rollback = os.path.abspath(str(self.yaml_path_getter()))
        for row, item in enumerate(plan_items):
            self.plan_table.insertRow(row)
            action_text = str(item.get("action", "") or "")
            action_norm = action_text.lower()
            payload = item.get("payload") or {}

            action_item = QTableWidgetItem(self._build_plan_action_text(action_norm, item))
            self.plan_table.setItem(row, 0, action_item)

            target_item = QTableWidgetItem(self._build_plan_target_text(action_norm, item, payload))
            self.plan_table.setItem(row, 1, target_item)

            date_item = QTableWidgetItem(self._build_plan_date_text(action_norm, payload))
            self.plan_table.setItem(row, 2, date_item)

            changes_summary, changes_detail = self._build_plan_changes(action_norm, item, payload, custom_fields)
            changes_item = QTableWidgetItem(changes_summary)
            if changes_detail and changes_detail != changes_summary:
                changes_item.setToolTip(changes_detail)
            self.plan_table.setItem(row, 3, changes_item)

            status_text, status_detail = self._build_plan_status(item)
            status_item = QTableWidgetItem(status_text)
            if status_detail:
                status_item.setToolTip(status_detail)
            self.plan_table.setItem(row, 4, status_item)

            # Set row background color based on color_key field (same as overview grid)
            record_id = item.get("record_id")
            if record_id:
                record = self.records_cache.get(record_id)
                if record:
                    color_value = record.get(color_key, "")
                    row_color = cell_color(color_value if color_value else None)
                    qcolor = QColor(row_color)
                    for col in range(self.plan_table.columnCount()):
                        cell_item = self.plan_table.item(row, col)
                        if cell_item:
                            cell_item.setBackground(qcolor)

        self._refresh_plan_toolbar_state()

    def execute_plan(self):
        """Execute all staged plan items after user confirmation."""
        if not self._plan_store.count():
            msg = tr("operations.planNoItemsToExecute")
            self._set_plan_feedback(msg, level="warning")
            self._publish_system_notice(
                code="plan.execute.empty",
                text=msg,
                level="error",
                timeout=3000,
                data={"total_count": 0},
            )
            return

        # Validation happens at button click time, proceed directly to execution.
        # Backend validation will catch any edge cases for safety.
        yaml_path = os.path.abspath(str(self.yaml_path_getter()))
        summary_lines = []
        plan_items = self._plan_store.list_items()
        for item in plan_items:
            action = item.get("action", "?")
            label = item.get("label", "?")
            pos = item.get("position", "?")
            if str(action).lower() == "rollback":
                payload = item.get("payload") or {}
                summary_lines.extend(
                    self._build_rollback_confirmation_lines(
                        backup_path=payload.get("backup_path"),
                        yaml_path=yaml_path,
                        source_event=payload.get("source_event"),
                        include_action_prefix=True,
                    )
                )
                continue

            line = f"  {action}: {label} @ Box {item.get('box', '?')}:{self._position_to_display(pos)}"
            to_pos = item.get("to_position")
            to_box = item.get("to_box")
            if to_pos:
                if to_box:
                    line += f" \u2192 Box {to_box}:{self._position_to_display(to_pos)}"
                else:
                    line += f" \u2192 {self._position_to_display(to_pos)}"
            summary_lines.append(line)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(tr("operations.executePlanTitle"))
        msg.setText(tr("operations.executePlanConfirm", count=len(plan_items)))
        msg.setInformativeText("\n".join(summary_lines[:20]))
        if len(summary_lines) > 20:
            msg.setDetailedText("\n".join(summary_lines))
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        if msg.exec() != QMessageBox.Yes:
            return

        original_plan = list(plan_items)
        report = run_plan(yaml_path, plan_items, self.bridge, mode="execute")

        report_items = report.get("items") if isinstance(report.get("items"), list) else []
        results = []
        for r in report_items:
            status = "OK" if r.get("ok") else "FAIL"
            info = r.get("response") or {}
            if status == "FAIL":
                info = {
                    "message": r.get("message"),
                    "error_code": r.get("error_code"),
                }
            results.append((status, r.get("item"), info))

        remaining = report.get("remaining_items") if isinstance(report.get("remaining_items"), list) else []
        fail_count = sum(1 for r in results if r[0] == "FAIL")
        rollback_info = None

        if fail_count:
            rollback_info = self._attempt_atomic_rollback(yaml_path, results)
            self._plan_store.replace_all(original_plan)
        elif remaining:
            self._plan_store.replace_all(remaining)
        else:
            self._plan_store.clear()

        self._run_plan_preflight(trigger="post_execute")
        self._refresh_plan_table()
        self._update_execute_button_state()
        execution_stats = summarize_plan_execution(report, rollback_info)
        self._show_plan_result(
            results,
            remaining,
            report=report,
            rollback_info=rollback_info,
        )

        executed_items = [r[1] for r in results if r[0] == "OK"]
        if execution_stats.get("rollback_ok"):
            executed_items = []
        self._last_executed_plan = list(executed_items)

        if report.get("ok") and any(r[0] == "OK" for r in results):
            self.operation_completed.emit(True)
        elif fail_count:
            self.operation_completed.emit(False)

        last_backup = report.get("backup_path")
        if last_backup and executed_items:
            self._last_operation_backup = last_backup
            self._enable_undo(timeout_sec=30)
        else:
            self._disable_undo(clear_last_executed=not bool(executed_items))

        summary_text = self._build_execution_summary_text(execution_stats)
        notice_level = "success"
        if execution_stats.get("fail_count", 0) > 0:
            notice_level = "warning" if execution_stats.get("rollback_ok") else "error"
        base_stats = report.get("stats") if isinstance(report.get("stats"), dict) else {}
        stats_payload = dict(base_stats) if isinstance(base_stats, dict) else {}
        stats_payload["applied"] = execution_stats.get("applied_count", 0)
        stats_payload["failed"] = execution_stats.get("fail_count", 0)
        stats_payload["rolled_back"] = bool(execution_stats.get("rollback_ok"))
        result_sample = []
        for status, plan_item, info in results:
            if not isinstance(plan_item, dict):
                continue
            line = f"{status}: {self._build_notice_plan_item_desc(plan_item)}"
            if status != "OK" and isinstance(info, dict):
                msg = info.get("message") or info.get("error_code")
                if msg:
                    line += f" | {str(msg)}"
            result_sample.append(line)
            if len(result_sample) >= 8:
                break
        self._publish_system_notice(
            code="plan.execute.result",
            text=summary_text,
            level=notice_level,
            timeout=5000,
            details=summary_text,
            data={
                "ok": bool(report.get("ok")),
                "stats": stats_payload,
                "report": report,
                "rollback": rollback_info,
                "sample": result_sample,
            },
        )

    def _attempt_atomic_rollback(self, yaml_path, results):
        """Best-effort rollback to the first backup of this execute run."""
        first_backup = None
        for status, _item, info in results:
            if status != "OK" or not isinstance(info, dict):
                continue
            backup_path = info.get("backup_path")
            if backup_path:
                first_backup = backup_path
                break

        if not first_backup:
            return {
                "attempted": False,
                "ok": False,
                "message": tr("operations.noRollbackBackup"),
            }

        rollback_fn = getattr(self.bridge, "rollback", None)
        if not callable(rollback_fn):
            return {
                "attempted": False,
                "ok": False,
                "message": tr("operations.bridgeNoRollback"),
                "backup_path": first_backup,
            }

        try:
            response = rollback_fn(yaml_path=yaml_path, backup_path=first_backup)
        except Exception as exc:
            return {
                "attempted": True,
                "ok": False,
                "message": tr("operations.rollbackException", error=exc),
                "backup_path": first_backup,
            }

        payload = response if isinstance(response, dict) else {}
        if payload.get("ok"):
            return {
                "attempted": True,
                "ok": True,
                "message": tr("operations.executionRolledBack"),
                "backup_path": first_backup,
            }

        return {
            "attempted": True,
            "ok": False,
            "message": payload.get("message", tr("operations.rollbackUnknown")),
            "error_code": payload.get("error_code"),
            "backup_path": first_backup,
        }

    def _emit_operation_event(self, event):
        """Emit a normalized operation event for AI panel/context consumers."""
        payload = coerce_system_notice(event) if isinstance(event, dict) else None
        if payload is None:
            payload = dict(event) if isinstance(event, dict) else {}
        payload["timestamp"] = payload.get("timestamp") or datetime.now().isoformat()
        self.operation_event.emit(payload)

    def _publish_system_notice(
        self,
        *,
        code,
        text,
        level="info",
        timeout=2000,
        details=None,
        data=None,
        source="operations_panel",
    ):
        """Single-path publisher for user-facing status + AI-visible system notice."""
        message = str(text or "")
        self.status_message.emit(message, int(timeout), str(level))
        notice = build_system_notice(
            code=str(code or "notice"),
            text=message,
            level=str(level or "info"),
            source=str(source or "operations_panel"),
            timeout_ms=int(timeout),
            details=str(details) if details else None,
            data=data if isinstance(data, dict) else None,
        )
        self._emit_operation_event(notice)
        return notice

    def emit_external_operation_event(self, event):
        """Public helper for non-plan modules to emit operation events."""
        if not isinstance(event, dict):
            return
        self._emit_operation_event(dict(event))

    def _build_execution_summary_text(self, execution_stats):
        """Build a user-facing summary for execution event payloads."""
        if execution_stats.get("fail_count", 0) <= 0:
            applied = execution_stats.get("applied_count", 0)
            total = execution_stats.get("total_count", 0)
            return tr("operations.planExecutionSuccessSummary", applied=applied, total=total)

        total = execution_stats.get("total_count", 0)
        fail = execution_stats.get("fail_count", 0)
        applied = execution_stats.get("applied_count", 0)
        if execution_stats.get("rollback_ok"):
            return tr("operations.planExecutionAtomicRollback", fail=fail, total=total)

        rollback_message = execution_stats.get("rollback_message", "")
        if execution_stats.get("rollback_attempted"):
            suffix = tr("operations.rollbackFailedSuffix", reason=rollback_message) if rollback_message else ""
        elif rollback_message:
            suffix = tr("operations.rollbackUnavailableSuffix", reason=rollback_message)
        else:
            suffix = ""
        return tr(
            "operations.planExecutionFailedSummary",
            fail=fail,
            total=total,
            applied=applied,
            suffix=suffix,
        )

    def _show_plan_result(self, results, remaining, report=None, rollback_info=None):
        execution_stats = summarize_plan_execution(report, rollback_info)
        ok_count = execution_stats.get("ok_count", sum(1 for r in results if r[0] == "OK"))
        fail_count = execution_stats.get("fail_count", sum(1 for r in results if r[0] == "FAIL"))
        applied_count = execution_stats.get("applied_count", ok_count)

        if fail_count:
            fail_item = [r for r in results if r[0] == "FAIL"][-1]
            error_msg = fail_item[2].get("message", "Unknown error")
            title_html = f"<b style='color: var(--status-error);'>{tr('operations.planExecutionStopped')}</b>"
            if execution_stats.get("rollback_ok"):
                title_html = f"<b style='color: var(--status-warning);'>{tr('operations.planExecutionRolledBack')}</b>"
            lines = [
                title_html,
                tr(
                    "operations.planExecutionStats",
                    attempted_ok=ok_count,
                    failed=fail_count,
                    applied=applied_count,
                ),
                tr("operations.planExecutionError", error=error_msg),
                f"<span style='color: var(--status-muted);'>{tr('operations.planExecutionRetry')}</span>",
            ]
            if isinstance(rollback_info, dict) and rollback_info:
                if execution_stats.get("rollback_ok"):
                    lines.append(
                        f"<span style='color: var(--status-success);'>{tr('operations.planExecutionRollbackApplied')}</span>"
                    )
                elif execution_stats.get("rollback_attempted"):
                    lines.append(
                        f"<span style='color: var(--status-error);'>{tr('operations.planExecutionRollbackFailed', reason=rollback_info.get('message', 'unknown error'))}</span>"
                    )
                elif execution_stats.get("rollback_message"):
                    lines.append(
                        f"<span style='color: var(--status-warning);'>{tr('operations.planExecutionRollbackUnavailable', reason=execution_stats.get('rollback_message'))}</span>"
                    )
            self._set_result_summary_html(lines)
            self.result_card.setProperty("state", "warning" if execution_stats.get("rollback_ok") else "error")
            self.result_card.style().unpolish(self.result_card)
            self.result_card.style().polish(self.result_card)
        else:
            lines = [
                f"<b style='color: var(--status-success);'>{tr('operations.planExecutionSuccess')}</b>",
                tr("operations.planExecutionSuccessSummary", applied=applied_count, total=applied_count),
            ]
            self._set_result_summary_html(lines)
            self.result_card.setProperty("state", "success")
            self.result_card.style().unpolish(self.result_card)
            self.result_card.style().polish(self.result_card)

        self.result_card.setVisible(True)
        self._sync_result_actions()

    def print_plan(self):
        """Print current staged plan (not yet executed)."""
        items_to_print = self._plan_store.list_items()
        if not items_to_print:
            self.status_message.emit(tr("operations.noCurrentPlanToPrint"), 3000, "error")
            return

        # Get grid state from overview panel
        grid_state = None
        if hasattr(self, '_overview_panel_ref') and self._overview_panel_ref:
            try:
                from app_gui.plan_model import extract_grid_state_for_print, apply_operation_markers_to_grid
                grid_state = extract_grid_state_for_print(self._overview_panel_ref)
                grid_state = apply_operation_markers_to_grid(grid_state, items_to_print)
            except Exception as e:
                print(f"Warning: Could not extract grid state: {e}")

        self._print_operation_sheet_with_grid(items_to_print, grid_state, opened_message=tr("operations.planPrintOpened"))

    def print_last_executed(self):
        """Print the last successfully applied execution result."""
        items_to_print = self._last_executed_plan
        if not items_to_print:
            self.status_message.emit(tr("operations.noLastExecutedToPrint"), 3000, "error")
            return

        # Get grid state from overview panel
        grid_state = None
        if hasattr(self, '_overview_panel_ref') and self._overview_panel_ref:
            try:
                from app_gui.plan_model import extract_grid_state_for_print, apply_operation_markers_to_grid
                grid_state = extract_grid_state_for_print(self._overview_panel_ref)
                grid_state = apply_operation_markers_to_grid(grid_state, items_to_print)
            except Exception as e:
                print(f"Warning: Could not extract grid state: {e}")

        self._print_operation_sheet_with_grid(items_to_print, grid_state, opened_message=tr("operations.guideOpened"))

    def print_last_plan(self):
        """Backward-compatible alias for printing last executed result."""
        self.print_last_executed()

    def _print_operation_sheet_with_grid(self, items, grid_state, opened_message=None):
        """Print operation sheet with grid visualization."""
        if opened_message is None:
            opened_message = tr("operations.operationSheetOpened")

        from app_gui.plan_model import render_operation_sheet_with_grid
        html = render_operation_sheet_with_grid(items, grid_state)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))
        self.status_message.emit(opened_message, 2000, "info")

    def _print_operation_sheet(self, items, opened_message=None):
        if opened_message is None:
            opened_message = tr("operations.operationSheetOpened")
        html = render_operation_sheet(items)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))
        self.status_message.emit(opened_message, 2000, "info")

    def clear_plan(self):
        cleared_items = self._plan_store.clear()
        self._set_plan_feedback("")
        self._plan_validation_by_key = {}
        self._plan_preflight_report = None
        self._refresh_plan_table()
        self._update_execute_button_state()
        action_counts, sample = self._collect_notice_action_counts_and_sample(cleared_items)

        self._publish_system_notice(
            code="plan.cleared",
            text=tr("operations.planCleared"),
            level="info",
            timeout=2000,
            details="\n".join(sample[:8]) if sample else None,
            data={
                "cleared_count": len(cleared_items),
                "action_counts": action_counts,
                "sample": sample,
            },
        )

    def reset_for_dataset_switch(self):
        """Clear transient plan/undo/audit state when switching datasets."""
        self._plan_store.clear()
        self._set_plan_feedback("")
        self._plan_validation_by_key = {}
        self._plan_preflight_report = None
        self._disable_undo(clear_last_executed=True)

        self._refresh_plan_table()
        self._update_execute_button_state()

    def on_export_inventory_csv(self):
        yaml_path = self.yaml_path_getter()
        default_name = f"inventory_full_{date.today().isoformat()}.csv"
        suggested_path = default_name
        if yaml_path:
            yaml_abs = os.path.abspath(os.fspath(yaml_path))
            base_name = os.path.splitext(os.path.basename(yaml_abs))[0] or "inventory"
            suggested_path = os.path.join(
                os.path.dirname(yaml_abs),
                f"{base_name}_full_{date.today().isoformat()}.csv",
            )

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("operations.exportDialogTitle"),
            suggested_path,
            tr("operations.exportCsvFilter"),
        )
        if not path:
            return

        if not str(path).lower().endswith(".csv"):
            path = f"{path}.csv"

        response = self.bridge.export_inventory_csv(
            yaml_path,
            output_path=path,
        )
        payload = response if isinstance(response, dict) else {}
        if payload.get("ok"):
            result = payload.get("result", {})
            exported_path = result.get("path") if isinstance(result, dict) else None
            count = result.get("count") if isinstance(result, dict) else None
            if isinstance(count, int):
                self._publish_system_notice(
                    code="inventory.export.success",
                    text=tr("operations.exportedToWithCount", count=count, path=exported_path or path),
                    level="success",
                    timeout=3000,
                    data={"path": exported_path or path, "count": count},
                )
            else:
                self._publish_system_notice(
                    code="inventory.export.success",
                    text=tr("operations.exportedTo", path=exported_path or path),
                    level="success",
                    timeout=3000,
                    data={"path": exported_path or path},
                )
            return

        self._publish_system_notice(
            code="inventory.export.failed",
            text=tr(
                "operations.exportFailed",
                error=payload.get("message", tr("operations.unknownError")),
            ),
            level="error",
            timeout=5000,
            data={
                "error_code": payload.get("error_code"),
                "message": payload.get("message"),
                "path": path,
            },
        )

    # --- UNDO ---

    def _enable_undo(self, timeout_sec=30):
        """Enable undo countdown while keeping last-result print available."""
        if not self._last_operation_backup:
            self._sync_result_actions()
            return

        # Start countdown timer
        self._undo_remaining = timeout_sec
        if self._undo_timer is not None:
            self._undo_timer.stop()

        self._undo_timer = QTimer(self)
        self._undo_timer.timeout.connect(self._undo_tick)
        self._undo_timer.start(1000)
        self._sync_result_actions()

    def _update_undo_button_text(self):
        """Update undo button text with countdown."""
        self.undo_btn.setText(
            tr(
                "operations.undoLastWithCountdown",
                operation=tr("operations.undoLast"),
                seconds=self._undo_remaining,
            )
        )

    def _undo_tick(self):
        self._undo_remaining -= 1
        if self._undo_remaining <= 0:
            self._disable_undo()
        else:
            self._update_undo_button_text()

    def _disable_undo(self, *, clear_last_executed=False):
        """Disable undo countdown and optionally clear last executed context."""
        if self._undo_timer is not None:
            self._undo_timer.stop()
            self._undo_timer = None

        self._undo_remaining = 0
        self._last_operation_backup = None
        if clear_last_executed:
            self._last_executed_plan = []
        self._sync_result_actions()

    def on_undo_last(self):
        if not self._last_operation_backup:
            self._publish_system_notice(
                code="undo.unavailable",
                text=tr("operations.noOperationToUndo"),
                level="error",
                timeout=3000,
            )
            return

        yaml_path = os.path.abspath(str(self.yaml_path_getter()))
        confirm_lines = self._build_rollback_confirmation_lines(
            backup_path=self._last_operation_backup,
            yaml_path=yaml_path,
            include_action_prefix=False,
        )
        if not self._confirm_execute(
            tr("operations.undo"),
            "\n".join(confirm_lines),
        ):
            return

        executed_plan_backup = list(self._last_executed_plan)
        response = self.bridge.rollback(
            self.yaml_path_getter(),
            backup_path=self._last_operation_backup,
            execution_mode="execute",
        )
        self._disable_undo(clear_last_executed=True)

        restored_data = None
        if response.get("ok") and executed_plan_backup:
            action_counts, sample = self._collect_notice_action_counts_and_sample(executed_plan_backup)
            restored_data = {
                "restored_count": len(executed_plan_backup),
                "action_counts": action_counts,
                "sample": sample,
            }

        self._handle_response(
            response,
            tr("operations.undo"),
            notice_code="plan.restored" if restored_data else "undo.result",
            notice_data=restored_data,
        )
        if response.get("ok") and executed_plan_backup:
            self._plan_store.replace_all(executed_plan_backup)
            self._refresh_plan_table()
