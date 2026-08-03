"""Pure movement and reward rules for the 2026 summer event."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from ...models import EventAction, EventState, ItemInventory, MoveOutcome


class SummerEventRules:
    MOVE_DISTANCE = {
        EventAction.BASIC: 10,
        EventAction.SHIELD: 10,
        EventAction.LEAP: 30,
        EventAction.SUPER_DASH: 30,
    }
    DRINK_COST = {
        EventAction.BASIC: 1,
        EventAction.SHIELD: 1,
        EventAction.LEAP: 1,
        EventAction.SUPER_DASH: 3,
    }

    DEFAULT_ITEM_RECHARGES = {
        100: {"shield": 2, "leap": 1},
        150: {"super_dash": 1},
        200: {"shield": 2, "leap": 1},
        300: {"shield": 2, "leap": 1, "super_dash": 1},
    }
    DEFAULT_ITEM_MAX_STACKS = {"shield": 4, "leap": 2, "super_dash": 2}
    DEFAULT_INITIAL_ITEM_STACKS = {"shield": 2, "leap": 1, "super_dash": 2}

    def __init__(
        self,
        reward_tiles: Iterable[int] = (100, 200, 300, 350, 400),
        finish_m: int = 400,
        item_recharges: Optional[Dict[int, Dict[str, int]]] = None,
        item_max_stacks: Optional[Dict[str, int]] = None,
        initial_item_stacks: Optional[Dict[str, int]] = None,
        reset_items_after_failure: bool = True,
    ):
        self.reward_tiles = tuple(sorted(reward_tiles))
        self.finish_m = finish_m
        self.item_recharges = item_recharges or self.DEFAULT_ITEM_RECHARGES
        self.item_max_stacks = item_max_stacks or self.DEFAULT_ITEM_MAX_STACKS
        self.initial_item_stacks = initial_item_stacks or self.DEFAULT_INITIAL_ITEM_STACKS
        self.reset_items_after_failure = reset_items_after_failure

    def validate_action(self, state: EventState, action: EventAction) -> None:
        if not state.active:
            raise ValueError("Event is not active")
        if action is EventAction.STOP:
            return
        if action is EventAction.SHIELD and state.items.shield <= 0:
            raise ValueError("No shield stacks available")
        if action is EventAction.LEAP and state.items.leap <= 0:
            raise ValueError("No leap stacks available")
        if action is EventAction.SUPER_DASH and state.items.super_dash <= 0:
            raise ValueError("No super dash stacks available")

    def apply(self, state: EventState, action: EventAction, outcome: MoveOutcome) -> EventState:
        self.validate_action(state, action)
        if action is EventAction.STOP:
            state.active = False
            return state
        if action is EventAction.SUPER_DASH and outcome is MoveOutcome.FAILURE:
            raise ValueError("Super dash cannot fail")

        old_position = state.position_m
        state.stats.increment(state.stats.attempts, action)
        state.stats.drinks_used += self.DRINK_COST[action]
        self._consume_item(state, action)

        if outcome is MoveOutcome.SUCCESS:
            state.stats.increment(state.stats.successes, action)
            state.position_m = old_position + self.MOVE_DISTANCE[action]
            crossed = self.crossed_rewards(old_position, state.position_m)
            for tile in crossed:
                state.stats.increment(state.stats.rewards, tile)
                state.collected_reward_tiles.add(tile)
            self._apply_crossed_recharges(state, old_position, state.position_m)
        else:
            state.stats.increment(state.stats.failures, action)
            if action is not EventAction.SHIELD:
                state.position_m = 0
                state.stats.rollbacks += 1
                state.plan_success_recorded = False
                if self.reset_items_after_failure:
                    state.items = ItemInventory(**self.initial_item_stacks)
        return state

    def crossed_rewards(self, start_m: int, end_m: int) -> Tuple[int, ...]:
        return tuple(tile for tile in self.reward_tiles if start_m < tile <= end_m)

    def _apply_crossed_recharges(self, state: EventState, start_m: int, end_m: int) -> None:
        for position, recharges in sorted(self.item_recharges.items()):
            if not start_m < position <= end_m:
                continue
            for item, amount in recharges.items():
                current = getattr(state.items, item)
                setattr(state.items, item, min(self.item_max_stacks[item], current + amount))

    @staticmethod
    def probability_tile(position_m: int, action: EventAction) -> int:
        if action is EventAction.LEAP:
            return max(0, position_m - 10)
        return position_m

    @staticmethod
    def _consume_item(state: EventState, action: EventAction) -> None:
        if action is EventAction.SHIELD:
            state.items.shield -= 1
        elif action is EventAction.LEAP:
            state.items.leap -= 1
        elif action is EventAction.SUPER_DASH:
            state.items.super_dash -= 1
