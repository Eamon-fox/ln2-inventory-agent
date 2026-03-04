"""Dataset session switching controller.

All dataset-path switches in GUI should go through this controller.
"""

from app_gui.application import DatasetUseCase
from lib.domain.commands import SwitchDatasetCommand


class DatasetSessionController:
    """Single entrypoint for dataset switch commands."""

    def __init__(
        self,
        window,
        *,
        dataset_use_case: DatasetUseCase,
    ):
        self._window = window
        self._dataset_use_case = dataset_use_case

    def switch_to(self, yaml_path: str, *, reason: str = "manual_switch") -> str:
        """Switch active dataset path via the application use case.

        Raises:
            ValueError / FileNotFoundError / InventoryPathError on invalid paths.
        """
        command = SwitchDatasetCommand(
            yaml_path=str(yaml_path or ""),
            reason=str(reason or "manual_switch"),
        )
        result = self._dataset_use_case.switch_dataset(
            session=self._window,
            command=command,
        )
        return result.target_path
