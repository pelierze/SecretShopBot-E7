"""Configuration loading for the 2026 summer event."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from .derived_probability import derive_linear_probabilities
from .probability_data import ProbabilityDataset, load_probability_data


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
    probability_data_file: str = "probability_data.json"
    generated_policy_file: str = "generated_policy.json"
    unknown_probability_policy: str = "interpolate_bounded_linear"
    policy_mode: str = "offline_with_runtime_adaptation"
    data_sources: Dict[str, Optional[str]] = field(
        default_factory=lambda: {
            "bundled": "probability_data.json",
            "personal": "event_data/2026_summer_event/personal_probability_data.json",
        }
    )

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
        if self.unknown_probability_policy not in ("require_explicit", "interpolate_bounded_linear"):
            raise ValueError(f"Unsupported unknown probability policy: {self.unknown_probability_policy}")
        if self.policy_mode != "offline_with_runtime_adaptation":
            raise ValueError(f"Unsupported policy mode: {self.policy_mode}")


def load_config(path: Path) -> SummerEventConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    config = SummerEventConfig(
        success_probabilities={int(key): float(value) for key, value in raw.get("success_probabilities", {}).items()},
        reward_weights={int(key): float(value) for key, value in raw.get("reward_weights", {}).items()},
        reward_tiles=tuple(int(value) for value in raw.get("reward_tiles", (100, 200, 300, 350))),
        finish_m=int(raw.get("finish_m", 400)),
        ends_at=raw.get("ends_at"),
        timezone=raw.get("timezone"),
        probability_data_file=str(raw.get("probability_data_file", "probability_data.json")),
        generated_policy_file=str(raw.get("generated_policy_file", "generated_policy.json")),
        unknown_probability_policy=str(raw.get("unknown_probability_policy", "interpolate_bounded_linear")),
        policy_mode=str(raw.get("policy_mode", "offline_with_runtime_adaptation")),
        data_sources=dict(
            raw.get("data_sources")
            or {
                "bundled": "probability_data.json",
                "personal": "event_data/2026_summer_event/personal_probability_data.json",
            }
        ),
    )
    config.validate()
    return config


def load_event_bundle(config_path: Path) -> Tuple[SummerEventConfig, ProbabilityDataset]:
    """Load config and its sparse probability data using relative paths."""
    config_path = Path(config_path)
    config = load_config(config_path)
    dataset = load_probability_data(config_path.parent / config.probability_data_file)
    probabilities = dataset.probabilities
    if config.unknown_probability_policy == "interpolate_bounded_linear":
        probabilities = {
            position: probability.success_probability
            for position, probability in derive_linear_probabilities(
                dataset,
                end_m=config.finish_m - 10,
            ).items()
        }
    merged = SummerEventConfig(
        success_probabilities=probabilities,
        reward_weights=config.reward_weights,
        reward_tiles=config.reward_tiles,
        finish_m=config.finish_m,
        ends_at=config.ends_at,
        timezone=config.timezone,
        probability_data_file=config.probability_data_file,
        generated_policy_file=config.generated_policy_file,
        unknown_probability_policy=config.unknown_probability_policy,
        policy_mode=config.policy_mode,
        data_sources=config.data_sources,
    )
    merged.validate()
    return merged, dataset
