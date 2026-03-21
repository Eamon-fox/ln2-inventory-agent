from pathlib import Path

from lib.builtin_skills import build_skill_catalog_prompt, list_builtin_skills, load_builtin_skill


def test_list_builtin_skills_returns_expected_names():
    rows = list_builtin_skills()
    names = [row["name"] for row in rows]

    assert names == sorted(names)
    assert "migration" in names
    assert "snowfox-system" in names
    assert "yaml-repair" in names


def test_build_skill_catalog_prompt_lists_skills_without_paths():
    text = build_skill_catalog_prompt()

    assert "Built-in skills are available via the `use_skill` tool." in text
    assert "`migration`:" in text
    assert "`snowfox-system`:" in text
    assert "`yaml-repair`:" in text
    assert "agent_skills/migration/SKILL.md" not in text


def test_load_builtin_skill_returns_skill_body_and_resources():
    payload = load_builtin_skill("migration")

    assert payload["name"] == "migration"
    assert "Core Workflow" in payload["instructions_markdown"]
    assert "agent_skills/migration/references/runbook_en.md" in payload["references"]
    assert "agent_skills/shared/references/schema_context.md" in payload["shared_references"]
    ref_docs = list(payload["reference_documents"])
    shared_docs = list(payload["shared_reference_documents"])
    assert any(doc["path"] == "agent_skills/migration/references/runbook_en.md" for doc in ref_docs)
    assert any("fs_copy" in doc["content"] for doc in ref_docs)
    assert any(doc["path"] == "agent_skills/shared/references/schema_context.md" for doc in shared_docs)


def test_load_builtin_skill_returns_snowfox_system_references():
    payload = load_builtin_skill("snowfox-system")

    assert payload["name"] == "snowfox-system"
    assert "Core Workflow" in payload["instructions_markdown"]
    assert "agent_skills/snowfox-system/references/architecture_map.md" in payload["references"]
    assert "agent_skills/snowfox-system/references/repo_sources.md" not in payload["references"]
    ref_docs = list(payload["reference_documents"])
    assert any(
        doc["path"] == "agent_skills/snowfox-system/references/capability_boundaries.md"
        for doc in ref_docs
    )
    assert any("Settings > Manage Fields" in doc["content"] for doc in ref_docs)
    assert all(doc["path"] != "agent_skills/snowfox-system/references/repo_sources.md" for doc in ref_docs)


def test_skill_markdown_files_exist():
    root = Path(__file__).resolve().parents[2]

    assert (root / "agent_skills" / "migration" / "SKILL.md").is_file()
    assert (root / "agent_skills" / "snowfox-system" / "SKILL.md").is_file()
    assert (root / "agent_skills" / "yaml-repair" / "SKILL.md").is_file()
