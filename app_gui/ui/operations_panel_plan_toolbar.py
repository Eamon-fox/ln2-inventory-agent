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

    rows = self._get_selected_plan_rows()
    has_selected = bool(rows)
    has_items = bool(self._plan_store.count())
    self.plan_remove_selected_btn.setEnabled(has_selected)
    self.plan_clear_btn.setEnabled(has_items)


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
