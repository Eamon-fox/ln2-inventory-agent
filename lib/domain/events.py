"""Domain event models."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DatasetSwitched:
    old_path: str
    new_path: str
    reason: str


@dataclass(frozen=True)
class PlanStoreChanged:
    item_count: int
    reason: str = "plan_store_changed"


@dataclass(frozen=True)
class MigrationModeChanged:
    enabled: bool
    reason: str = "migration_mode_changed"


@dataclass(frozen=True)
class OperationExecuted:
    operation: str
    success: bool
    trace_id: Optional[str] = None
    reason: str = "operation_executed"

