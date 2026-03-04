"""Domain command models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SwitchDatasetCommand:
    yaml_path: str
    reason: str = "manual_switch"


@dataclass(frozen=True)
class CreateDatasetCommand:
    dataset_name: str
    reason: str = "new_dataset"


@dataclass(frozen=True)
class RenameDatasetCommand:
    current_yaml_path: str
    target_dataset_name: str
    reason: str = "dataset_rename"


@dataclass(frozen=True)
class DeleteDatasetCommand:
    current_yaml_path: str
    reason: str = "dataset_delete"


@dataclass(frozen=True)
class ExecutePlanCommand:
    yaml_path: str
    reason: str = "execute_plan"

