"""Contract checks to keep the snowfox-system skill aligned with repo truth sources."""

import re
import unittest
from pathlib import Path

import yaml

from agent.react_agent import SYSTEM_PROMPT
from lib.builtin_skills import load_builtin_skill, list_builtin_skills
from app_gui.application.open_api.contracts import (
    LOCAL_OPEN_API_ROUTE_ALLOWLIST,
    LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS,
)
from tests.contract.doc_contract_loader import ROOT, load_contract_block


ARCH_DOC = ROOT / "docs" / "01-系统架构总览.md"
MODULE_MAP_DOC = ROOT / "docs" / "02-模块地图.md"
CHOKEPOINT_DOC = ROOT / "docs" / "03-共享瓶颈点.md"
SETTINGS_DIALOG = ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog.py"
SETTINGS_DIALOG_SECTION_FILES = [
    SETTINGS_DIALOG,
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_about_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_ai_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_custom_fields.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_dataset_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_formatters.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_local_api_section.py",
]


def _combined_settings_dialog_source() -> str:
    parts = []
    for path in SETTINGS_DIALOG_SECTION_FILES:
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


MANAGE_BOXES_DIALOG = ROOT / "app_gui" / "ui" / "dialogs" / "manage_boxes_dialog.py"
INDEXING_WRITE_IMPL = ROOT / "lib" / "tool_api_impl" / "write_set_box_layout_indexing.py"
REPO_SOURCES_DOC = ROOT / "agent_skills" / "snowfox-system" / "maintainers" / "repo_sources.md"


def _reference_documents_by_path() -> dict[str, str]:
    payload = load_builtin_skill("snowfox-system")
    return {
        str(doc.get("path") or ""): str(doc.get("content") or "")
        for doc in list(payload.get("reference_documents") or [])
        if isinstance(doc, dict)
    }


class SnowfoxSystemSkillSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_payload = load_builtin_skill("snowfox-system")
        cls.docs = _reference_documents_by_path()
        cls.architecture_map = cls.docs["agent_skills/snowfox-system/references/architecture_map.md"]
        cls.user_workflows = cls.docs["agent_skills/snowfox-system/references/user_workflows.md"]
        cls.capability_boundaries = cls.docs[
            "agent_skills/snowfox-system/references/capability_boundaries.md"
        ]
        cls.field_schema = cls.docs["agent_skills/snowfox-system/references/field_schema.md"]
        cls.repo_sources = REPO_SOURCES_DOC.read_text(encoding="utf-8")
        cls.runtime_capabilities = yaml.safe_load(
            cls.docs["agent_skills/snowfox-system/references/runtime_capabilities.yaml"]
        )
        cls.skill_contract = load_contract_block(ARCH_DOC, "agent_builtin_skills")

    def test_runtime_skill_does_not_require_repo_docs_in_primary_instructions(self):
        instructions = str(self.skill_payload.get("instructions_markdown") or "")

        self.assertNotIn("repo docs", instructions.lower())
        self.assertNotIn("source files before answering", instructions.lower())
        self.assertNotIn("repo authority map", instructions.lower())

        self.assertIn("bundled references", instructions.lower())
        self.assertIn("runtime authority", instructions.lower())

    def test_runtime_capability_catalog_exists_and_is_structured(self):
        catalog = dict(self.runtime_capabilities or {})
        self.assertIn("settings", catalog)
        self.assertIn("manage_boxes", catalog)
        self.assertIn("position_indexing", catalog)
        self.assertIn("local_open_api", catalog)
        self.assertIn("agent_boundaries", catalog)

    def test_builtin_skill_contract_matches_packaged_skill_catalog(self):
        rules = dict(self.skill_contract.get("rules") or {})
        access = dict(rules.get("access") or {})
        packaged = sorted(str(name) for name in list(access.get("packaged_skills") or []))
        catalog = [row["name"] for row in list_builtin_skills()]

        self.assertEqual("use_skill", access.get("tool_name"))
        self.assertEqual(packaged, catalog)

    def test_snowfox_system_contract_declares_expected_runtime_scope(self):
        rules = dict(self.skill_contract.get("rules") or {})
        runtime_packaging = dict(rules.get("runtime_packaging") or {})
        snowfox_system = dict(rules.get("snowfox_system") or {})
        must_cover = set(str(name) for name in list(snowfox_system.get("must_cover") or []))

        self.assertTrue(bool(runtime_packaging.get("runtime_must_not_require_repo_docs_on_user_machine")))
        self.assertEqual(
            {"gui_operation_paths", "capability_boundaries", "field_schema"},
            must_cover,
        )
        self.assertTrue(bool(snowfox_system.get("must_refuse_unsupported_product_actions_early")))

    def test_runtime_payload_excludes_maintainer_only_repo_sources(self):
        self.assertNotIn(
            "agent_skills/snowfox-system/references/repo_sources.md",
            set(self.docs.keys()),
        )

    def test_field_schema_reference_covers_core_runtime_rules(self):
        text = self.field_schema
        for key in ("`id`", "`box`", "`position`", "`stored_at`", "`storage_events`"):
            with self.subTest(key=key):
                self.assertIn(key, text)
        self.assertIn("5 canonical structural record fields", text)
        self.assertIn("`note`", text)
        self.assertIn("`required: false`", text)
        self.assertIn("`multiline: true`", text)
        self.assertIn("`meta.custom_fields`", text)
        self.assertIn("`meta.box_fields` is no longer supported", text)
        self.assertIn("`display_key`", text)
        self.assertIn("`color_key`", text)
        self.assertIn("`numeric`", text)
        self.assertIn("`alphanumeric`", text)
        self.assertIn("Do not rewrite stored positions into strings like `A1`", text)
        self.assertIn("`parent_cell_line`", text)
        self.assertIn("`frozen_at`", text)
        self.assertIn("`thaw_events`", text)

    def test_field_schema_reference_matches_code_level_schema_constants(self):
        from lib.custom_fields import DEFAULT_NOTE_FIELD, STRUCTURAL_FIELD_KEYS
        from lib.schema_aliases import CANONICAL_STRUCTURAL_FIELD_KEYS

        self.assertEqual(5, len(CANONICAL_STRUCTURAL_FIELD_KEYS))
        for key in CANONICAL_STRUCTURAL_FIELD_KEYS:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", self.field_schema)
        self.assertEqual(CANONICAL_STRUCTURAL_FIELD_KEYS, STRUCTURAL_FIELD_KEYS)
        self.assertEqual("note", DEFAULT_NOTE_FIELD["key"])
        self.assertEqual(False, DEFAULT_NOTE_FIELD["required"])
        self.assertEqual(True, DEFAULT_NOTE_FIELD["multiline"])

    def test_field_schema_reference_matches_custom_field_type_rules(self):
        from lib.custom_fields import _VALID_TYPES  # type: ignore[attr-defined]

        self.assertEqual({"str", "int", "float", "date"}, set(_VALID_TYPES))
        self.assertIn("one of `str`, `int`, `float`, `date`", self.field_schema)

    def test_field_schema_reference_matches_indexing_contract(self):
        contract = load_contract_block(ARCH_DOC, "inventory_position_indexing_rules")
        rules = dict(contract.get("rules") or {})
        indexing_field = dict(rules.get("indexing_field") or {})
        position_field = dict(rules.get("inventory_position_field") or {})

        self.assertEqual("meta.box_layout.indexing", indexing_field.get("storage_path"))
        self.assertEqual("inventory[].position", position_field.get("storage_path"))
        self.assertIn("`meta.box_layout.indexing`", self.field_schema)
        self.assertIn("`inventory[].position`", self.field_schema)

    def test_field_schema_reference_matches_legacy_alias_policy(self):
        from lib.legacy_field_policy import (
            CELL_LINE_OPTIONS_META_KEY,
            CELL_LINE_REQUIRED_META_KEY,
            PARENT_CELL_LINE_FIELD_KEY,
        )
        from lib.schema_aliases import LEGACY_STORED_AT_KEY, LEGACY_STORAGE_EVENTS_KEY

        for key in (
            PARENT_CELL_LINE_FIELD_KEY,
            CELL_LINE_OPTIONS_META_KEY,
            CELL_LINE_REQUIRED_META_KEY,
            LEGACY_STORED_AT_KEY,
            LEGACY_STORAGE_EVENTS_KEY,
        ):
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", self.field_schema)

    def test_architecture_map_mentions_all_documented_modules(self):
        module_map = load_contract_block(MODULE_MAP_DOC, "module_map")
        for module_id in dict(module_map.get("modules") or {}):
            with self.subTest(module_id=module_id):
                self.assertIn(f"`{module_id}`", self.architecture_map)

    def test_architecture_map_mentions_all_shared_chokepoints(self):
        chokepoints = load_contract_block(CHOKEPOINT_DOC, "shared_chokepoints")
        for rel_path in list(chokepoints.get("paths") or []):
            with self.subTest(path=rel_path):
                self.assertIn(f"`{rel_path}`", self.architecture_map)

    def test_capability_boundaries_match_local_open_api_contract(self):
        contract = load_contract_block(ARCH_DOC, "local_open_api_boundary")
        rules = dict(contract.get("rules") or {})
        exposure = dict(rules.get("exposure") or {})

        if exposure.get("must_not_execute_write_tools"):
            self.assertIn("must not execute write tools", self.capability_boundaries)
        self.assertIn("must not expose agent runtime", self.capability_boundaries)
        self.assertIn("read-only plus GUI handoff", self.capability_boundaries)

    def test_capability_boundaries_match_agent_system_prompt_rules(self):
        self.assertIn("You do NOT have permission to add, remove, or rename inventory fields.", SYSTEM_PROMPT)
        self.assertIn("Inventory mutation tools (`add_entry`, `edit_entry`, `takeout`, `move`, `rollback`) are stage-only.", SYSTEM_PROMPT)

        self.assertIn("cannot add, remove, or rename inventory fields", self.capability_boundaries)
        self.assertIn("stage-only", self.capability_boundaries)
        self.assertIn("manage_boxes` requires human confirmation", self.capability_boundaries)
        self.assertIn("write scope is `migrate/` only", self.capability_boundaries)

    def test_user_workflows_track_settings_sections(self):
        source = _combined_settings_dialog_source()
        settings_catalog = dict((self.runtime_capabilities or {}).get("settings") or {})
        for section_id, section in settings_catalog.items():
            section = dict(section or {})
            path = str(section.get("path") or "")
            marker = str(section.get("section_ui_marker") or "")
            with self.subTest(section=section_id):
                self.assertTrue(path)
                self.assertTrue(marker)
                self.assertIn(marker, source)
                if section_id in {"data", "ai", "local_api"}:
                    self.assertIn(path, self.user_workflows)

        self.assertIn("Settings > Manage Fields", self.user_workflows)

    def test_user_workflows_mentions_manage_boxes_indexing_path(self):
        settings_source = _combined_settings_dialog_source()
        manage_boxes_source = MANAGE_BOXES_DIALOG.read_text(encoding="utf-8")

        self.assertIn("Settings > Data > Manage Boxes", self.user_workflows)
        self.assertIn("Set position indexing", self.user_workflows)
        self.assertIn("stored inventory positions remain integers", self.user_workflows)

        manage_boxes_catalog = dict((self.runtime_capabilities or {}).get("manage_boxes") or {})
        self.assertEqual("Settings > Data > Manage Boxes", manage_boxes_catalog.get("entry_path"))
        self.assertIn(str(manage_boxes_catalog.get("entry_ui_marker") or ""), settings_source)
        operations = dict(manage_boxes_catalog.get("operations") or {})
        self.assertEqual(
            {"add", "remove", "set_tag", "set_indexing"},
            set(operations.keys()),
        )
        for operation_id, expected_confirmation in (
            ("add", True),
            ("remove", True),
            ("set_tag", False),
            ("set_indexing", False),
        ):
            with self.subTest(operation=operation_id):
                operation = dict(operations[operation_id] or {})
                self.assertEqual(expected_confirmation, bool(operation.get("requires_confirmation")))
                self.assertIn(str(operation.get("ui_marker") or ""), manage_boxes_source)

    def test_repo_sources_only_reference_existing_repo_files(self):
        paths = re.findall(r"`([^`\n]+/[^`\n]+)`", self.repo_sources)
        self.assertTrue(paths, "repo_sources.md should list repo-relative authority files")
        for rel_path in paths:
            with self.subTest(path=rel_path):
                self.assertTrue((ROOT / rel_path).exists(), f"Authority path missing on disk: {rel_path}")

    def test_repo_sources_is_marked_as_maintainer_only_not_runtime_dependency(self):
        self.assertIn("for maintainers and tests", self.repo_sources)
        self.assertIn("should not require these repo files", self.repo_sources)
        self.assertIn("bundled skill references remain the usable authority", self.repo_sources)

    def test_capability_boundaries_include_indexing_mode_not_position_rewrite(self):
        impl_source = INDEXING_WRITE_IMPL.read_text(encoding="utf-8")

        self.assertIn("without rewriting stored inventory positions", impl_source)
        self.assertIn("Do not rewrite stored `inventory[].position` integers", self.capability_boundaries)
        self.assertIn("Set position indexing", self.user_workflows)

        indexing_catalog = dict((self.runtime_capabilities or {}).get("position_indexing") or {})
        self.assertEqual("meta.box_layout.indexing", indexing_catalog.get("storage_field"))
        self.assertEqual("inventory[].position", indexing_catalog.get("inventory_position_field"))
        self.assertEqual(["numeric", "alphanumeric"], list(indexing_catalog.get("allowed_values") or []))
        self.assertIn("remain integers", str(indexing_catalog.get("inventory_position_rule") or ""))

    def test_runtime_capability_catalog_tracks_settings_data_actions(self):
        source = _combined_settings_dialog_source()
        data_settings = dict((((self.runtime_capabilities or {}).get("settings") or {}).get("data") or {}))
        actions = list(data_settings.get("actions") or [])
        ui_markers = dict(data_settings.get("ui_markers") or {})

        self.assertEqual(actions, list(ui_markers.keys()))
        for action_id, marker in ui_markers.items():
            with self.subTest(action=action_id):
                self.assertIn(marker, source)

    def test_runtime_capability_catalog_tracks_settings_ai_local_api_and_preferences(self):
        source = _combined_settings_dialog_source()
        settings_catalog = dict((self.runtime_capabilities or {}).get("settings") or {})
        for section_id in ("ai", "local_api", "preferences", "about"):
            with self.subTest(section=section_id):
                section = dict(settings_catalog.get(section_id) or {})
                actions = list(section.get("actions") or [])
                ui_markers = dict(section.get("ui_markers") or {})
                self.assertEqual(actions, list(ui_markers.keys()))
                for action_id, marker in ui_markers.items():
                    with self.subTest(action=action_id):
                        self.assertIn(marker, source)

    def test_runtime_capability_catalog_tracks_local_open_api_surface(self):
        catalog = dict((self.runtime_capabilities or {}).get("local_open_api") or {})
        route_groups = dict(catalog.get("route_groups") or {})
        catalog_routes = set(route_groups.get("read_routes") or []) | set(route_groups.get("gui_handoff_routes") or [])
        actual_routes = {f"{method} {path}" for method, path in LOCAL_OPEN_API_ROUTE_ALLOWLIST}
        self.assertEqual(actual_routes, catalog_routes)
        self.assertEqual(
            set(LOCAL_OPEN_API_STAGE_ALLOWED_ACTIONS),
            set(catalog.get("stage_allowed_actions") or []),
        )
        self.assertEqual(
            {
                "loopback_only",
                "disabled_by_default",
                "current_gui_session_dataset_only",
                "explicit_route_allowlist_only",
                "no_write_tool_execution",
                "no_agent_runtime_exposure",
            },
            set(catalog.get("restrictions") or []),
        )

    def test_runtime_capability_catalog_tracks_agent_boundaries(self):
        rules = list((((self.runtime_capabilities or {}).get("agent_boundaries") or {}).get("rules") or []))
        self.assertEqual(
            [
                "field_management_is_gui_only",
                "inventory_mutation_tools_are_stage_only",
                "do_not_patch_managed_inventory_yaml_with_file_tools",
                "local_api_cannot_execute_write_tools",
                "local_api_cannot_expose_agent_runtime",
                "migrate_write_scope_only_for_agent_file_tools",
            ],
            rules,
        )
        self.assertIn("add, remove, or rename inventory fields", SYSTEM_PROMPT)
        self.assertIn("Inventory mutation tools (`add_entry`, `edit_entry`, `takeout`, `move`, `rollback`) are stage-only.", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
