"""
Module: test_dataset_session
Layer: integration/gui
Covers: app_gui/dataset_session.py

Dataset session command delegation tests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app_gui.dataset_session import DatasetSessionController
from lib.domain.commands import SwitchDatasetCommand


def test_switch_to_delegates_to_use_case_with_command_payload():
    window = SimpleNamespace()
    use_case = SimpleNamespace(
        switch_dataset=MagicMock(return_value=SimpleNamespace(target_path="D:/data/new/inventory.yaml"))
    )
    controller = DatasetSessionController(window, dataset_use_case=use_case)

    result = controller.switch_to("D:/data/new/inventory.yaml", reason="manual_switch")

    assert result == "D:/data/new/inventory.yaml"
    use_case.switch_dataset.assert_called_once()
    called_kwargs = use_case.switch_dataset.call_args.kwargs
    assert called_kwargs["session"] is window
    command = called_kwargs["command"]
    assert isinstance(command, SwitchDatasetCommand)
    assert command.yaml_path == "D:/data/new/inventory.yaml"
    assert command.reason == "manual_switch"


def test_switch_to_uses_default_reason_when_empty():
    window = SimpleNamespace()
    use_case = SimpleNamespace(
        switch_dataset=MagicMock(return_value=SimpleNamespace(target_path="D:/data/default/inventory.yaml"))
    )
    controller = DatasetSessionController(window, dataset_use_case=use_case)

    result = controller.switch_to("D:/data/default/inventory.yaml", reason="")

    assert result == "D:/data/default/inventory.yaml"
    command = use_case.switch_dataset.call_args.kwargs["command"]
    assert command.reason == "manual_switch"


def test_switch_to_returns_use_case_target_path_verbatim():
    window = SimpleNamespace()
    use_case = SimpleNamespace(
        switch_dataset=MagicMock(return_value=SimpleNamespace(target_path="D:/data/imported/inventory.yaml"))
    )
    controller = DatasetSessionController(window, dataset_use_case=use_case)

    result = controller.switch_to("D:/ignored/path.yaml", reason="import_success")

    assert result == "D:/data/imported/inventory.yaml"
