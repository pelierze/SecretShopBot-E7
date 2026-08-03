"""Configuration loading for the 2026 summer event."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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
    item_recharges: Dict[int, Dict[str, int]] = field(
        default_factory=lambda: {
            100: {"shield": 2, "leap": 1},
            150: {"super_dash": 1},
            200: {"shield": 2, "leap": 1},
            300: {"shield": 2, "leap": 1, "super_dash": 1},
        }
    )
    item_max_stacks: Dict[str, int] = field(
        default_factory=lambda: {"shield": 4, "leap": 2, "super_dash": 2}
    )
    initial_item_stacks: Dict[str, int] = field(
        default_factory=lambda: {"shield": 2, "leap": 1, "super_dash": 2}
    )
    reset_items_after_failure: bool = True
    verification_attempts: int = 3
    outcome_check_attempts: int = 30
    finish_m: int = 400
    ends_at: Optional[str] = None
    timezone: Optional[str] = None
    probability_data_file: str = "probability_data.json"
    generated_policy_file: str = "generated_policy.json"
    screen_layout_file: str = "screen_layout.json"
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
        valid_items = {"shield", "leap", "super_dash"}
        if set(self.item_max_stacks) != valid_items:
            raise ValueError("Item max stacks must define shield, leap, and super_dash")
        if set(self.initial_item_stacks) != valid_items:
            raise ValueError("Initial item stacks must define shield, leap, and super_dash")
        for item in valid_items:
            if not 0 <= self.initial_item_stacks[item] <= self.item_max_stacks[item]:
                raise ValueError(f"Invalid initial stack for {item}")
        for position, recharges in self.item_recharges.items():
            if position <= 0 or position % 10:
                raise ValueError(f"Recharge position must be a positive 10M tile: {position}")
            if not set(recharges).issubset(valid_items):
                raise ValueError(f"Unknown recharge item at {position}M")
            if any(amount < 0 for amount in recharges.values()):
                raise ValueError(f"Recharge amount cannot be negative at {position}M")
        if self.verification_attempts <= 0:
            raise ValueError("Verification attempts must be positive")
        if self.outcome_check_attempts <= 0:
            raise ValueError("Outcome check attempts must be positive")
        if self.unknown_probability_policy not in ("require_explicit", "interpolate_bounded_linear"):
            raise ValueError(f"Unsupported unknown probability policy: {self.unknown_probability_policy}")
        if self.policy_mode != "offline_with_runtime_adaptation":
            raise ValueError(f"Unsupported policy mode: {self.policy_mode}")
        if self.ends_at is not None and datetime.fromisoformat(self.ends_at).tzinfo is None:
            raise ValueError("Event end time must include a timezone offset")

    def has_ended(self, now: Optional[datetime] = None) -> bool:
        if self.ends_at is None:
            return False
        end_time = datetime.fromisoformat(self.ends_at)
        current_time = now or datetime.now(end_time.tzinfo)
        if current_time.tzinfo is None:
            raise ValueError("Current time must be timezone-aware")
        return current_time >= end_time


def load_config(path: Path) -> SummerEventConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    config = SummerEventConfig(
        success_probabilities={int(key): float(value) for key, value in raw.get("success_probabilities", {}).items()},
        reward_weights={int(key): float(value) for key, value in raw.get("reward_weights", {}).items()},
        reward_tiles=tuple(int(value) for value in raw.get("reward_tiles", (100, 200, 300, 350))),
        item_recharges={
            int(position): {str(item): int(amount) for item, amount in recharges.items()}
            for position, recharges in raw.get("item_recharges", {}).items()
        } or SummerEventConfig().item_recharges,
        item_max_stacks={
            str(item): int(amount) for item, amount in raw.get("item_max_stacks", {}).items()
        } or SummerEventConfig().item_max_stacks,
        initial_item_stacks={
            str(item): int(amount) for item, amount in raw.get("initial_item_stacks", {}).items()
        } or SummerEventConfig().initial_item_stacks,
        reset_items_after_failure=bool(raw.get("reset_items_after_failure", True)),
        verification_attempts=int(raw.get("verification_attempts", 3)),
        outcome_check_attempts=int(raw.get("outcome_check_attempts", 30)),
        finish_m=int(raw.get("finish_m", 400)),
        ends_at=raw.get("ends_at"),
        timezone=raw.get("timezone"),
        probability_data_file=str(raw.get("probability_data_file", "probability_data.json")),
        generated_policy_file=str(raw.get("generated_policy_file", "generated_policy.json")),
        screen_layout_file=str(raw.get("screen_layout_file", "screen_layout.json")),
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
        item_recharges=config.item_recharges,
        item_max_stacks=config.item_max_stacks,
        initial_item_stacks=config.initial_item_stacks,
        reset_items_after_failure=config.reset_items_after_failure,
        verification_attempts=config.verification_attempts,
        outcome_check_attempts=config.outcome_check_attempts,
        finish_m=config.finish_m,
        ends_at=config.ends_at,
        timezone=config.timezone,
        probability_data_file=config.probability_data_file,
        generated_policy_file=config.generated_policy_file,
        screen_layout_file=config.screen_layout_file,
        unknown_probability_policy=config.unknown_probability_policy,
        policy_mode=config.policy_mode,
        data_sources=config.data_sources,
    )
    merged.validate()
    return merged, dataset
