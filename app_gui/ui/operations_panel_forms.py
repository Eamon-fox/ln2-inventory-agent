"""Form-building and inline editing helpers for OperationsPanel."""

from contextlib import suppress

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon
from app_gui.ui.theme import resolve_theme_token

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
            lock_btn.setText("\U0001F513")
            confirm_btn.setVisible(True)
            field.setFocus()
            field.selectAll()
        else:
            # Re-lock without saving
            field.setReadOnly(True)
            lock_btn.setText("\U0001F512")
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
    self.plan_table.setContextMenuPolicy(Qt.CustomContextMenu)
    self.plan_table.customContextMenuRequested.connect(self.on_plan_table_context_menu)
    layout.addWidget(self.plan_table, 1)

    toolbar = QHBoxLayout()
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
    self.plan_print_btn.setEnabled(False)
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
