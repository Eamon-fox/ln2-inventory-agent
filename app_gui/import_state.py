"""State types for the import journey workflow."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ImportJourneyState:
    """Minimal explicit state machine snapshot for one import run."""

    mode: str = ""
    stage: str = "idle"
    source_paths: List[str] = field(default_factory=list)
    candidate_yaml: str = ""
    target_yaml: str = ""
    message: str = ""
    error_code: str = ""
    validation_report: Dict[str, object] = field(default_factory=dict)

    def set_stage(self, stage: str) -> None:
        self.stage = str(stage or "").strip() or "idle"

