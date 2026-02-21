"""Facade module for add/edit write operations."""

from . import write_add_entry as _add_ops
from . import write_edit_entry as _edit_ops


_EDITABLE_FIELDS = _edit_ops._EDITABLE_FIELDS


def _get_editable_fields(yaml_path):
    return _edit_ops._get_editable_fields(yaml_path)


def _tool_add_entry_impl(
    yaml_path,
    box,
    positions,
    frozen_at,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    return _add_ops._tool_add_entry_impl(
        yaml_path=yaml_path,
        box=box,
        positions=positions,
        frozen_at=frozen_at,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def tool_edit_entry(
    yaml_path,
    record_id,
    fields,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    return _edit_ops.tool_edit_entry(
        yaml_path=yaml_path,
        record_id=record_id,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )