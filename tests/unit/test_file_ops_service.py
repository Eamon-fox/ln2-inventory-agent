from pathlib import Path

from agent import file_ops_service


def test_handle_shell_defaults_to_repo_root_and_injects_migration_env(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    migrate_root = repo_root / "migrate"
    migrate_root.mkdir(parents=True, exist_ok=True)
    captured = {}

    def fake_run_terminal_command(command, timeout_seconds, cwd, engine, extra_env=None):
        captured["command"] = command
        captured["timeout_seconds"] = timeout_seconds
        captured["cwd"] = cwd
        captured["engine"] = engine
        captured["extra_env"] = dict(extra_env or {})
        return {
            "ok": True,
            "exit_code": 0,
            "raw_output": "ok",
            "effective_cwd": cwd,
            "engine": engine,
        }

    monkeypatch.setattr(file_ops_service, "run_terminal_command", fake_run_terminal_command)

    response = file_ops_service.handle_request(
        {
            "tool": "powershell",
            "args": {
                "command": "Write-Output ok",
                "description": "emit ok",
            },
            "repo_root": str(repo_root),
            "migrate_root": str(migrate_root),
        }
    )

    assert response["ok"] is True
    assert captured["cwd"] == str(repo_root.resolve())
    assert captured["engine"] == "powershell"
    assert captured["extra_env"] == {
        "LN2_REPO_ROOT": str(repo_root.resolve()),
        "LN2_MIGRATE_ROOT": str(migrate_root.resolve()),
        "LN2_MIGRATE_INPUTS": str((migrate_root / "inputs").resolve()),
        "LN2_MIGRATE_NORMALIZED": str((migrate_root / "normalized").resolve()),
        "LN2_MIGRATE_OUTPUT": str((migrate_root / "output").resolve()),
        "LN2_MIGRATE_OUTPUT_YAML": str((migrate_root / "output" / "ln2_inventory.yaml").resolve()),
        "LN2_MIGRATE_CHECKLIST": str((migrate_root / "output" / "migration_checklist.md").resolve()),
    }


def test_handle_fs_copy_copies_existing_file_into_migrate(tmp_path):
    repo_root = tmp_path / "repo"
    migrate_root = repo_root / "migrate"
    source = repo_root / "migrate" / "inputs" / "inventory.yaml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("meta: {}\ninventory: []\n", encoding="utf-8")

    response = file_ops_service.handle_request(
        {
            "tool": "fs_copy",
            "args": {
                "src": "migrate/inputs/inventory.yaml",
                "dst": "migrate/output/ln2_inventory.yaml",
            },
            "repo_root": str(repo_root),
            "migrate_root": str(migrate_root),
        }
    )

    target = repo_root / "migrate" / "output" / "ln2_inventory.yaml"
    assert response["ok"] is True
    assert response["resolved_path"] == str(target.resolve())
    assert response["source_path"] == str(source.resolve())
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_handle_fs_copy_requires_explicit_overwrite_for_existing_destination(tmp_path):
    repo_root = tmp_path / "repo"
    migrate_root = repo_root / "migrate"
    source = repo_root / "migrate" / "inputs" / "inventory.yaml"
    target = repo_root / "migrate" / "output" / "ln2_inventory.yaml"
    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("new\n", encoding="utf-8")
    target.write_text("old\n", encoding="utf-8")

    denied = file_ops_service.handle_request(
        {
            "tool": "fs_copy",
            "args": {
                "src": "migrate/inputs/inventory.yaml",
                "dst": "migrate/output/ln2_inventory.yaml",
            },
            "repo_root": str(repo_root),
            "migrate_root": str(migrate_root),
        }
    )
    allowed = file_ops_service.handle_request(
        {
            "tool": "fs_copy",
            "args": {
                "src": "migrate/inputs/inventory.yaml",
                "dst": "migrate/output/ln2_inventory.yaml",
                "overwrite": True,
            },
            "repo_root": str(repo_root),
            "migrate_root": str(migrate_root),
        }
    )

    assert denied["ok"] is False
    assert denied["error_code"] == "file_exists_and_overwrite_false"
    assert allowed["ok"] is True
    assert Path(allowed["resolved_path"]).read_text(encoding="utf-8") == "new\n"
