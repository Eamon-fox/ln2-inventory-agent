"""Helpers for fixed migration workspace asset paths and input staging."""

import os
import shutil
import sys
from typing import Iterable, List

from lib.app_storage import get_install_dir, get_migrate_root


class MigrationWorkspaceError(RuntimeError):
    """Raised when fixed migration workspace is unavailable or invalid."""


class MigrationWorkspaceService:
    """Manage fixed migrate/ workspace under the current writable data root."""

    def __init__(self, root_dir: str = ""):
        workspace = str(root_dir or "").strip()
        self._explicit_root = bool(workspace)
        if not workspace:
            workspace = get_migrate_root()
        self._install_root = os.path.abspath(get_install_dir())
        self._root = os.path.abspath(workspace)
        self._data_root = os.path.abspath(os.path.dirname(self._root))
        self._inputs = os.path.join(self._root, "inputs")
        self._output_dir = os.path.join(self._root, "output")
        self._output_yaml = os.path.join(self._output_dir, "ln2_inventory.yaml")
        self._session_checklist = os.path.join(self._output_dir, "migration_checklist.md")
        self._normalized = os.path.join(self._root, "normalized")
        self._bootstrap_workspace_from_internal_layout()
        self._assert_workspace_layout()
        self._checklist_template = self._resolve_checklist_template()

    @property
    def workspace_root(self) -> str:
        return self._root

    @property
    def inputs_dir(self) -> str:
        return self._inputs

    @property
    def output_yaml_path(self) -> str:
        return self._output_yaml

    @property
    def session_checklist_path(self) -> str:
        return self._session_checklist

    @property
    def normalized_dir(self) -> str:
        return self._normalized

    def reset_inputs_dir(self) -> None:
        """Clear and recreate migrate/inputs directory."""
        if os.path.isfile(self._inputs):
            raise MigrationWorkspaceError(f"inputs path is a file: {self._inputs}")
        if os.path.isdir(self._inputs):
            shutil.rmtree(self._inputs)
        os.makedirs(self._inputs, exist_ok=False)

    def reset_normalized_dir(self) -> None:
        """Clear and recreate migrate/normalized directory."""
        if os.path.isfile(self._normalized):
            raise MigrationWorkspaceError(f"normalized path is a file: {self._normalized}")
        if os.path.isdir(self._normalized):
            shutil.rmtree(self._normalized)
        os.makedirs(self._normalized, exist_ok=False)

    def stage_input_files(self, source_paths: Iterable[str]) -> List[str]:
        """Copy selected files to migrate/inputs after resetting workspace state."""
        normalized: List[str] = []
        seen = set()
        for raw in source_paths or []:
            path = os.path.abspath(str(raw or "").strip())
            if not path:
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            if not os.path.isfile(path):
                raise MigrationWorkspaceError(f"source file not found: {path}")
            normalized.append(path)

        if not normalized:
            raise MigrationWorkspaceError("no source files selected")

        self.reset_output_dir()
        self.reset_session_checklist()
        self.reset_inputs_dir()
        self.reset_normalized_dir()
        copied: List[str] = []
        used_names = set()
        for src in normalized:
            base_name = os.path.basename(src) or "source.bin"
            target_name = self._dedupe_name(base_name, used_names)
            target = os.path.join(self._inputs, target_name)
            shutil.copy2(src, target)
            copied.append(target)
        return copied

    def reset_output_dir(self) -> None:
        """Remove stale generated files from migrate/output for a fresh round."""
        if os.path.isfile(self._output_dir):
            raise MigrationWorkspaceError(f"output path is a file: {self._output_dir}")
        if not os.path.isdir(self._output_dir):
            raise MigrationWorkspaceError(f"migration output directory not found: {self._output_dir}")

        for name in os.listdir(self._output_dir):
            if str(name).strip().lower() == "readme.md":
                continue
            target = os.path.join(self._output_dir, name)
            try:
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
            except Exception as exc:
                raise MigrationWorkspaceError(f"failed to clear output entry: {target} ({exc})") from exc

    def reset_session_checklist(self) -> None:
        """Reset migrate/output checklist from immutable migration skill assets."""
        if not self._checklist_template or not os.path.isfile(self._checklist_template):
            raise MigrationWorkspaceError(
                f"migration checklist template not found: {self._checklist_template}"
            )
        try:
            shutil.copy2(self._checklist_template, self._session_checklist)
        except Exception as exc:
            raise MigrationWorkspaceError(
                f"failed to reset session checklist: {self._session_checklist} ({exc})"
            ) from exc

    def _assert_workspace_layout(self) -> None:
        if not os.path.isdir(self._root):
            raise MigrationWorkspaceError(f"migration workspace not found: {self._root}")
        if os.path.exists(self._output_dir) and not os.path.isdir(self._output_dir):
            raise MigrationWorkspaceError(
                f"migration output path is invalid: {self._output_dir}"
            )
        if not os.path.isdir(self._output_dir):
            os.makedirs(self._output_dir, exist_ok=True)
        if os.path.exists(self._inputs) and not os.path.isdir(self._inputs):
            raise MigrationWorkspaceError(f"migration inputs path is invalid: {self._inputs}")
        if not os.path.isdir(self._inputs):
            os.makedirs(self._inputs, exist_ok=True)
        if os.path.exists(self._normalized) and not os.path.isdir(self._normalized):
            raise MigrationWorkspaceError(f"migration normalized path is invalid: {self._normalized}")
        if not os.path.isdir(self._normalized):
            os.makedirs(self._normalized, exist_ok=True)

    def _bootstrap_workspace_from_internal_layout(self) -> None:
        """Backfill writable migrate/ workspace from bundled layout."""
        needs_workspace = not os.path.isdir(self._root)
        if not needs_workspace:
            return

        for source_root in self._candidate_bundle_roots():
            source_migrate = os.path.join(source_root, "migrate")

            if needs_workspace and os.path.isdir(source_migrate):
                try:
                    shutil.copytree(source_migrate, self._root, dirs_exist_ok=True)
                except Exception as exc:
                    raise MigrationWorkspaceError(
                        f"failed to bootstrap migration workspace: {self._root} ({exc})"
                    ) from exc
                needs_workspace = False

            if not needs_workspace:
                break

    def _candidate_bundle_roots(self) -> List[str]:
        roots: List[str] = []
        seen = set()
        if self._explicit_root:
            candidates = [
                self._data_root,
                os.path.join(self._data_root, "_internal"),
                os.path.join(self._data_root, "..", "Resources"),
                os.path.join(self._data_root, "..", "Frameworks"),
            ]
        else:
            candidates = [
                self._data_root,
                self._install_root,
                os.path.join(self._install_root, "_internal"),
                os.path.join(self._install_root, "..", "Resources"),
                os.path.join(self._install_root, "..", "Frameworks"),
            ]
        if getattr(sys, "frozen", False):
            candidates.append(getattr(sys, "_MEIPASS", ""))

        for candidate in candidates:
            root = os.path.abspath(str(candidate or "").strip())
            if not root or root in seen:
                continue
            seen.add(root)
            roots.append(root)
        return roots

    def _resolve_checklist_template(self) -> str:
        for source_root in self._candidate_bundle_roots():
            candidate = os.path.join(
                source_root,
                "agent_skills",
                "migration",
                "assets",
                "acceptance_checklist_en.md",
            )
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return ""

    @staticmethod
    def _dedupe_name(name: str, used_names: set) -> str:
        base, ext = os.path.splitext(str(name or "source.bin"))
        candidate = f"{base}{ext}"
        idx = 2
        while candidate.lower() in used_names:
            candidate = f"{base}_{idx}{ext}"
            idx += 1
        used_names.add(candidate.lower())
        return candidate
