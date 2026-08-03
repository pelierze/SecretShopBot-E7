"""Replaceable action policy for the 2026 summer event."""

from __future__ import annotations

import logging

from ...models import EventAction, EventPlan, EventState
from .config import SummerEventConfig
from .rules import SummerEventRules


logger = logging.getLogger(__name__)


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
        if not state.active or self.config.has_ended() or state.position_m >= self.config.finish_m:
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


class PlannedSummerEventPolicy:
    """Use exact dynamic planning from the currently observed runtime state."""

    def __init__(self, config: SummerEventConfig, planner, adaptive_model=None):
        self.config = config
        self.planner = planner
        self._cache = {}
        self._prepared = False
        self.adaptive_model = adaptive_model

    def prepare(self, state: EventState) -> None:
        if self._prepared:
            return
        targets = {
            EventPlan.TARGET_100M: (
                EventPlan.TARGET_100M,
                EventPlan.TARGET_200M,
                EventPlan.TARGET_300M,
            ),
            EventPlan.TARGET_200M: (EventPlan.TARGET_200M, EventPlan.TARGET_300M),
            EventPlan.TARGET_300M: (EventPlan.TARGET_300M,),
            EventPlan.TARGET_500M: (EventPlan.TARGET_500M,),
        }[state.plan]
        state_key = self.planner.state_key(
            state.position_m,
            state.items.shield,
            state.items.leap,
            state.items.super_dash,
        )
        for target_plan in targets:
            self._cache[target_plan] = self.planner.build_plan(
                target_plan,
                initial_state=state_key,
            )
        self._prepared = True
        observations = self.adaptive_model.total_observations if self.adaptive_model else 0
        logger.info(
            "🧭 이벤트 경로 업데이트 완료: 시작 시 누적 관측 %s건 반영, 준비 플랜 %s",
            observations,
            ", ".join(plan.value for plan in targets),
        )

    def choose_action(self, state: EventState) -> EventAction:
        if not state.active or self.config.has_ended():
            return EventAction.STOP
        if state.plan is EventPlan.TARGET_500M:
            if state.position_m >= 500:
                return EventAction.STOP
            return self._planned_action(state, EventPlan.TARGET_500M)
        if state.position_m >= 300:
            return self._choose_best_effort_action(state)
        target_plan = self._next_target_plan(state)
        return self._planned_action(state, target_plan)

    def _planned_action(self, state: EventState, target_plan: EventPlan) -> EventAction:
        if not self._prepared:
            self.prepare(state)
        state_key = self.planner.state_key(
            state.position_m,
            state.items.shield,
            state.items.leap,
            state.items.super_dash,
        )
        plan = self._cache[target_plan]
        try:
            return plan.actions[state_key]
        except KeyError:
            logger.warning("사전 계산 경로에 없는 상태입니다. 실시간 재계산 없이 안전 우선 행동을 사용합니다: %s", state_key)
            return self._choose_best_effort_action(state)

    def observe_outcome(
        self,
        position_m: int,
        probability_tile_m: int,
        action: EventAction,
        outcome,
    ) -> None:
        # Runtime observations are persisted by the recorder and applied only
        # once when the next event session starts.
        return None

    def observe_displayed_probability(self, position_m: int, probability: float) -> bool:
        return False

    @staticmethod
    def _choose_best_effort_action(state: EventState) -> EventAction:
        """Continue beyond the planned target using the observed inventory.

        Probability observations end at 290M, so post-300M actions deliberately
        avoid invented probability estimates. Guaranteed movement is preferred,
        followed by protection that cannot end the run, then the remaining leap.
        """
        if state.items.super_dash > 0:
            return EventAction.SUPER_DASH
        if state.items.shield > 0:
            return EventAction.SHIELD
        if state.items.leap > 0:
            return EventAction.LEAP
        return EventAction.BASIC

    @staticmethod
    def _next_target_plan(state: EventState) -> EventPlan:
        if state.plan is EventPlan.TARGET_300M:
            return EventPlan.TARGET_300M
        if state.plan is EventPlan.TARGET_200M:
            return EventPlan.TARGET_200M if state.position_m < 200 else EventPlan.TARGET_300M
        if state.position_m < 100:
            return EventPlan.TARGET_100M
        if state.position_m < 200:
            return EventPlan.TARGET_200M
        return EventPlan.TARGET_300M
