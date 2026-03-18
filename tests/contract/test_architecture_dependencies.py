"""Contract tests for architecture dependency boundaries."""

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

OPERATIONS_PANEL_PUBLIC_API = (
    "apply_meta_update",
    "set_migration_mode_enabled",
    "update_records_cache",
    "set_prefill",
    "set_prefill_background",
    "set_add_prefill",
    "set_add_prefill_background",
    "add_plan_items",
    "execute_plan",
    "clear_plan",
    "reset_for_dataset_switch",
    "on_export_inventory_csv",
    "emit_external_operation_event",
    "print_plan",
    "print_last_executed",
    "on_undo_last",
    "remove_selected_plan_items",
    "on_plan_table_context_menu",
)

OPERATIONS_PANEL_ALIAS_ALLOWLIST = set()

OPERATIONS_PANEL_REMOVED_PRIVATE_ALIASES = {
    "_lookup_record",
    "_refresh_takeout_record_context",
    "_refresh_move_record_context",
    "_rebuild_custom_add_fields",
    "_handle_response",
    "_get_selected_plan_rows",
    "_enable_undo",
    "_build_print_grid_state",
}


def _parse_ast(path: Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _import_modules(path: Path):
    tree = _parse_ast(path)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name or ""))
        elif isinstance(node, ast.ImportFrom):
            modules.add(str(node.module or ""))
    return modules


def _find_class(tree: ast.AST, class_name: str):
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _is_ops_bridge_alias_expr(value_node: ast.AST):
    if isinstance(value_node, ast.Attribute):
        return isinstance(value_node.value, ast.Name) and value_node.value.id.startswith("_ops_")
    if (
        isinstance(value_node, ast.Call)
        and isinstance(value_node.func, ast.Name)
        and value_node.func.id == "staticmethod"
        and len(value_node.args) == 1
    ):
        return _is_ops_bridge_alias_expr(value_node.args[0])
    return False


def _collect_operations_panel_members(class_node: ast.ClassDef):
    methods = set()
    alias_names = set()
    for stmt in class_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(stmt.name)
            continue
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if _is_ops_bridge_alias_expr(stmt.value):
            alias_names.add(target.id)
    return methods, alias_names


class ArchitectureDependencyTests(unittest.TestCase):
    def test_domain_layer_does_not_depend_on_pyside(self):
        domain_root = ROOT / "lib" / "domain"
        self.assertTrue(domain_root.exists(), "lib/domain should exist")

        for file_path in domain_root.rglob("*.py"):
            modules = _import_modules(file_path)
            offenders = sorted(mod for mod in modules if mod.startswith("PySide6"))
            self.assertEqual(
                [],
                offenders,
                f"{file_path} should not import GUI framework modules: {offenders}",
            )

    def test_ui_layer_does_not_import_write_validation_infra_directly(self):
        ui_root = ROOT / "app_gui" / "ui"
        disallowed_prefixes = (
            "lib.tool_api_write",
            "lib.tool_api_write_validation",
        )

        for file_path in ui_root.rglob("*.py"):
            modules = _import_modules(file_path)
            offenders = sorted(
                mod for mod in modules if any(mod.startswith(prefix) for prefix in disallowed_prefixes)
            )
            self.assertEqual(
                [],
                offenders,
                f"{file_path} imports infra write modules directly: {offenders}",
            )

    def test_operations_panel_public_api_symbols_exist(self):
        panel_path = ROOT / "app_gui" / "ui" / "operations_panel.py"
        tree = _parse_ast(panel_path)
        public_api = set(OPERATIONS_PANEL_PUBLIC_API)
        self.assertTrue(public_api, "OPERATIONS_PANEL_PUBLIC_API must not be empty")

        class_node = _find_class(tree, "OperationsPanel")
        self.assertIsNotNone(class_node, "OperationsPanel class should exist")
        methods, _alias_names = _collect_operations_panel_members(class_node)

        missing = sorted(public_api - methods)
        self.assertEqual(
            [],
            missing,
            "OperationsPanel public API symbols missing from explicit method definitions: "
            f"{missing}",
        )

    def test_operations_panel_ops_bridge_aliases_are_allowlisted(self):
        panel_path = ROOT / "app_gui" / "ui" / "operations_panel.py"
        tree = _parse_ast(panel_path)
        allowlist = set(OPERATIONS_PANEL_ALIAS_ALLOWLIST)

        class_node = _find_class(tree, "OperationsPanel")
        self.assertIsNotNone(class_node, "OperationsPanel class should exist")
        _methods, alias_names = _collect_operations_panel_members(class_node)

        unexpected = sorted(alias_names - allowlist)
        self.assertEqual(
            [],
            unexpected,
            "Unexpected `_ops_*` bridge aliases added to OperationsPanel: "
            f"{unexpected}",
        )
        self.assertLessEqual(
            len(alias_names),
            0,
            f"OperationsPanel bridge alias count regressed: {len(alias_names)} > 0",
        )

    def test_operations_panel_private_aliases_not_called_from_tests(self):
        integration_root = ROOT / "tests" / "integration" / "gui"
        pattern = re.compile(
            r"\bpanel\.(?P<name>"
            + "|".join(re.escape(name) for name in sorted(OPERATIONS_PANEL_REMOVED_PRIVATE_ALIASES))
            + r")\s*\("
        )

        offenders = []
        for file_path in integration_root.rglob("test_*.py"):
            text = file_path.read_text(encoding="utf-8-sig")
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = pattern.search(line)
                if not match:
                    continue
                offenders.append(f"{file_path}:{line_no}:{match.group('name')}")

        self.assertEqual(
            [],
            offenders,
            "Integration tests still rely on removed OperationsPanel private aliases: "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
