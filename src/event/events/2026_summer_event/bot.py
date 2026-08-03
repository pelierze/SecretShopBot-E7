"""State-machine shell connecting policy, recognition and input adapters."""

from __future__ import annotations

import time

from ...models import EventAction, EventState, MoveOutcome
from ...ports import EventExecutor, EventObserver, EventOutcomePending, EventRecognitionError
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
        verification_attempts: int = 3,
        outcome_check_attempts: int = 30,
    ):
        self.state = state
        self.policy = policy
        self.rules = rules
        self.observer = observer
        self.executor = executor
        if verification_attempts <= 0:
            raise ValueError("Verification attempts must be positive")
        self.verification_attempts = verification_attempts
        if outcome_check_attempts <= 0:
            raise ValueError("Outcome check attempts must be positive")
        self.outcome_check_attempts = outcome_check_attempts
        self.stop_requested = False

    def run(self) -> dict:
        self.state.stats.start_time = getattr(self.state.stats, "start_time", None) or time.time()
        while self.state.active and not self.stop_requested:
            self.step()
        return self.get_stats()

    def set_user_action(self, action: str) -> None:
        if action == "stop":
            self.stop_requested = True
            self.state.active = False

    def get_stats(self) -> dict:
        stats = self.state.stats
        return {
            "position_m": self.state.position_m,
            "shield": self.state.items.shield,
            "leap": self.state.items.leap,
            "super_dash": self.state.items.super_dash,
            "drinks_used": stats.drinks_used,
            "rollbacks": stats.rollbacks,
            "attempts": sum(stats.attempts.values()),
            "successes": sum(stats.successes.values()),
            "failures": sum(stats.failures.values()),
            "rewards_100": stats.rewards.get(100, 0),
            "rewards_200": stats.rewards.get(200, 0),
            "rewards_300": stats.rewards.get(300, 0),
            "start_time": getattr(stats, "start_time", None),
        }

    def step(self) -> EventState:
        self.state = self._observe_state()
        action = self.policy.choose_action(self.state)
        if action is EventAction.STOP:
            self.state.active = False
            return self.state

        self.rules.validate_action(self.state, action)
        self.executor.execute(action)
        outcome = self._observe_outcome(action)
        return self.rules.apply(self.state, action, outcome)

    def _observe_outcome(self, action: EventAction) -> MoveOutcome:
        for _ in range(self.outcome_check_attempts):
            try:
                return self._verify(lambda: self.observer.observe_outcome(action), "이동 결과 인식")
            except EventOutcomePending:
                continue
        self.state.active = False
        raise EventRecognitionError(
            f"이동 후 M/스택 변화 또는 결과창을 {self.outcome_check_attempts}회 확인하지 못해 안전하게 중지했습니다."
        )

    def _observe_state(self) -> EventState:
        for _ in range(self.outcome_check_attempts):
            try:
                return self._verify(lambda: self.observer.observe(self.state), "이벤트 화면 인식")
            except EventOutcomePending:
                continue
        self.state.active = False
        raise EventRecognitionError(
            f"팝업 처리 후 기본 화면을 {self.outcome_check_attempts}회 확인하지 못해 안전하게 중지했습니다."
        )

    def _verify(self, operation, label):
        last_error = None
        for _ in range(self.verification_attempts):
            try:
                return operation()
            except EventRecognitionError as exc:
                last_error = exc
        self.state.active = False
        raise EventRecognitionError(
            f"{label}에 {self.verification_attempts}회 실패하여 안전하게 중지했습니다: {last_error}"
        ) from last_error
