"""Derive missing tile probabilities without modifying source observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .probability_data import ProbabilityDataset


@dataclass(frozen=True)
class DerivedProbability:
    position_m: int
    success_probability: float
    derived: bool
    lower_source_m: Optional[int] = None
    upper_source_m: Optional[int] = None


def derive_linear_probabilities(
    dataset: ProbabilityDataset,
    start_m: int = 0,
    end_m: int = 390,
    step_m: int = 10,
) -> Dict[int, DerivedProbability]:
    """Fill only gaps bounded by known tiles using piecewise-linear interpolation."""
    if step_m <= 0 or start_m < 0 or end_m < start_m:
        raise ValueError("Invalid probability range")

    known_positions = sorted(dataset.tiles)
    result: Dict[int, DerivedProbability] = {}
    for position in range(start_m, end_m + 1, step_m):
        if position in dataset.tiles:
            result[position] = DerivedProbability(
                position_m=position,
                success_probability=dataset.tiles[position].success_probability,
                derived=False,
                lower_source_m=position,
                upper_source_m=position,
            )
            continue

        lower = _nearest_lower(known_positions, position)
        upper = _nearest_upper(known_positions, position)
        if lower is None or upper is None:
            continue
        lower_probability = dataset.tiles[lower].success_probability
        upper_probability = dataset.tiles[upper].success_probability
        ratio = (position - lower) / (upper - lower)
        result[position] = DerivedProbability(
            position_m=position,
            success_probability=lower_probability + (upper_probability - lower_probability) * ratio,
            derived=True,
            lower_source_m=lower,
            upper_source_m=upper,
        )
    return result


def _nearest_lower(positions, target):
    return next((position for position in reversed(positions) if position < target), None)


def _nearest_upper(positions, target):
    return next((position for position in positions if position > target), None)
