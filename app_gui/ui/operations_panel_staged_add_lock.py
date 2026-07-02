"""Staged add-draft form-lock collaborator for OperationsPanel.

This module owns the "staged add" editing responsibility that used to live
inline in :class:`OperationsPanel`:

- resolving which staged ``add`` plan item matches an overview/plan-table
  selection,
- mirroring that item back into the add form,
- locking/unlocking the add-form widgets while a staged item is being edited,
- keeping the lock in sync as the plan store or dataset meta changes.

The controller holds a back-reference to the panel and reads/writes panel
widget state through it. The panel keeps thin delegating methods so existing
call sites (including ``getattr(self, ...)`` lookups from
``operations_panel_plan_toolbar``) stay stable.
"""

from PySide6.QtCore import Qt, QDate, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox

from lib.schema_aliases import get_input_stored_at


class StagedAddLockController:
    """Coordinate staged add-item form prefill and input locking."""

    def __init__(self, panel):
        self._panel = panel
        self._signature = None
        self._source = None

    @property
    def signature(self):
        return self._signature

    @property
    def source(self):
        return self._source

    # --- staged add item lookup -------------------------------------------

    def _iter_staged_add_items(self):
        for item in self._panel._plan_store.list_items():
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
                position = self._panel._normalize_position_value(
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
            box = self._panel._normalize_box_value(
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
        overview = getattr(self._panel, "_overview_panel_ref", None)
        if active_position in (None, "") and overview is not None:
            active_key = getattr(overview, "overview_selected_key", None)
            if isinstance(active_key, (tuple, list)) and len(active_key) == 2:
                box = payload.get("box")
                if box in (None, "") or str(active_key[0]) == str(box):
                    active_position = active_key[1]
        try:
            return self._panel._normalize_position_value(
                active_position,
                field_name="position",
                allow_empty=True,
            )
        except ValueError:
            return None

    def resolve_item_for_prefill(self, source_info):
        payload = dict(source_info or {})
        try:
            box = self._panel._normalize_box_value(
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
                position = self._panel._normalize_position_value(
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
                single_position = self._panel._normalize_position_value(
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

    # --- add form widget locking ------------------------------------------

    def _iter_add_form_widgets(self):
        panel = self._panel
        for attr_name in ("a_box", "a_positions", "a_date", "a_apply_btn"):
            widget = getattr(panel, attr_name, None)
            if widget is not None:
                yield widget
        for widget in dict(getattr(panel, "_add_custom_widgets", {}) or {}).values():
            if widget is not None:
                yield widget

    def _set_add_form_locked(self, locked):
        for widget in self._iter_add_form_widgets():
            widget.setEnabled(not bool(locked))

    def clear(self, *, only_source=None):
        if only_source is not None and self._source != only_source:
            return False
        had_lock = bool(self._signature)
        self._signature = None
        self._source = None
        self._set_add_form_locked(False)
        return had_lock

    def _reset_add_form_to_defaults(self):
        panel = self._panel
        panel._ensure_today_defaults()
        with QSignalBlocker(panel.a_box):
            panel.a_box.setValue(max(1, int(panel.a_box.minimum())))
        with QSignalBlocker(panel.a_positions):
            panel.a_positions.clear()
        with QSignalBlocker(panel.a_date):
            panel.a_date.setDate(QDate.currentDate())

        for field_def in list(getattr(panel, "_current_custom_fields", []) or []):
            if not isinstance(field_def, dict):
                continue
            key = str(field_def.get("key") or "").strip()
            if not key:
                continue
            widget = panel._add_custom_widgets.get(key)
            if widget is None:
                continue
            self._apply_add_form_widget_value(widget, field_def, field_def.get("default"))

    def _apply_add_form_widget_value(self, widget, field_def, value):
        from app_gui.ui import operations_panel_forms as _ops_forms

        if widget is None:
            return
        if isinstance(widget, QComboBox):
            text = "" if value is None else str(value)
            with QSignalBlocker(widget):
                if text:
                    widget.setCurrentText(text)
                elif widget.findText("", Qt.MatchFixedString) >= 0:
                    widget.setCurrentText("")
                elif widget.count() > 0:
                    widget.setCurrentIndex(0)
                else:
                    widget.setEditText("")
            return
        if isinstance(widget, QDateEdit):
            text = str(value or "").strip()
            parsed = QDate.fromString(text, "yyyy-MM-dd") if text else QDate()
            with QSignalBlocker(widget):
                widget.setDate(parsed if parsed.isValid() else QDate.currentDate())
            return
        if isinstance(widget, QSpinBox):
            with QSignalBlocker(widget):
                if value in (None, ""):
                    widget.setValue(0)
                else:
                    try:
                        widget.setValue(int(value))
                    except (TypeError, ValueError):
                        widget.setValue(0)
            return
        if isinstance(widget, QDoubleSpinBox):
            with QSignalBlocker(widget):
                if value in (None, ""):
                    widget.setValue(0.0)
                else:
                    try:
                        widget.setValue(float(value))
                    except (TypeError, ValueError):
                        widget.setValue(0.0)
            return
        _ops_forms._write_text_widget_value(widget, "" if value is None else value)

    def apply_item_to_form(self, item, *, source):
        panel = self._panel
        signature = self._staged_add_item_signature(item)
        if signature is None:
            return False

        self._reset_add_form_to_defaults()

        box, positions = signature
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        stored_at = str(get_input_stored_at(payload, default="") or "").strip()

        with QSignalBlocker(panel.a_box):
            panel.a_box.setValue(int(box))

        with QSignalBlocker(panel.a_positions):
            panel.a_positions.setText(panel._positions_to_display_text(list(positions)))

        if stored_at:
            parsed_date = QDate.fromString(stored_at, "yyyy-MM-dd")
            if parsed_date.isValid():
                with QSignalBlocker(panel.a_date):
                    panel.a_date.setDate(parsed_date)

        for field_def in list(getattr(panel, "_current_custom_fields", []) or []):
            if not isinstance(field_def, dict):
                continue
            key = str(field_def.get("key") or "").strip()
            if not key:
                continue
            widget = panel._add_custom_widgets.get(key)
            if widget is None:
                continue
            self._apply_add_form_widget_value(widget, field_def, fields.get(key))

        panel.set_mode("add")
        self._signature = signature
        self._source = str(source or "overview")
        self._set_add_form_locked(True)
        return True

    def sync_locked_state(self):
        if not self._signature:
            return
        if self._find_staged_add_item_by_signature(self._signature) is not None:
            self._set_add_form_locked(True)
            return
        self.clear()

    def reapply_after_meta_update(self):
        """Re-mirror the locked staged add item after a dataset meta change."""
        if not self._signature:
            return
        locked_item = self._find_staged_add_item_by_signature(self._signature)
        if locked_item is not None:
            self.apply_item_to_form(locked_item, source=self._source or "overview")
        else:
            self.clear()
