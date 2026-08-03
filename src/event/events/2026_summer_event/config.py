"""Configuration loading for the 2026 summer event."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class SummerEventConfig:
    success_probabilities: Dict[int, float] = field(default_factory=dict)
    reward_weights: Dict[int, float] = field(
        # Ordering-only placeholders until relative reward values are provided.
        default_factory=lambda: {100: 1.0, 200: 2.0, 300: 3.0, 350: 4.0}
    )
    reward_tiles: tuple = (100, 200, 300, 350)
    finish_m: int = 400
    ends_at: Optional[str] = None
    timezone: Optional[str] = None

    def validate(self) -> None:
        for position, probability in self.success_probabilities.items():
            if position < 0 or position % 10:
                raise ValueError(f"Position must be a non-negative 10M tile: {position}")
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"Probability must be between 0 and 1: {probability}")
        if tuple(sorted(self.reward_tiles)) != tuple(self.reward_tiles):
            raise ValueError("Reward tiles must be sorted")
        if self.finish_m <= self.reward_tiles[-1]:
            raise ValueError("Finish position must be beyond the final reward tile")


def load_config(path: Path) -> SummerEventConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    config = SummerEventConfig(
        success_probabilities={int(key): float(value) for key, value in raw.get("success_probabilities", {}).items()},
        reward_weights={int(key): float(value) for key, value in raw.get("reward_weights", {}).items()},
        reward_tiles=tuple(int(value) for value in raw.get("reward_tiles", (100, 200, 300, 350))),
        finish_m=int(raw.get("finish_m", 400)),
        ends_at=raw.get("ends_at"),
        timezone=raw.get("timezone"),
    )
    config.validate()
    return config
