"""Stable application-layer contract for settings dialog submissions."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class SettingsDialogSubmission:
    yaml_path: str = ""
    api_keys: Dict[str, str] = field(default_factory=dict)
    language: str = "en"
    theme: str = "dark"
    ui_scale: float = 1.0
    open_api_enabled: bool = False
    open_api_port: int = 0
    ai_provider: str = ""
    ai_model: str = ""
    ai_max_steps: int = 0
    ai_thinking_enabled: bool = True
    ai_custom_prompt: str = ""

    def as_dict(self) -> dict:
        return {
            "yaml_path": self.yaml_path,
            "api_keys": dict(self.api_keys or {}),
            "language": self.language,
            "theme": self.theme,
            "ui_scale": self.ui_scale,
            "open_api_enabled": self.open_api_enabled,
            "open_api_port": self.open_api_port,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "ai_max_steps": self.ai_max_steps,
            "ai_thinking_enabled": self.ai_thinking_enabled,
            "ai_custom_prompt": self.ai_custom_prompt,
        }
