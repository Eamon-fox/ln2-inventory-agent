"""Backward-compatible facade — real logic lives in ``lib.plan_gate``.

GUI callers that need preflight should use the wrappers below which inject
``app_gui.plan_executor.preflight_plan`` automatically.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from lib.plan_gate import (  # noqa: F401 — re-export
    validate_plan_batch as _validate_plan_batch,
    validate_stage_request as _validate_stage_request,
)
from lib.plan_item_factory import PlanItem


def validate_plan_batch(
    *,
    items: List[PlanItem],
    yaml_path: Optional[str],
    bridge: Any = None,
    run_preflight: bool = True,
) -> Dict[str, Any]:
    """Wrapper that injects GUI preflight automatically."""
    from app_gui.plan_executor import preflight_plan

    return _validate_plan_batch(
        items=items,
        yaml_path=yaml_path,
        bridge=bridge,
        run_preflight=run_preflight,
        preflight_fn=preflight_plan,
    )


def validate_stage_request(
    *,
    existing_items: List[PlanItem],
    incoming_items: List[PlanItem],
    yaml_path: Optional[str],
    bridge: Any = None,
    run_preflight: bool = True,
) -> Dict[str, Any]:
    """Wrapper that injects GUI preflight automatically."""
    from app_gui.plan_executor import preflight_plan

    return _validate_stage_request(
        existing_items=existing_items,
        incoming_items=incoming_items,
        yaml_path=yaml_path,
        bridge=bridge,
        run_preflight=run_preflight,
        preflight_fn=preflight_plan,
    )
