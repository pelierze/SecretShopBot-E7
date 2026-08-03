"""Replaceable action policy for the 2026 summer event."""

from __future__ import annotations

from ...models import EventAction, EventPlan, EventState
from .config import SummerEventConfig
from .rules import SummerEventRules


class MissingProbabilityData(RuntimeError):
    pass


class SummerEventPolicy:
    """Conservative scaffold; final optimization is added with event data."""

    PLAN_TARGETS = {
        EventPlan.TARGET_100M: 100,
        EventPlan.TARGET_200M: 200,
        EventPlan.TARGET_300M: 300,
    }

    def __init__(self, config: SummerEventConfig, rules: SummerEventRules):
        self.config = config
        self.rules = rules

    def choose_action(self, state: EventState) -> EventAction:
        if not state.active or state.position_m >= self.config.finish_m:
            return EventAction.STOP

        target = self._current_target(state)
        candidates = self._available_actions(state)
        scored = [(self._score(state, action, target), action) for action in candidates]
        return max(scored, key=lambda item: item[0])[1]

    def _current_target(self, state: EventState) -> int:
        plan_target = self.PLAN_TARGETS[state.plan]
        if state.position_m >= 350:
            return 400
        if state.position_m >= plan_target:
            return 350 if state.plan is EventPlan.TARGET_300M else plan_target
        return plan_target

    @staticmethod
    def _available_actions(state: EventState):
        actions = [EventAction.BASIC]
        if state.items.shield:
            actions.append(EventAction.SHIELD)
        if state.items.leap:
            actions.append(EventAction.LEAP)
        if state.items.super_dash:
            actions.append(EventAction.SUPER_DASH)
        return actions

    def _score(self, state: EventState, action: EventAction, target: int) -> float:
        if action is EventAction.SUPER_DASH:
            probability = 1.0
        else:
            tile = self.rules.probability_tile(state.position_m, action)
            try:
                probability = self.config.success_probabilities[tile]
            except KeyError as exc:
                raise MissingProbabilityData(f"Missing success probability for {tile}M") from exc

        distance = self.rules.MOVE_DISTANCE[action]
        drink_cost = self.rules.DRINK_COST[action]
        reaches_target = state.position_m < target <= state.position_m + distance
        target_bonus = 100.0 if reaches_target else 0.0
        shield_failure_value = (1.0 - probability) * 20.0 if action is EventAction.SHIELD else 0.0
        return target_bonus + shield_failure_value + (probability * distance / drink_cost)
