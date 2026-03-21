"""Application use cases coordinating domain intents and infra effects."""

import os
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from app_gui.application.event_bus import EventBus
from app_gui.plan_executor import run_plan
from app_gui.plan_outcome import summarize_plan_execution
from lib.domain.commands import SwitchDatasetCommand
from lib.domain.events import DatasetSwitched, MigrationModeChanged, OperationExecuted


class _DatasetSessionLike(Protocol):
    current_yaml_path: str
    gui_config: dict


@dataclass(frozen=True)
class DatasetSwitchResult:
    """Result for dataset-switch command execution."""

    target_path: str
    old_path: str
    new_path: str
    changed: bool
    reason: str


@dataclass(frozen=True)
class PlanRunResult:
    """Result produced by plan execution use case."""

    report: dict
    results: list


class DatasetUseCase:
    """Domain-oriented dataset switching use case."""

    def __init__(
        self,
        *,
        normalize_yaml_path: Callable[[str], str],
        assert_allowed_path: Callable[..., str],
        save_gui_config: Callable[[dict], None],
        ensure_runtime_ready: Optional[Callable[[str], str]] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self._normalize_yaml_path = normalize_yaml_path
        self._assert_allowed_path = assert_allowed_path
        self._save_gui_config = save_gui_config
        self._ensure_runtime_ready = ensure_runtime_ready
        self._event_bus = event_bus

    def switch_dataset(
        self,
        *,
        session: _DatasetSessionLike,
        command: SwitchDatasetCommand,
    ) -> DatasetSwitchResult:
        """Switch active dataset path and persist config if changed."""
        old_abs = os.path.abspath(str(getattr(session, "current_yaml_path", "") or ""))
        normalized = self._normalize_yaml_path(command.yaml_path)
        target = self._assert_allowed_path(normalized, must_exist=True)
        if callable(self._ensure_runtime_ready):
            prepared = self._ensure_runtime_ready(target)
            if isinstance(prepared, str) and prepared.strip():
                target = self._assert_allowed_path(prepared, must_exist=True)
        new_abs = os.path.abspath(str(target))
        reason = str(command.reason or "manual_switch")

        if old_abs == new_abs and reason != "import_success":
            return DatasetSwitchResult(
                target_path=target,
                old_path=old_abs,
                new_path=new_abs,
                changed=False,
                reason=reason,
            )

        session.current_yaml_path = target
        gui_config = getattr(session, "gui_config", None)
        if not isinstance(gui_config, dict):
            raise ValueError("session.gui_config must be a dict")
        gui_config["yaml_path"] = target
        self._save_gui_config(gui_config)

        event = DatasetSwitched(
            old_path=old_abs,
            new_path=new_abs,
            reason=reason,
        )
        if self._event_bus is not None:
            self._event_bus.publish(event)

        return DatasetSwitchResult(
            target_path=target,
            old_path=old_abs,
            new_path=new_abs,
            changed=True,
            reason=reason,
        )


class MigrationModeUseCase:
    """Use case for migration-mode state transitions."""

    def __init__(self, *, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus

    def set_mode(self, *, enabled: bool, reason: str = "ai_panel") -> MigrationModeChanged:
        event = MigrationModeChanged(
            enabled=bool(enabled),
            reason=str(reason or "ai_panel"),
        )
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event


class PlanExecutionUseCase:
    """Use case for publishing operation execution outcomes."""

    def __init__(self, *, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus

    def report_operation_completed(
        self,
        *,
        success: bool,
        operation: str = "plan_execute",
        source: str = "ui",
        trace_id: Optional[str] = None,
    ) -> OperationExecuted:
        event = OperationExecuted(
            operation=str(operation or "plan_execute"),
            success=bool(success),
            trace_id=trace_id,
            reason=str(source or "ui"),
        )
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event


class PlanRunUseCase:
    """Use case for executing staged plan items and normalizing execution rows."""

    def __init__(
        self,
        *,
        run_plan_fn: Callable = run_plan,
        summarize_plan_execution_fn: Callable = summarize_plan_execution,
    ):
        self._run_plan = run_plan_fn
        self._summarize_plan_execution = summarize_plan_execution_fn

    def execute(
        self,
        *,
        yaml_path: str,
        plan_items: list,
        bridge,
        mode: str = "execute",
    ) -> PlanRunResult:
        report = self._run_plan(yaml_path, plan_items, bridge, mode=mode)
        results = self.collect_results(report)
        return PlanRunResult(report=report, results=results)

    def summarize(self, *, report: dict, rollback_info=None) -> dict:
        return self._summarize_plan_execution(report, rollback_info)

    @staticmethod
    def collect_results(report: dict) -> list:
        report_items = report.get("items") if isinstance(report.get("items"), list) else []
        rows = []
        for row in report_items:
            status = "OK" if row.get("ok") else "FAIL"
            info = row.get("response") or {}
            if status == "FAIL":
                info = {
                    "message": row.get("message"),
                    "error_code": row.get("error_code"),
                }
            rows.append((status, row.get("item"), info))
        return rows
