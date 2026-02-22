"""Facade module for rollback and box-count write operations."""

from . import write_adjust_box_count as _box_ops
from . import write_rollback as _rollback_ops


def tool_rollback(
    yaml_path,
    backup_path=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    source_event=None,
    request_backup_path=None,
):
    return _rollback_ops.tool_rollback(
        yaml_path=yaml_path,
        backup_path=backup_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        source_event=source_event,
        request_backup_path=request_backup_path,
    )


def _tool_adjust_box_count_impl(
    yaml_path,
    operation,
    count=1,
    box=None,
    renumber_mode=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    return _box_ops._tool_adjust_box_count_impl(
        yaml_path=yaml_path,
        operation=operation,
        count=count,
        box=box,
        renumber_mode=renumber_mode,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
