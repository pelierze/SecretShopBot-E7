"""State-machine shell connecting policy, recognition and input adapters."""

from __future__ import annotations

from ...models import EventAction, EventState, MoveOutcome
from ...ports import EventExecutor, EventObserver
from .policy import SummerEventPolicy
from .rules import SummerEventRules


class SummerEventBot:
    def __init__(
        self,
        state: EventState,
        policy: SummerEventPolicy,
        rules: SummerEventRules,
        observer: EventObserver,
        executor: EventExecutor,
    ):
        self.state = state
        self.policy = policy
        self.rules = rules
        self.observer = observer
        self.executor = executor

    def step(self) -> EventState:
        self.state = self.observer.observe(self.state)
        action = self.policy.choose_action(self.state)
        if action is EventAction.STOP:
            self.state.active = False
            return self.state

        self.rules.validate_action(self.state, action)
        self.executor.execute(action)
        outcome = (
            MoveOutcome.SUCCESS
            if action is EventAction.SUPER_DASH
            else self.observer.observe_outcome(action)
        )
        return self.rules.apply(self.state, action, outcome)
