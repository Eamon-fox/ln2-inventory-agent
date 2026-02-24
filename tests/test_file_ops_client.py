from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent.file_ops_client import run_file_tool


def _make_managed_yaml(base_dir: str) -> Path:
    repo_root = Path(base_dir).resolve()
    yaml_path = repo_root / "inventories" / "demo" / "inventory.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("meta: {}\ninventory: []\n", encoding="utf-8")
    return yaml_path


def test_run_file_tool_calls_service_in_process():
    with TemporaryDirectory(prefix="ln2_fileops_client_") as td:
        yaml_path = _make_managed_yaml(td)
        expected_repo = str(yaml_path.parents[2])
        expected_migrate = str((yaml_path.parents[2] / "migrate").resolve(strict=False))

        with patch("agent.file_ops_service.handle_request", return_value={"ok": True}) as mock_handle:
            response = run_file_tool("fs_list", {"path": "migrate"}, yaml_path=str(yaml_path))

        mock_handle.assert_called_once()
        payload = mock_handle.call_args.args[0]
        assert payload["tool"] == "fs_list"
        assert payload["args"] == {"path": "migrate"}
        assert payload["repo_root"] == expected_repo
        assert payload["migrate_root"] == expected_migrate
        assert response["ok"] is True
        assert response["effective_root"] == expected_repo


def test_run_file_tool_returns_structured_error_when_service_raises():
    with TemporaryDirectory(prefix="ln2_fileops_client_") as td:
        yaml_path = _make_managed_yaml(td)
        expected_repo = str(yaml_path.parents[2])

        with patch("agent.file_ops_service.handle_request", side_effect=RuntimeError("boom")):
            response = run_file_tool("fs_read", {"path": "migrate/a.txt"}, yaml_path=str(yaml_path))

        assert response["ok"] is False
        assert response["error_code"] == "file_ops_service_failed"
        assert "boom" in str(response["message"])
        assert response["effective_root"] == expected_repo


def test_run_file_tool_rejects_non_object_response():
    with TemporaryDirectory(prefix="ln2_fileops_client_") as td:
        yaml_path = _make_managed_yaml(td)
        expected_repo = str(yaml_path.parents[2])

        with patch("agent.file_ops_service.handle_request", return_value="bad"):
            response = run_file_tool("fs_write", {"path": "migrate/x.txt", "content": "x"}, yaml_path=str(yaml_path))

        assert response["ok"] is False
        assert response["error_code"] == "file_ops_invalid_response"
        assert response["effective_root"] == expected_repo
