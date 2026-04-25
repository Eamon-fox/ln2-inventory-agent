"""Unified Tool API shared by CLI, GUI, and AI agents."""

from .schema_aliases import (
    coalesce_stored_at_value,
    expand_structural_aliases_in_sections,
)
from . import tool_api_support as _support
from . import tool_api_write_v2 as _write_v2


_get_layout = _support._get_layout
_format_box_constraint = _support._format_box_constraint
_is_middle_box = _support._is_middle_box


build_actor_context = _support.build_actor_context
coerce_position_value = _support.coerce_position_value
normalize_positions_input = _support.normalize_positions_input
parse_batch_entries = _support.parse_batch_entries
coerce_batch_entry = _support.coerce_batch_entry
parse_slot_payload = _support.parse_slot_payload
format_positions_in_payload = _support.format_positions_in_payload
find_record_by_id_local = _support.find_record_by_id_local
validate_source_slot_match = _support.validate_source_slot_match
_format_tool_response_positions = _support._format_tool_response_positions
_build_move_event = _support._build_move_event


_build_audit_meta = _support._build_audit_meta
_validate_data_or_error = _support._validate_data_or_error
_append_failed_audit = _support._append_failed_audit
_failure_result = _support._failure_result

_ALLOWED_EXECUTION_MODES = _support._ALLOWED_EXECUTION_MODES
_normalize_execution_mode = _support._normalize_execution_mode
_enforce_execute_mode_for_source = _support._enforce_execute_mode_for_source
_validate_execution_gate = _support._validate_execution_gate
_validate_add_entry_request = _support._validate_add_entry_request
_validate_edit_entry_request = _support._validate_edit_entry_request
_validate_takeout_request = _support._validate_takeout_request
_validate_manage_boxes_request = _support._validate_manage_boxes_request
_WRITE_REQUEST_VALIDATORS = _support._WRITE_REQUEST_VALIDATORS


def validate_write_tool_call(
    *,
    yaml_path,
    action,
    source,
    tool_name,
    tool_input,
    payload,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    before_data=None,
    auto_backup=True,
    request_backup_path=None,
):
    return _support.validate_write_tool_call(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload=payload,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        before_data=before_data,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )


