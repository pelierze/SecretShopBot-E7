"""Generated route cache metadata helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .probability_data import ProbabilityDataset


@dataclass(frozen=True)
class GeneratedPolicy:
    schema_version: int
    event_id: str
    source_probability_fingerprint: Optional[str]
    plans: Dict[str, Dict]
    generated_at: Optional[str] = None
    generator_version: Optional[str] = None

    def is_stale_for(self, dataset: ProbabilityDataset) -> bool:
        return self.source_probability_fingerprint != dataset.fingerprint


def load_generated_policy(path: Path) -> GeneratedPolicy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return GeneratedPolicy(
        schema_version=int(raw.get("schema_version", 1)),
        event_id=str(raw.get("event_id", "2026_summer_event")),
        source_probability_fingerprint=raw.get("source_probability_fingerprint"),
        plans=dict(raw.get("plans", {})),
        generated_at=raw.get("generated_at"),
        generator_version=raw.get("generator_version"),
    )
