"""Plan-table selection and toolbar helpers for OperationsPanel."""

from app_gui.i18n import tr


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

    has_items = bool(self._plan_store.count())
    locked = bool(getattr(self, "_is_write_locked_by_migration_mode", lambda: False)())
    self.plan_print_btn.setEnabled(has_items)
    self.plan_clear_btn.setEnabled(has_items and (not locked))


def _refresh_after_plan_items_changed(self):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store
    from app_gui.ui import operations_panel_plan_table as _ops_plan_table

    _ops_plan_table._refresh_plan_table(self)
    _ops_plan_store._update_execute_button_state(self)
    _refresh_plan_toolbar_state(self)
    apply_mode_fn = getattr(self, "_apply_migration_mode_ui_state", None)
    if callable(apply_mode_fn):
        apply_mode_fn()
    sync_locked_add_fn = getattr(self, "_sync_locked_staged_add_state", None)
    if callable(sync_locked_add_fn):
        sync_locked_add_fn()
    sync_selection_fn = getattr(self, "_sync_plan_table_add_prefill_lock", None)
    if callable(sync_selection_fn):
        sync_selection_fn()


def remove_selected_plan_items(self):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
        return
    rows = _get_selected_plan_rows(self)
    if not rows:
        self.status_message.emit(tr("operations.planNoSelection"), 2000, "warning")
        return

    items = self._plan_store.list_items()
    removed_items = [items[r] for r in rows if 0 <= r < len(items)]
    removed_count = self._plan_store.remove_by_indices(rows)
    if removed_count == 0:
        self.status_message.emit(tr("operations.planNoRemoved"), 2000, "warning")
        return

    _ops_plan_store._publish_plan_items_notice(
        self,
        code="plan.removed",
        text=tr("operations.planRemovedCount", count=removed_count),
        level="info",
        timeout=2000,
        items=removed_items,
        count_key="removed_count",
        count_value=removed_count,
        include_total_count=True,
    )


def on_plan_table_context_menu(self, pos):
    if not hasattr(self, "plan_table") or self.plan_table is None:
        return

    item = self.plan_table.itemAt(pos)
    if item is None:
        return

    row = item.row()
    selected_rows = _get_selected_plan_rows(self)
    if row not in selected_rows:
        self.plan_table.clearSelection()
        self.plan_table.selectRow(row)

    from app_gui.ui import operations_panel as _ops_panel

    menu = _ops_panel.QMenu(self)
    remove_action = menu.addAction(tr("operations.removeSelected"))
    chosen_action = menu.exec(self.plan_table.viewport().mapToGlobal(pos))
    if chosen_action == remove_action:
        self.remove_selected_plan_items()
