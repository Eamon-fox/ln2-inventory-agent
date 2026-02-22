from PySide6.QtCore import Qt, Signal, Slot, QDate, QSize, QSortFilterProxyModel
from PySide6.QtGui import QDesktopServices, QValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCompleter,
    QStackedWidget, QFileDialog, QMenu,
    QDateEdit, QSpinBox, QDoubleSpinBox, QTextBrowser
)
from app_gui.ui.theme import (
    get_theme_color,
)
from app_gui.ui.icons import get_icon, Icons
from app_gui.gui_config import load_gui_config
from app_gui.i18n import tr
from lib.position_fmt import pos_to_display
from lib import tool_api_parsers as _tool_parsers
from lib.plan_store import PlanStore
from app_gui.ui import operations_panel_execution as _ops_exec
from app_gui.ui import operations_panel_actions as _ops_actions
from app_gui.ui import operations_panel_plan_table as _ops_plan_table
from app_gui.ui import operations_panel_results as _ops_results
from app_gui.ui import operations_panel_plan_store as _ops_plan_store
from app_gui.ui import operations_panel_forms as _ops_forms
from app_gui.ui import operations_panel_context as _ops_context
from app_gui.ui import operations_panel_staging as _ops_staging
from app_gui.ui import operations_panel_confirm as _ops_confirm
from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

