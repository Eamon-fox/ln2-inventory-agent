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
        "LN2_MIGRATE_VALIDATION_REPORT": str((migrate_root / "output" / "validation_report.json").resolve()),
    }
