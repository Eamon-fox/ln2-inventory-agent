"""
Module: test_migration_assets_templates
Layer: integration/migration
Covers: agent_skills/migration/*, agent_skills/shared/*

迁移提示词与运行手册模板，验证提示词模板要求显式映射批准、
运行手册定义审批步骤以及验收检查清单的会话跟踪功能。
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE = ROOT / "agent_skills" / "migration" / "references" / "prompt_en.md"
RUNBOOK_TEMPLATE = ROOT / "agent_skills" / "migration" / "references" / "runbook_en.md"
CHECKLIST_TEMPLATE = ROOT / "agent_skills" / "migration" / "assets" / "acceptance_checklist_en.md"


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
