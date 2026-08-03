"""Exact target-reach planning and reproducible simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional, Tuple

from ...models import EventAction, EventPlan
from .config import SummerEventConfig
from .policy import MissingProbabilityData
from .rules import SummerEventRules


PlannerState = Tuple[int, int, int, int]


@dataclass(frozen=True)
class TargetPlan:
    target_m: int
    success_probability: float
    expected_drinks: float
    actions: Dict[PlannerState, EventAction]


@dataclass(frozen=True)
class SimulationResult:
    target_m: int
    trials: int
    successes: int
    success_rate: float
    average_drinks: float


class SummerEventPlanner:
    PLAN_TARGETS = {
        EventPlan.TARGET_100M: 100,
        EventPlan.TARGET_200M: 200,
        EventPlan.TARGET_300M: 300,
    }

    def __init__(self, config: SummerEventConfig, rules: Optional[SummerEventRules] = None):
        self.config = config
        self.rules = rules or SummerEventRules(
            reward_tiles=config.reward_tiles,
            finish_m=config.finish_m,
            item_recharges=config.item_recharges,
            item_max_stacks=config.item_max_stacks,
            initial_item_stacks=config.initial_item_stacks,
            reset_items_after_failure=config.reset_items_after_failure,
        )

    def build_plan(self, plan: EventPlan, initial_state: Optional[PlannerState] = None) -> TargetPlan:
        target_m = self.PLAN_TARGETS[plan]
        decisions: Dict[PlannerState, EventAction] = {}

        @lru_cache(maxsize=None)
        def solve(state: PlannerState) -> Tuple[float, float]:
            position, shield, leap, super_dash = state
            if position >= target_m:
                return 1.0, 0.0

            candidates = [EventAction.BASIC]
            if shield:
                candidates.append(EventAction.SHIELD)
            if leap:
                candidates.append(EventAction.LEAP)
            if super_dash:
                candidates.append(EventAction.SUPER_DASH)

            best_probability = -1.0
            best_drinks = float("inf")
            best_action = EventAction.BASIC
            for action in candidates:
                probability = self._action_probability(position, action)
                success_state = self._success_state(state, action)
                success_value, success_drinks = solve(success_state)
                failure_value, failure_drinks = 0.0, 0.0
                if action is EventAction.SHIELD:
                    failure_value, failure_drinks = solve((position, shield - 1, leap, super_dash))
                value = probability * success_value + (1.0 - probability) * failure_value
                drinks = (
                    self.rules.DRINK_COST[action]
                    + probability * success_drinks
                    + (1.0 - probability) * failure_drinks
                )
                if value > best_probability + 1e-12 or (
                    abs(value - best_probability) <= 1e-12 and drinks < best_drinks
                ):
                    best_probability = value
                    best_drinks = drinks
                    best_action = action

            decisions[state] = best_action
            return best_probability, best_drinks

        initial = initial_state or self._initial_state()
        probability, expected_drinks = solve(initial)
        return TargetPlan(
            target_m=target_m,
            success_probability=probability,
            expected_drinks=expected_drinks,
            actions=decisions,
        )

    @staticmethod
    def state_key(position_m: int, shield: int, leap: int, super_dash: int) -> PlannerState:
        return position_m, shield, leap, super_dash

    def simulate(self, plan: TargetPlan, trials: int = 100_000, seed: int = 20260803) -> SimulationResult:
        if trials <= 0:
            raise ValueError("Trials must be positive")
        rng = random.Random(seed)
        successes = 0
        total_drinks = 0
        for _ in range(trials):
            state = self._initial_state()
            while state[0] < plan.target_m:
                action = plan.actions[state]
                total_drinks += self.rules.DRINK_COST[action]
                probability = self._action_probability(state[0], action)
                if rng.random() < probability:
                    state = self._success_state(state, action)
                elif action is EventAction.SHIELD:
                    state = (state[0], state[1] - 1, state[2], state[3])
                else:
                    break
            if state[0] >= plan.target_m:
                successes += 1
        return SimulationResult(
            target_m=plan.target_m,
            trials=trials,
            successes=successes,
            success_rate=successes / trials,
            average_drinks=total_drinks / trials,
        )

    def _initial_state(self) -> PlannerState:
        stacks = self.config.initial_item_stacks
        return 0, stacks["shield"], stacks["leap"], stacks["super_dash"]

    def _action_probability(self, position: int, action: EventAction) -> float:
        if action is EventAction.SUPER_DASH:
            return 1.0
        probability_tile = self.rules.probability_tile(position, action)
        try:
            return self.config.success_probabilities[probability_tile]
        except KeyError as exc:
            raise MissingProbabilityData(f"Missing success probability for {probability_tile}M") from exc

    def _success_state(self, state: PlannerState, action: EventAction) -> PlannerState:
        position, shield, leap, super_dash = state
        if action is EventAction.SHIELD:
            shield -= 1
        elif action is EventAction.LEAP:
            leap -= 1
        elif action is EventAction.SUPER_DASH:
            super_dash -= 1

        end_position = min(self.config.finish_m, position + self.rules.MOVE_DISTANCE[action])
        inventory = {"shield": shield, "leap": leap, "super_dash": super_dash}
        for recharge_position, recharges in sorted(self.config.item_recharges.items()):
            if not position < recharge_position <= end_position:
                continue
            for item, amount in recharges.items():
                inventory[item] = min(self.config.item_max_stacks[item], inventory[item] + amount)
        return end_position, inventory["shield"], inventory["leap"], inventory["super_dash"]
