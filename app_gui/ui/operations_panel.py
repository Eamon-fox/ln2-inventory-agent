import os
import sys

from PySide6.QtCore import Qt, Signal, Slot, QDate, QSortFilterProxyModel, QEvent
from PySide6.QtGui import QDesktopServices, QValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCompleter,
    QStackedWidget, QFileDialog, QMenu,
    QDateEdit, QSpinBox, QDoubleSpinBox, QTextBrowser
)
from app_gui.ui.theme import (
    get_theme_color,
    resolve_theme_token,
)
from app_gui.ui.icons import get_icon, Icons
from app_gui.ui.watermark_overlay import SvgWatermarkLabel
from app_gui.application import PlanRunUseCase
from app_gui.gui_config import load_gui_config
from app_gui.i18n import tr
from lib.position_fmt import pos_to_display
from lib.schema_aliases import expand_record_structural_aliases, get_input_stored_at
from lib import tool_api_parsers as _tool_parsers
from lib.plan_store import PlanStore
from app_gui.ui import operations_panel_execution as _ops_exec
from app_gui.ui import operations_panel_actions as _ops_actions
from app_gui.ui import operations_panel_plan_table as _ops_plan_table
from app_gui.ui import operations_panel_plan_store as _ops_plan_store
from app_gui.ui import operations_panel_forms as _ops_forms
from app_gui.ui import operations_panel_context as _ops_context
from app_gui.ui import operations_panel_staging as _ops_staging
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
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

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
        self._migration_mode_enabled = False

        self.records_cache = {}
        self._current_inventory = []
        self.current_operation_mode = "takeout"
        self.t_prefill_source = None
        self._default_date_anchor = QDate.currentDate()
        self._last_operation_backup = None
        self._last_executed_plan = []
        self._last_executed_print_snapshot = None
        self._plan_preflight_report = None
        self._plan_validation_by_key = {}
        self._undo_timer = None
        self._undo_remaining = 0
        self._current_custom_fields = []
        self._current_meta = {}
        self._current_layout = {}
        self._staged_add_lock_signature = None
        self._staged_add_lock_source = None
        self._plan_run_use_case = PlanRunUseCase()

        self.setup_ui()
        # Initialize dynamic fields with a permissive startup profile so the
        # add-form widgets are immediately available even before dataset meta
        # is loaded from disk.
        self.apply_meta_update({"custom_fields": []}, inventory=[])
        self._apply_migration_mode_ui_state()

    @property
    def plan_items(self):
        """Read-only snapshot for backward compatibility (tests, external reads)."""
        return self._plan_store.list_items()

    def _iter_staged_add_items(self):
        for item in self._plan_store.list_items():
            if not isinstance(item, dict):
                continue
            if str(item.get("action") or "").strip().lower() != "add":
                continue
            yield item

    def _normalize_add_item_positions(self, item):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        raw_positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        if not raw_positions:
            raw_positions = [item.get("position")]

        normalized = []
        for raw_position in raw_positions:
            try:
                position = self._normalize_position_value(
                    raw_position,
                    field_name="position",
                    allow_empty=True,
                )
            except ValueError:
                continue
            if position is None or position in normalized:
                continue
            normalized.append(position)
        return tuple(sorted(normalized))

    def _staged_add_item_signature(self, item):
        if not isinstance(item, dict):
            return None
        try:
            box = self._normalize_box_value(
                item.get("box"),
                field_name="box",
                allow_empty=True,
            )
        except ValueError:
            return None
        positions = self._normalize_add_item_positions(item)
        if box is None or not positions:
            return None
        return int(box), positions

    def _find_staged_add_item_by_signature(self, signature):
        if not signature:
            return None
        for item in self._iter_staged_add_items():
            if self._staged_add_item_signature(item) == signature:
                return item
        return None

    def _resolve_overview_active_add_position(self, source_info):
        payload = dict(source_info or {})
        active_position = payload.get("active_position")
        overview = getattr(self, "_overview_panel_ref", None)
        if active_position in (None, "") and overview is not None:
            active_key = getattr(overview, "overview_selected_key", None)
            if isinstance(active_key, (tuple, list)) and len(active_key) == 2:
                box = payload.get("box")
                if box in (None, "") or str(active_key[0]) == str(box):
                    active_position = active_key[1]
        try:
            return self._normalize_position_value(
                active_position,
                field_name="position",
                allow_empty=True,
            )
        except ValueError:
            return None

    def _resolve_staged_add_item_for_prefill(self, source_info):
        payload = dict(source_info or {})
        try:
            box = self._normalize_box_value(
                payload.get("box"),
                field_name="box",
                allow_empty=True,
            )
        except ValueError:
            return None
        if box is None:
            return None

        requested_positions = []
        for raw_position in list(payload.get("positions") or []):
            try:
                position = self._normalize_position_value(
                    raw_position,
                    field_name="position",
                    allow_empty=True,
                )
            except ValueError:
                continue
            if position is None or position in requested_positions:
                continue
            requested_positions.append(position)
        if not requested_positions:
            try:
                single_position = self._normalize_position_value(
                    payload.get("position"),
                    field_name="position",
                    allow_empty=True,
                )
            except ValueError:
                single_position = None
            if single_position is not None:
                requested_positions.append(single_position)

        exact_match = tuple(sorted(requested_positions)) if requested_positions else ()
        active_position = self._resolve_overview_active_add_position(payload)

        candidates = []
        for item in self._iter_staged_add_items():
            signature = self._staged_add_item_signature(item)
            if signature is None or signature[0] != int(box):
                continue
            positions = signature[1]
            if exact_match and positions == exact_match:
                return item
            if active_position is not None and active_position in positions:
                candidates.insert(0, item)
                continue
            if any(position in positions for position in requested_positions):
                candidates.append(item)

        if not candidates:
            return None
        return candidates[0]

    def _iter_add_form_widgets(self):
        for attr_name in ("a_box", "a_positions", "a_date", "a_apply_btn"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                yield widget
        for widget in dict(getattr(self, "_add_custom_widgets", {}) or {}).values():
            if widget is not None:
                yield widget

    def _set_add_form_locked(self, locked):
        for widget in self._iter_add_form_widgets():
            widget.setEnabled(not bool(locked))

    def _clear_staged_add_lock(self, *, only_source=None):
        if only_source is not None and self._staged_add_lock_source != only_source:
            return False
        had_lock = bool(self._staged_add_lock_signature)
        self._staged_add_lock_signature = None
        self._staged_add_lock_source = None
        self._set_add_form_locked(False)
        return had_lock

    def _reset_add_form_to_defaults(self):
        self._ensure_today_defaults()
        self.a_box.blockSignals(True)
        self.a_box.setValue(max(1, int(self.a_box.minimum())))
        self.a_box.blockSignals(False)
        self.a_positions.blockSignals(True)
        self.a_positions.clear()
        self.a_positions.blockSignals(False)
        self.a_date.blockSignals(True)
        self.a_date.setDate(QDate.currentDate())
        self.a_date.blockSignals(False)

        for field_def in list(getattr(self, "_current_custom_fields", []) or []):
            if not isinstance(field_def, dict):
                continue
            key = str(field_def.get("key") or "").strip()
            if not key:
                continue
            widget = self._add_custom_widgets.get(key)
            if widget is None:
                continue
            self._apply_add_form_widget_value(widget, field_def, field_def.get("default"))

    def _apply_add_form_widget_value(self, widget, field_def, value):
        if widget is None:
            return
        if isinstance(widget, QComboBox):
            text = "" if value is None else str(value)
            widget.blockSignals(True)
            if text:
                widget.setCurrentText(text)
            elif widget.findText("", Qt.MatchFixedString) >= 0:
                widget.setCurrentText("")
            elif widget.count() > 0:
                widget.setCurrentIndex(0)
            else:
                widget.setEditText("")
            widget.blockSignals(False)
            return
        if isinstance(widget, QDateEdit):
            text = str(value or "").strip()
            parsed = QDate.fromString(text, "yyyy-MM-dd") if text else QDate()
            widget.blockSignals(True)
            widget.setDate(parsed if parsed.isValid() else QDate.currentDate())
            widget.blockSignals(False)
            return
        if isinstance(widget, QSpinBox):
            widget.blockSignals(True)
            if value in (None, ""):
                widget.setValue(0)
            else:
                try:
                    widget.setValue(int(value))
                except (TypeError, ValueError):
                    widget.setValue(0)
            widget.blockSignals(False)
            return
        if isinstance(widget, QDoubleSpinBox):
            widget.blockSignals(True)
            if value in (None, ""):
                widget.setValue(0.0)
            else:
                try:
                    widget.setValue(float(value))
                except (TypeError, ValueError):
                    widget.setValue(0.0)
            widget.blockSignals(False)
            return
        _ops_forms._write_text_widget_value(widget, "" if value is None else value)

    def _apply_staged_add_item_to_form(self, item, *, source):
        signature = self._staged_add_item_signature(item)
        if signature is None:
            return False

        self._reset_add_form_to_defaults()

        box, positions = signature
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        stored_at = str(get_input_stored_at(payload, default="") or "").strip()

        self.a_box.blockSignals(True)
        self.a_box.setValue(int(box))
        self.a_box.blockSignals(False)

        self.a_positions.blockSignals(True)
        self.a_positions.setText(self._positions_to_display_text(list(positions)))
        self.a_positions.blockSignals(False)

        if stored_at:
            parsed_date = QDate.fromString(stored_at, "yyyy-MM-dd")
            if parsed_date.isValid():
                self.a_date.blockSignals(True)
                self.a_date.setDate(parsed_date)
                self.a_date.blockSignals(False)

        for field_def in list(getattr(self, "_current_custom_fields", []) or []):
            if not isinstance(field_def, dict):
                continue
            key = str(field_def.get("key") or "").strip()
            if not key:
                continue
            widget = self._add_custom_widgets.get(key)
            if widget is None:
                continue
            self._apply_add_form_widget_value(widget, field_def, fields.get(key))

        self.set_mode("add")
        self._staged_add_lock_signature = signature
        self._staged_add_lock_source = str(source or "overview")
        self._set_add_form_locked(True)
        return True

    def _sync_locked_staged_add_state(self):
        if not self._staged_add_lock_signature:
            return
        if self._find_staged_add_item_by_signature(self._staged_add_lock_signature) is not None:
            self._set_add_form_locked(True)
            return
        self._clear_staged_add_lock()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        layout.addLayout(self._build_mode_row())
        self._migration_mode_banner = QLabel(tr("operations.migrationModeBanner"))
        self._migration_mode_banner.setObjectName("operationsMigrationModeBanner")
        self._migration_mode_banner.setWordWrap(True)
        self._migration_mode_banner.setVisible(False)
        layout.addWidget(self._migration_mode_banner)
        layout.addWidget(self._build_operation_stack(), 2)
        layout.addLayout(self._build_feedback_row())
        # Plan Queue is always visible to reduce context switching.
        self.plan_panel = _ops_forms._build_plan_tab(self)
        layout.addWidget(self.plan_panel, 3)
        self._op_watermark_host = self.plan_panel
        self._op_watermark = self._create_operation_watermark(self.plan_panel)
        self.plan_panel.installEventFilter(self)
        self._update_operation_watermark()
        layout.addLayout(self._build_result_row())
        self._build_migration_lock_overlay()

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

        mode_row.addWidget(self.op_mode_combo)
        mode_row.addStretch()
        return mode_row

    def _build_operation_stack(self):
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.op_stack = QStackedWidget(host)
        self.op_mode_indexes = {
            "add": self.op_stack.addWidget(_ops_forms._build_add_tab(self)),
            "takeout": self.op_stack.addWidget(_ops_forms._build_takeout_tab(self)),
            "move": self.op_stack.addWidget(_ops_forms._build_move_tab(self)),
        }
        host_layout.addWidget(self.op_stack)
        return host

    def _create_operation_watermark(self, parent):
        watermark = SvgWatermarkLabel(
            parent=parent,
            opacity=0.09,
            target_ratio=0.48,
            min_width=180,
            max_width=360,
            margin_top=12,
            margin_right=12,
        )
        watermark.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return watermark

    def _resolve_operation_logo_path(self):
        candidates = []

        if getattr(sys, "frozen", False):
            meipass_root = str(getattr(sys, "_MEIPASS", "") or "")
            if meipass_root:
                candidates.append(os.path.join(meipass_root, "app_gui", "assets", "logo.svg"))
            exe_dir = os.path.dirname(str(getattr(sys, "executable", "") or ""))
            if exe_dir:
                candidates.append(os.path.join(exe_dir, "logo.svg"))
        else:
            app_gui_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            repo_root = os.path.dirname(app_gui_root)
            candidates.append(os.path.join(app_gui_root, "assets", "logo.svg"))
            candidates.append(os.path.join(repo_root, "logo.svg"))

        seen = set()
        for raw_path in candidates:
            norm_path = os.path.normpath(str(raw_path))
            key = os.path.normcase(norm_path)
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(norm_path):
                return norm_path
        return ""

    def _watermark_tint_color(self):
        theme_mode = "dark" if self._is_dark_theme() else "light"
        return resolve_theme_token("text-muted", mode=theme_mode, fallback="#94a3b8")

    def _update_operation_watermark_geometry(self):
        host = getattr(self, "_op_watermark_host", None)
        watermark = getattr(self, "_op_watermark", None)
        if host is None or watermark is None:
            return
        if host.width() <= 0 or host.height() <= 0:
            return
        watermark.update_geometry_for(host.rect())
        centered_x = max(0, int((host.width() - watermark.width()) / 2))
        centered_y = max(0, int((host.height() - watermark.height()) / 2))
        watermark.move(centered_x, centered_y)
        watermark.raise_()

    def _update_operation_watermark(self):
        watermark = getattr(self, "_op_watermark", None)
        if watermark is None:
            return

        logo_path = self._resolve_operation_logo_path()
        if not logo_path:
            watermark.hide()
            return

        watermark.set_tint_color(self._watermark_tint_color())
        if not watermark.set_svg_path(logo_path):
            watermark.hide()
            return

        self._update_operation_watermark_geometry()
        watermark.show()

    def _build_migration_lock_overlay(self):
        overlay = QWidget(self)
        overlay.setObjectName("operationsMigrationLockOverlay")
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(18, 12, 18, 12)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch()
        overlay_label = QLabel(tr("operations.migrationOverlayHint"), overlay)
        overlay_label.setObjectName("operationsMigrationLockOverlayLabel")
        overlay_label.setWordWrap(True)
        overlay_layout.addWidget(overlay_label, 0, Qt.AlignCenter)
        overlay_layout.addStretch()
        overlay.hide()
        self._migration_lock_overlay = overlay
        self._update_migration_lock_overlay_geometry()

    def _update_migration_lock_overlay_geometry(self):
        overlay = getattr(self, "_migration_lock_overlay", None)
        if overlay is None:
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        overlay.setGeometry(self.rect())
        if overlay.isVisible():
            overlay.raise_()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_op_watermark_host", None):
            if event.type() in (QEvent.Resize, QEvent.Show):
                self._update_operation_watermark_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_migration_lock_overlay_geometry()

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
        _ops_actions._disable_undo(self, clear_last_executed=True)

    def _sync_result_actions(self):
        """Sync visibility/enabled state of result-card action buttons."""
        has_last_executed = bool(self._last_executed_plan)
        has_undo = bool(self._last_operation_backup)

        self.print_last_result_btn.setVisible(has_last_executed)
        self.print_last_result_btn.setEnabled(has_last_executed)

        self.undo_btn.setVisible(has_undo)
        self.undo_btn.setEnabled(has_undo)
        if has_undo and self._undo_remaining > 0:
            _ops_actions._update_undo_button_text(self)
        else:
            self.undo_btn.setText(tr("operations.undoLast"))

        if self._is_write_locked_by_migration_mode():
            self.undo_btn.setEnabled(False)

        self.result_actions.setVisible(has_last_executed or has_undo)

    def _is_write_locked_by_migration_mode(self):
        return bool(getattr(self, "_migration_mode_enabled", False))

    def _warn_write_locked_by_migration_mode(self):
        self.status_message.emit(tr("operations.migrationWriteLocked"), 3000, "warning")

    def _guard_write_action_by_migration_mode(self):
        if not self._is_write_locked_by_migration_mode():
            return False
        self._warn_write_locked_by_migration_mode()
        return True

    def _apply_migration_mode_ui_state(self):
        locked = self._is_write_locked_by_migration_mode()
        banner = getattr(self, "_migration_mode_banner", None)
        if banner is not None:
            banner.setVisible(False)
        overlay = getattr(self, "_migration_lock_overlay", None)
        if overlay is not None:
            overlay.setVisible(locked)
            if locked:
                self._update_migration_lock_overlay_geometry()
                overlay.raise_()
        for attr in ("op_mode_combo", "op_stack"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(not locked)
        if locked:
            for attr in ("plan_exec_btn", "plan_clear_btn", "undo_btn"):
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            return

        _ops_plan_store._update_execute_button_state(self)
        _ops_plan_toolbar._refresh_plan_toolbar_state(self)
        self._sync_result_actions()

    def set_migration_mode_enabled(self, enabled):
        locked = bool(enabled)
        if self._migration_mode_enabled == locked:
            return
        self._migration_mode_enabled = locked
        self._apply_migration_mode_ui_state()

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
            expand_record_structural_aliases(normalized_record)
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
        self._current_inventory = list(normalized.values())
        _ops_context._refresh_takeout_record_context(self)
        _ops_context._refresh_move_record_context(self)

    def _resolved_inventory_records(self, inventory=None):
        if isinstance(inventory, list):
            return inventory
        current_inventory = getattr(self, "_current_inventory", None)
        if isinstance(current_inventory, list):
            return current_inventory
        records_cache = getattr(self, "records_cache", None)
        if isinstance(records_cache, dict):
            return list(records_cache.values())
        return []

    def _refresh_custom_fields(self):
        """Reload custom field definitions from YAML meta and rebuild dynamic forms."""
        self.apply_meta_update()

    def apply_meta_update(self, meta=None, inventory=None):
        """Apply latest YAML meta to forms immediately (no restart needed)."""
        from app_gui.error_localizer import localize_error
        from lib.custom_fields import get_effective_fields, unsupported_box_fields_issue

        if not isinstance(meta, dict):
            from lib.yaml_ops import load_yaml

            try:
                yaml_path = self.yaml_path_getter()
                data = load_yaml(yaml_path)
                meta = data.get("meta", {})
                inventory = data.get("inventory", [])
            except Exception:
                meta = {}
                inventory = []

        inventory = self._resolved_inventory_records(inventory)
        self._current_inventory = list(inventory)

        unsupported_issue = unsupported_box_fields_issue(meta)
        if unsupported_issue:
            self._current_meta = dict(meta) if isinstance(meta, dict) else {}
            self._current_layout = dict((meta or {}).get("box_layout") or {})
            self._current_custom_fields = []
            _ops_forms._rebuild_custom_add_fields(self, [])
            _ops_context._rebuild_ctx_user_fields(self, "takeout", [])
            _ops_context._rebuild_ctx_user_fields(self, "move", [])
            self._sync_cell_line_context_visibility([])
            self._plan_preflight_report = None
            self._plan_validation_by_key = {}
            self._clear_staged_add_lock()
            _ops_plan_table._refresh_plan_table(self)
            _ops_plan_store._update_execute_button_state(self)
            self.status_message.emit(
                localize_error(
                    unsupported_issue.get("error_code"),
                    unsupported_issue.get("message"),
                    details=unsupported_issue.get("details"),
                ),
                5000,
                "error",
            )
            return

        self._current_meta = meta
        self._current_layout = dict((meta or {}).get("box_layout") or {})
        custom_fields = get_effective_fields(meta, inventory=inventory)
        self._current_custom_fields = custom_fields
        _ops_forms._rebuild_custom_add_fields(self, custom_fields)
        _ops_context._rebuild_ctx_user_fields(self, "takeout", custom_fields)
        _ops_context._rebuild_ctx_user_fields(self, "move", custom_fields)
        self._sync_cell_line_context_visibility(custom_fields)
        # Refresh dropdown options for all option-bearing fields
        self._refresh_field_options(meta)

        # Re-evaluate staged plan immediately against latest rules.
        if self._plan_store.count() > 0:
            _ops_plan_store._run_plan_preflight(self, trigger="meta_updated")
        else:
            self._plan_preflight_report = None
            self._plan_validation_by_key = {}
            _ops_plan_table._refresh_plan_table(self)
            _ops_plan_store._update_execute_button_state(self)

        if self._staged_add_lock_signature:
            locked_item = self._find_staged_add_item_by_signature(self._staged_add_lock_signature)
            if locked_item is not None:
                self._apply_staged_add_item_to_form(
                    locked_item,
                    source=self._staged_add_lock_source or "overview",
                )
            else:
                self._clear_staged_add_lock()

    def _sync_cell_line_context_visibility(self, custom_fields):
        has_cell_line = any(
            isinstance(field, dict) and str(field.get("key") or "") == "cell_line"
            for field in (custom_fields or [])
        )
        for attr_name in (
            "_t_ctx_cell_line_label",
            "_t_ctx_cell_line_container",
            "_m_ctx_cell_line_label",
            "_m_ctx_cell_line_container",
        ):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            widget.setVisible(has_cell_line)

    def _refresh_field_options(self, meta):
        """Populate dropdown options for all option-bearing fields in the add form."""
        from lib.custom_fields import get_effective_fields

        inventory = self._resolved_inventory_records()
        for field_def in get_effective_fields(meta, inventory=inventory):
            fkey = field_def["key"]
            foptions = field_def.get("options")
            if not foptions:
                continue
            frequired = field_def.get("required", False)

            combo = self._add_custom_widgets.get(fkey)
            if not isinstance(combo, QComboBox):
                continue

            options = []
            seen = set()
            for raw in foptions:
                text = str(raw or "").strip()
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                options.append(text)

            hint_lines = self._cell_line_hint_lines() if fkey == "cell_line" else []
            prev = combo.currentText()

            combo.blockSignals(True)

            display_options = []
            if not frequired:
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

            if target_index < 0 and options:
                if frequired:
                    target_index = 0
                else:
                    target_index = 1 if combo.count() > 1 else 0
            elif target_index < 0 and combo.count() > 0:
                target_index = 0

            if target_index >= 0:
                combo.setCurrentIndex(target_index)

            combo.blockSignals(False)
            combo_line = combo.lineEdit()
            if combo_line is not None:
                self._configure_choice_line_edit(
                    combo_line,
                    options=options,
                    allow_empty=(not frequired),
                    hint_lines=hint_lines,
                    show_all_popup=True,
                )

        self._refresh_context_field_constraints()

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
        return self._field_choice_config("cell_line")

    def _field_choice_config(self, field_key):
        """Return (options, allow_empty) for any option-bearing field."""
        from lib.custom_fields import get_field_options, is_field_required

        meta = self._current_meta if isinstance(self._current_meta, dict) else {}
        inventory = self._resolved_inventory_records()
        required = is_field_required(meta, field_key, inventory=inventory)
        options = []
        seen = set()
        for raw in get_field_options(meta, field_key, inventory=inventory):
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

    def _refresh_context_field_constraints(self):
        """Refresh choice constraints on editable context fields (takeout/move tabs)."""
        from lib.custom_fields import get_effective_fields

        meta = self._current_meta if isinstance(self._current_meta, dict) else {}
        inventory = self._resolved_inventory_records()
        for field_def in get_effective_fields(meta, inventory=inventory):
            fkey = field_def["key"]
            foptions = field_def.get("options")
            if not foptions:
                continue
            frequired = field_def.get("required", False)

            options, allow_empty = [], True
            seen = set()
            for raw in foptions:
                text = str(raw or "").strip()
                if not text:
                    continue
                k = text.casefold()
                if k in seen:
                    continue
                seen.add(k)
                options.append(text)
            allow_empty = not frequired

            # Apply to takeout and move context widgets
            for prefix in ("t_ctx_", "m_ctx_"):
                field_widget = getattr(self, f"{prefix}{fkey}", None)
                if isinstance(field_widget, QLineEdit):
                    self._configure_choice_line_edit(
                        field_widget,
                        options=options,
                        allow_empty=allow_empty,
                        show_all_popup=True,
                    )

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
            elif isinstance(widget, QComboBox):
                raw = widget.currentText().strip()
            else:
                raw = _ops_forms._read_text_widget_value(widget).strip()
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
                _tool_parsers.coerce_position_value(
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
        _ops_context._refresh_takeout_record_context(self)
        self.set_mode("takeout")

    def set_prefill(self, source_info):
        self.set_prefill_background(source_info)

    def set_prefill_background(self, source_info):
        self._apply_takeout_prefill(source_info)

    def _apply_add_prefill(self, source_info):
        payload = dict(source_info or {})
        if "box" in payload:
            self.a_box.setValue(int(payload["box"]))
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        normalized_positions = []
        for raw_position in positions:
            try:
                normalized_positions.append(
                    self._normalize_position_value(
                        raw_position,
                        field_name="position",
                        allow_empty=False,
                    )
                )
            except ValueError:
                continue
        normalized_positions = sorted(set(normalized_positions))
        if normalized_positions:
            self.a_positions.setText(self._positions_to_display_text(normalized_positions))
        elif "position" in payload:
            self.a_positions.setText(self._position_to_display(payload["position"]))
        self.set_mode("add")

    def set_add_prefill(self, source_info):
        """Pre-fill the Add Entry form with box and position from overview."""
        self.set_add_prefill_background(source_info)

    def set_add_prefill_background(self, source_info):
        """Pre-fill the Add Entry form and switch to Add mode."""
        staged_item = self._resolve_staged_add_item_for_prefill(source_info)
        if staged_item is not None:
            self._apply_staged_add_item_to_form(staged_item, source="overview")
            return
        self._clear_staged_add_lock()
        self._apply_add_prefill(source_info)

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

    def _emit_exception_status(self, exc, timeout, level="error"):
        self.status_message.emit(str(exc), int(timeout), str(level))

    def on_add_entry(self):
        return _ops_staging.on_add_entry(self)

    def on_record_takeout(self):
        return _ops_staging.on_record_takeout(self)

    def on_record_move(self):
        return _ops_staging.on_record_move(self)

    def on_batch_move(self):
        return _ops_staging.on_batch_move(self)

    def on_batch_takeout(self):
        return _ops_staging.on_batch_takeout(self)

    # --- PLAN OPERATIONS ---

    @Slot()
    def _on_store_changed(self):
        """Slot invoked (via QueuedConnection) when PlanStore mutates from any thread."""
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)

    def _sync_plan_table_add_prefill_lock(self):
        rows = _ops_plan_toolbar._get_selected_plan_rows(self)
        if len(rows) != 1:
            self._clear_staged_add_lock(only_source="plan")
            return

        items = self._plan_store.list_items()
        row = rows[0]
        if row < 0 or row >= len(items):
            self._clear_staged_add_lock(only_source="plan")
            return

        item = items[row]
        if str(item.get("action") or "").strip().lower() != "add":
            self._clear_staged_add_lock(only_source="plan")
            return

        self._apply_staged_add_item_to_form(item, source="plan")

    def _on_plan_table_selection_changed(self, *_args):
        _ops_plan_toolbar._refresh_plan_toolbar_state(self)
        self._sync_plan_table_add_prefill_lock()

    # Stable public API: these wrappers keep the call surface fixed while the
    # implementation lives in extracted helper modules.
    @Slot()
    def refresh_plan_store_view(self):
        self._on_store_changed()

    def add_plan_items(self, items):
        return _ops_plan_store.add_plan_items(self, items)

    def execute_plan(self):
        return _ops_exec.execute_plan(self)

    def clear_plan(self):
        return _ops_actions.clear_plan(self)

    def reset_for_dataset_switch(self):
        return _ops_actions.reset_for_dataset_switch(self)

    def on_export_inventory_csv(self, checked=False, *, parent=None, yaml_path_override=None):
        return _ops_actions.on_export_inventory_csv(
            self,
            checked=checked,
            parent=parent,
            yaml_path_override=yaml_path_override,
        )

    def emit_external_operation_event(self, event):
        return _ops_exec.emit_external_operation_event(self, event)

    def print_plan(self):
        return _ops_actions.print_plan(self)

    def print_last_executed(self):
        return _ops_actions.print_last_executed(self)

    def on_undo_last(self):
        return _ops_actions.on_undo_last(self)

    def remove_selected_plan_items(self):
        return _ops_plan_toolbar.remove_selected_plan_items(self)

    def on_plan_table_context_menu(self, pos):
        return _ops_plan_toolbar.on_plan_table_context_menu(self, pos)