# Keep these Qt symbols imported here as stable monkeypatch targets used by
# operations_panel_actions and related tests.
_MONKEYPATCH_EXPORTS = (QDesktopServices, QFileDialog, QMenu)

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
        # Keep layout current before normalizing incoming record positions.
        self._refresh_custom_fields()

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
                rid_int = int(rid)
            except (TypeError, ValueError):
                continue

            normalized_record = dict(record)
            try:
                normalized_record["box"] = self._normalize_box_value(
                    normalized_record.get("box"),
                    field_name="box",
                    allow_empty=True,
                )
            except ValueError:
                normalized_record["box"] = None

            try:
                normalized_record["position"] = self._normalize_position_value(
                    normalized_record.get("position"),
                    field_name="position",
                    allow_empty=True,
                )
            except ValueError:
                normalized_record["position"] = None

            normalized[rid_int] = normalized_record

        self.records_cache = normalized
        self._refresh_takeout_record_context()
        self._refresh_move_record_context()

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

    _takeout_record_id = _ops_context._takeout_record_id
    _move_record_id = _ops_context._move_record_id
    _rebuild_ctx_user_fields = _ops_context._rebuild_ctx_user_fields

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

    def _normalize_box_value(self, value, *, field_name="box", allow_empty=False):
        if value in (None, ""):
            if allow_empty:
                return None
            raise ValueError(f"{field_name} is required")
        if isinstance(value, bool):
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}")
        if isinstance(value, int):
            return int(value)
        try:
            return int(_tool_parsers.display_to_box(value, self._current_layout))
        except Exception as exc:
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}") from exc

    def _normalize_position_value(self, value, *, field_name="position", allow_empty=False):
        if value in (None, ""):
            if allow_empty:
                return None
            raise ValueError(f"{field_name} is required")
        if isinstance(value, bool):
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}")
        if isinstance(value, int):
            if value > 0:
                return int(value)
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}")
        if isinstance(value, float) and value.is_integer():
            if value > 0:
                return int(value)
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}")
        try:
            return int(
                _tool_parsers._coerce_position_value(
                    value,
                    layout=self._current_layout,
                    field_name=field_name,
                )
            )
        except Exception as exc:
            if allow_empty:
                return None
            raise ValueError(f"Invalid {field_name}: {value}") from exc

    def _parse_position_text(self, raw_text, *, allow_empty=False):
        text = str(raw_text or "").strip()
        if not text:
            if allow_empty:
                return None
            raise ValueError("Position is required")
        try:
            return self._normalize_position_value(
                text,
                field_name="position",
                allow_empty=False,
            )
        except ValueError as exc:
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

    _setup_table = _ops_forms._setup_table
    _make_readonly_field = _ops_forms._make_readonly_field
    _make_readonly_history_label = _ops_forms._make_readonly_history_label
    _make_editable_field = _ops_forms._make_editable_field
    _build_add_tab = _ops_forms._build_add_tab
    _rebuild_custom_add_fields = _ops_forms._rebuild_custom_add_fields
    _build_takeout_tab = _ops_forms._build_takeout_tab
    _build_move_tab = _ops_forms._build_move_tab
    _init_hidden_batch_takeout_controls = _ops_forms._init_hidden_batch_takeout_controls
    _init_hidden_batch_move_controls = _ops_forms._init_hidden_batch_move_controls
    _build_plan_tab = _ops_forms._build_plan_tab
    _on_toggle_move_batch_section = _ops_forms._on_toggle_move_batch_section
    _style_execute_button = _ops_forms._style_execute_button
    _style_stage_button = _ops_forms._style_stage_button
    _build_stage_action_button = _ops_forms._build_stage_action_button
    _set_plan_feedback = _ops_forms._set_plan_feedback

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

    _lookup_record = _ops_context._lookup_record
    _clear_context_label_groups = staticmethod(_ops_context._clear_context_label_groups)
    _populate_record_context_labels = _ops_context._populate_record_context_labels
    _set_last_event_summary_label = _ops_context._set_last_event_summary_label
    _refresh_takeout_record_context = _ops_context._refresh_takeout_record_context

    _confirm_warning_dialog = _ops_confirm._confirm_warning_dialog
    _confirm_execute = _ops_confirm._confirm_execute
    _format_size_bytes = staticmethod(_ops_confirm._format_size_bytes)
    _build_rollback_confirmation_lines = _ops_confirm._build_rollback_confirmation_lines

    def _emit_exception_status(self, exc, timeout, level="error"):
        self.status_message.emit(str(exc), int(timeout), str(level))

    on_add_entry = _ops_staging.on_add_entry
    _record_takeout_with_action = _ops_staging._record_takeout_with_action
    on_record_takeout = _ops_staging.on_record_takeout
    on_record_move = _ops_staging.on_record_move
    _read_required_table_texts = staticmethod(_ops_staging._read_required_table_texts)
    _collect_move_batch_from_table = _ops_staging._collect_move_batch_from_table
    on_batch_move = _ops_staging.on_batch_move
    _on_move_source_changed = _ops_context._on_move_source_changed
    _refresh_move_record_context = _ops_context._refresh_move_record_context
    _collect_batch_from_table = _ops_staging._collect_batch_from_table
    _resolve_batch_entries_with_fallback = _ops_staging._resolve_batch_entries_with_fallback
    _build_human_record_plan_item = _ops_staging._build_human_record_plan_item
    _build_move_batch_plan_items = _ops_staging._build_move_batch_plan_items
    _build_takeout_batch_plan_items = _ops_staging._build_takeout_batch_plan_items
    on_batch_takeout = _ops_staging.on_batch_takeout

    _handle_response = _ops_results._handle_response
    _result_header_html = staticmethod(_ops_results._result_header_html)
    _build_add_entry_result_lines = _ops_results._build_add_entry_result_lines
    _build_single_operation_result_lines = _ops_results._build_single_operation_result_lines
    _build_batch_operation_result_lines = staticmethod(_ops_results._build_batch_operation_result_lines)
    _build_restore_result_lines = staticmethod(_ops_results._build_restore_result_lines)
    _build_success_result_lines = _ops_results._build_success_result_lines
    _display_result_summary = _ops_results._display_result_summary

    # --- PLAN OPERATIONS ---

    _get_selected_plan_rows = _ops_plan_toolbar._get_selected_plan_rows
    _refresh_plan_toolbar_state = _ops_plan_toolbar._refresh_plan_toolbar_state

    @Slot()
    def _on_store_changed(self):
        """Slot invoked (via QueuedConnection) when PlanStore mutates from any thread."""
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)

    _refresh_after_plan_items_changed = _ops_plan_toolbar._refresh_after_plan_items_changed
    remove_selected_plan_items = _ops_plan_toolbar.remove_selected_plan_items
    on_plan_table_context_menu = _ops_plan_toolbar.on_plan_table_context_menu

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
    _build_plan_row_semantics = _ops_plan_table._build_plan_row_semantics
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
    _build_print_table_rows = _ops_actions._build_print_table_rows
    _print_operation_sheet_with_grid = _ops_actions._print_operation_sheet_with_grid
    clear_plan = _ops_actions.clear_plan
    reset_for_dataset_switch = _ops_actions.reset_for_dataset_switch
    on_export_inventory_csv = _ops_actions.on_export_inventory_csv
    _enable_undo = _ops_actions._enable_undo
    _update_undo_button_text = _ops_actions._update_undo_button_text
    _undo_tick = _ops_actions._undo_tick
    _disable_undo = _ops_actions._disable_undo
    on_undo_last = _ops_actions.on_undo_last







