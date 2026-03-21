"""Application use case helpers for audit-log presentation."""

from lib.custom_fields import get_effective_fields
from lib.yaml_ops import load_yaml


class AuditViewUseCase:
    """Load read-only audit-view metadata for GUI presentation."""

    def load_field_order(self, *, yaml_path: str) -> list[str]:
        try:
            data = load_yaml(yaml_path) or {}
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        meta = data.get("meta")
        if not isinstance(meta, dict):
            meta = {}

        inventory = data.get("inventory")
        if not isinstance(inventory, list):
            inventory = []

        return [
            str(field.get("key"))
            for field in get_effective_fields(meta, inventory=inventory)
            if isinstance(field, dict) and field.get("key")
        ]