def tool_add_entry(
    yaml_path,
    box,
    positions,
    frozen_at=None,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
    **kwargs,
):
    effective_stored_at = kwargs.pop("stored_at", None)
    if kwargs:
        unexpected = ", ".join(sorted(kwargs.keys()))
        raise TypeError(f"Unexpected keyword arguments: {unexpected}")
    effective_stored_at = coalesce_stored_at_value(
        stored_at=effective_stored_at,
        frozen_at=frozen_at,
    )
    response = _tool_add_entry_impl(
        yaml_path=yaml_path,
        box=box,
        positions=positions,
        frozen_at=effective_stored_at,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def _tool_add_entry_impl(
    yaml_path,
    box,
    positions,
    frozen_at=None,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_add_entry_impl(
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
    return _format_tool_response_positions(response, yaml_path=yaml_path)


_EDITABLE_FIELDS = {"stored_at", "frozen_at"}


def _get_editable_fields(yaml_path):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._get_editable_fields(yaml_path)


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
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_edit_entry(
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
    response = _format_tool_response_positions(response, yaml_path=yaml_path)
    result = response.get("result") if isinstance(response, dict) else None
    if isinstance(result, dict):
        expand_structural_aliases_in_sections(result)
    preview = response.get("preview") if isinstance(response, dict) else None
    if isinstance(preview, dict):
        expand_structural_aliases_in_sections(preview)
    return response


tool_takeout = _write_v2.tool_takeout
tool_move = _write_v2.tool_move
_tool_takeout_impl = _write_v2._tool_takeout_impl

def tool_batch_add_entries(
    yaml_path,
    entries,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Add multiple entries in a single load/validate/write cycle.

    Each entry dict must contain: box, positions, stored_at/frozen_at, fields.
    Returns a batch result with per-entry status in ``entry_results``.
    Atomicity: all entries must validate before any are written.
    """
    from .tool_api_impl.write_batch_add import tool_batch_add_entries as _impl

    response = _impl(
        yaml_path=yaml_path,
        entries=entries,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_rollback(
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
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_manage_boxes(
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
    response = _tool_manage_boxes_impl(
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
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def _tool_manage_boxes_impl(
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
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_manage_boxes_impl(
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
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_set_box_tag(
    yaml_path,
    box,
    tag="",
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_set_box_tag(
        yaml_path=yaml_path,
        box=box,
        tag=tag,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_set_box_layout_indexing(
    yaml_path,
    indexing,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_set_box_layout_indexing(
        yaml_path=yaml_path,
        indexing=indexing,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_export_inventory_csv(yaml_path, output_path):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_export_inventory_csv(
        yaml_path=yaml_path,
        output_path=output_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_list_empty_positions(yaml_path, box=None):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_list_empty_positions(
        yaml_path=yaml_path,
        box=box,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


record_search_blob = _support.record_search_blob


parse_search_location_shortcut = _support.parse_search_location_shortcut

def tool_search_records(
    yaml_path,
    query=None,
    mode="fuzzy",
    max_results=None,
    case_sensitive=False,
    box=None,
    position=None,
    record_id=None,
    status="all",
    sort_by=None,
    sort_order="desc",
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_search_records(
        yaml_path=yaml_path,
        query=query,
        mode=mode,
        max_results=max_results,
        case_sensitive=case_sensitive,
        box=box,
        position=position,
        record_id=record_id,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_filter_records(
    yaml_path,
    keyword=None,
    box=None,
    color_value=None,
    include_inactive=False,
    column_filters=None,
    sort_by="location",
    sort_order="asc",
    limit=None,
    offset=0,
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_filter_records(
        yaml_path=yaml_path,
        keyword=keyword,
        box=box,
        color_value=color_value,
        include_inactive=include_inactive,
        column_filters=column_filters,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_recent_frozen(yaml_path, days=None, count=None):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_recent_frozen(
        yaml_path=yaml_path,
        days=days,
        count=count,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_recent_stored(yaml_path, days=None, count=None):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_recent_stored(
        yaml_path=yaml_path,
        days=days,
        count=count,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_query_takeout_events(
    yaml_path,
    date=None,
    days=None,
    start_date=None,
    end_date=None,
    action=None,
    max_records=0,
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_query_takeout_events(
        yaml_path=yaml_path,
        date=date,
        days=days,
        start_date=start_date,
        end_date=end_date,
        action=action,
        max_records=max_records,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)
_collect_timeline_events = _support._collect_timeline_events


def tool_collect_timeline(yaml_path, days=30, all_history=False):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_collect_timeline(
        yaml_path=yaml_path,
        days=days,
        all_history=all_history,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_list_audit_timeline(
    yaml_path,
    limit=50,
    offset=0,
    action_filter=None,
    status_filter=None,
    start_date=None,
    end_date=None,
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_list_audit_timeline(
        yaml_path=yaml_path,
        limit=limit,
        offset=offset,
        action_filter=action_filter,
        status_filter=status_filter,
        start_date=start_date,
        end_date=end_date,
    )
    return _format_tool_response_positions(response, layout={})
_find_consecutive_slots = _support._find_consecutive_slots
_find_same_row_slots = _support._find_same_row_slots


def tool_recommend_positions(yaml_path, count, box_preference=None, strategy="consecutive"):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_recommend_positions(
        yaml_path=yaml_path,
        count=count,
        box_preference=box_preference,
        strategy=strategy,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_generate_stats(
    yaml_path,
    box=None,
    include_inactive=False,
    full_records_for_gui=False,
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_generate_stats(
        yaml_path=yaml_path,
        box=box,
        include_inactive=include_inactive,
        full_records_for_gui=full_records_for_gui,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_get_raw_entries(yaml_path, ids):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_get_raw_entries(
        yaml_path=yaml_path,
        ids=ids,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)
