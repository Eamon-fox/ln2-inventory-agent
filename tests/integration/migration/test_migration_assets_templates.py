"""
Module: test_migration_assets_templates
Layer: integration/migration
Covers: agent_skills/migration/*, agent_skills/shared/*

迁移提示词与运行手册模板，验证提示词模板要求显式映射批准、
运行手册定义审批步骤以及验收检查清单的会话跟踪功能。
"""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE = ROOT / "agent_skills" / "migration" / "references" / "prompt_en.md"
RUNBOOK_TEMPLATE = ROOT / "agent_skills" / "migration" / "references" / "runbook_en.md"
CHECKLIST_TEMPLATE = ROOT / "agent_skills" / "migration" / "assets" / "acceptance_checklist_en.md"
IMPORT_SCHEMA = ROOT / "migration_assets" / "schema" / "ln2_import_schema.json"
EXAMPLE_MIN = ROOT / "migration_assets" / "examples" / "valid_inventory_min.yaml"
EXAMPLE_FULL = ROOT / "migration_assets" / "examples" / "valid_inventory_full.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prompt_template_requires_mapping_approval_before_lock():
    text = _read(PROMPT_TEMPLATE)
    assert "get explicit user approval" in text
    assert "confirm the field mapping/schema plan" in text


def test_runbook_requires_explicit_mapping_approval_step():
    text = _read(RUNBOOK_TEMPLATE)
    assert "request explicit approval" in text
    assert "revise the proposal and confirm again" in text


def test_acceptance_checklist_requires_user_mapping_approval():
    text = _read(CHECKLIST_TEMPLATE)
    assert "User explicitly approved the field mapping/schema plan" in text


def test_templates_define_live_session_checklist_tracking():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)
    checklist_text = _read(CHECKLIST_TEMPLATE)

    assert "migrate/output/migration_checklist.md" in prompt_text
    assert "migrate/output/migration_checklist.md" in runbook_text
    assert "migrate/output/migration_checklist.md" in checklist_text


def test_templates_require_repo_relative_paths_for_shell_and_file_tools():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)

    assert "repo-relative paths" in prompt_text
    assert "repo-relative paths" in runbook_text


def test_templates_prefer_fs_copy_for_identity_yaml_passthrough():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)

    assert "fs_copy" in prompt_text
    assert "fs_copy" in runbook_text
    assert "identity" in prompt_text


def test_templates_do_not_special_case_cell_line_as_builtin_field():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)
    checklist_text = _read(CHECKLIST_TEMPLATE)

    assert "Treat fields like `cell_line` as ordinary custom fields" in prompt_text
    assert "schema-declared required custom fields" in runbook_text
    assert "Every custom field marked `required: true`" in checklist_text


def test_templates_use_stored_at_as_canonical_migration_field():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)
    checklist_text = _read(CHECKLIST_TEMPLATE)

    assert "stored_at" in prompt_text
    assert "stored_at" in runbook_text
    assert "stored_at" in checklist_text
    assert "frozen_at" not in runbook_text


def test_templates_define_resume_behavior_from_existing_outputs():
    prompt_text = _read(PROMPT_TEMPLATE)
    runbook_text = _read(RUNBOOK_TEMPLATE)

    assert "resume from the highest valid completed stage" in prompt_text
    assert "resume from the highest valid completed stage" in runbook_text


def test_migration_schema_and_examples_use_canonical_storage_field_names():
    schema = json.loads(_read(IMPORT_SCHEMA))
    item_properties = schema["properties"]["inventory"]["items"]["properties"]
    assert "stored_at" in item_properties
    assert "storage_events" in item_properties
    assert "frozen_at" not in item_properties
    assert "thaw_events" not in item_properties

    example_min = yaml.safe_load(_read(EXAMPLE_MIN))
    example_full = yaml.safe_load(_read(EXAMPLE_FULL))
    for document in (example_min, example_full):
        for record in document["inventory"]:
            assert "stored_at" in record
            assert "storage_events" in record
            assert "frozen_at" not in record
            assert "thaw_events" not in record
