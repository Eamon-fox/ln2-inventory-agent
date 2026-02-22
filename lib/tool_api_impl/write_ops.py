"""Write-operation facade for Tool API."""

from . import write_add_edit, write_rollback_box, write_takeout_batch, write_takeout_single


_EDITABLE_FIELDS = write_add_edit._EDITABLE_FIELDS


def _get_editable_fields(yaml_path):
    return write_add_edit._get_editable_fields(yaml_path)


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
    request_backup_path=None,
):
    return write_add_edit._tool_add_entry_impl(
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
        request_backup_path=request_backup_path,
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
    request_backup_path=None,
):
    return write_add_edit.tool_edit_entry(
        yaml_path=yaml_path,
        record_id=record_id,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )


def tool_list_backups(yaml_path):
    return write_rollback_box.tool_list_backups(yaml_path=yaml_path)


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
    return write_rollback_box.tool_rollback(
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


def _tool_record_takeout_impl(
    yaml_path,
    record_id,
    position=None,
    date_str=None,
    action="takeout",
    to_position=None,
    to_box=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    return write_takeout_single._tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=position,
        date_str=date_str,
        action=action,
        to_position=to_position,
        to_box=to_box,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )


def _tool_batch_takeout_impl(
    yaml_path,
    entries,
    date_str,
    action="takeout",
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    return write_takeout_batch._tool_batch_takeout_impl(
        yaml_path=yaml_path,
        entries=entries,
        date_str=date_str,
        action=action,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
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
    return write_rollback_box._tool_adjust_box_count_impl(
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
