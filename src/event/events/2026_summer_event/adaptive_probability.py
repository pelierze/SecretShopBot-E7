"""Adaptive probability estimates for the 500M high-score plan."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Dict, Iterable

from ...models import EventAction, MoveOutcome


class AdaptiveProbabilityModel:
    """Seed unknown tiles and refine every tile with runtime observations."""

    def __init__(
        self,
        probabilities: Dict[int, float],
        observed_tiles: Iterable[int],
        end_m: int = 490,
        prior_strength: float = 5.0,
        observed_prior_strength: float = 20.0,
    ):
        self.observed_tiles = frozenset(int(tile) for tile in observed_tiles)
        self.prior_strength = float(prior_strength)
        self.observed_prior_strength = float(observed_prior_strength)
        self.probabilities = probabilities
        self._prior = dict(probabilities)
        self._displayed_probabilities = {}
        self._outcomes = defaultdict(lambda: [0, 0])
        self._seed_predictions(end_m)

    def observe(self, tile_m: int, action: EventAction, outcome: MoveOutcome) -> bool:
        if action is EventAction.SUPER_DASH:
            return False
        successes, attempts = self._outcomes[tile_m]
        attempts += 1
        successes += int(outcome is MoveOutcome.SUCCESS)
        self._outcomes[tile_m] = [successes, attempts]
        prior = self._prior[tile_m]
        strength = (
            self.observed_prior_strength
            if tile_m in self.observed_tiles
            else self.prior_strength
        )
        self.probabilities[tile_m] = (
            prior * strength + successes
        ) / (strength + attempts)
        return True

    def set_displayed_probability(self, tile_m: int, probability: float) -> bool:
        if tile_m in self.observed_tiles or not 0.0 <= probability <= 1.0:
            return False
        self._prior[tile_m] = probability
        self._displayed_probabilities[tile_m] = probability
        successes, attempts = self._outcomes[tile_m]
        self.probabilities[tile_m] = (
            probability * self.prior_strength + successes
        ) / (self.prior_strength + attempts)
        return True

    def displayed_probability(self, tile_m: int):
        return self._displayed_probabilities.get(tile_m)

    def observation_count(self, tile_m: int) -> int:
        return self._outcomes[tile_m][1]

    def _seed_predictions(self, end_m: int) -> None:
        source = dict(self.probabilities)
        for position in range(0, end_m + 1, 10):
            if position in self.probabilities:
                continue
            same_offset = [
                probability
                for tile, probability in sorted(source.items())
                if tile < 300 and tile % 100 == position % 100
            ]
            if same_offset:
                prediction = mean(same_offset[-2:])
            else:
                nearest = max(source, key=lambda tile: -abs(tile - position))
                prediction = source[nearest]
            self.probabilities[position] = prediction
            self._prior[position] = prediction
