"""State-machine shell connecting policy, recognition and input adapters."""

from __future__ import annotations

import logging
import time

from ...models import EventAction, EventState, MoveOutcome
from ...ports import EventExecutor, EventObserver, EventOutcomePending, EventRecognitionError
from .policy import SummerEventPolicy
from .rules import SummerEventRules


logger = logging.getLogger(__name__)

ACTION_NAMES = {
    EventAction.SHIELD: "보호",
    EventAction.LEAP: "도움닫기",
    EventAction.SUPER_DASH: "슈퍼럭키",
}

PLAN_TARGETS = {
    "100m": 100,
    "200m": 200,
    "300m": 300,
    "500m": 500,
}


class SummerEventBot:
    VERIFICATION_RETRY_DELAY_SECONDS = 0.25

    def __init__(
        self,
        state: EventState,
        policy: SummerEventPolicy,
        rules: SummerEventRules,
        observer: EventObserver,
        executor: EventExecutor,
        verification_attempts: int = 3,
        outcome_check_attempts: int = 30,
        probability_recorder=None,
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
        self._state_initialized = False
        self.probability_recorder = probability_recorder

    def run(self) -> dict:
        self.state.stats.start_time = getattr(self.state.stats, "start_time", None) or time.time()
        self.initialize_state()
        prepare_policy = getattr(self.policy, "prepare", None)
        if prepare_policy is not None:
            prepare_policy(self.state)
        while self.state.active and not self.stop_requested:
            self.step()
        self.state.active = False
        return self.get_stats()

    def initialize_state(self) -> EventState:
        """Scan the live event screen before the policy chooses its first action."""
        if not self._state_initialized:
            self.state = self._observe_state()
            self._state_initialized = True
            displayed_probability = getattr(
                self.observer,
                "last_observed_success_probability",
                None,
            )
            record_displayed = getattr(
                self.probability_recorder,
                "record_displayed_probability",
                None,
            )
            if displayed_probability is not None and record_displayed is not None:
                if record_displayed(self.state.position_m, displayed_probability):
                    logger.info(
                        "✅ 신규 타일 OCR 확률 확정: %sM = %.2f%% (동일 관측 3회)",
                        self.state.position_m,
                        displayed_probability * 100,
                    )
                get_confirmed = getattr(
                    self.probability_recorder,
                    "confirmed_probability",
                    None,
                )
                confirmed = get_confirmed(self.state.position_m) if get_confirmed else None
                if confirmed is not None:
                    set_confirmed = getattr(self.observer, "set_confirmed_probability", None)
                    if set_confirmed is not None:
                        set_confirmed(self.state.position_m, confirmed)
            self._record_plan_success_if_reached()
        return self.state

    def set_user_action(self, action: str) -> None:
        if action == "stop":
            self.stop_requested = True

    def get_stats(self) -> dict:
        stats = self.state.stats
        return {
            "position_m": self.state.position_m,
            "shield": self.state.items.shield,
            "leap": self.state.items.leap,
            "super_dash": self.state.items.super_dash,
            "drinks_used": stats.drinks_used,
            "rollbacks": stats.rollbacks,
            "plan_successes": stats.plan_successes,
            "attempts": sum(stats.attempts.values()),
            "successes": sum(stats.successes.values()),
            "failures": sum(stats.failures.values()),
            "rewards_100": stats.rewards.get(100, 0),
            "rewards_200": stats.rewards.get(200, 0),
            "rewards_300": stats.rewards.get(300, 0),
            "rewards_350": stats.rewards.get(350, 0),
            "rewards_400": stats.rewards.get(400, 0),
            "rewards_500": stats.rewards.get(500, 0),
            "core_rewards_total": sum(stats.rewards.get(tile, 0) for tile in self.rules.reward_tiles),
            "start_time": getattr(stats, "start_time", None),
        }

    def step(self) -> EventState:
        self.initialize_state()
        if self.stop_requested:
            self.state.active = False
            return self.state
        action = self.policy.choose_action(self.state)
        if action is EventAction.STOP:
            self.state.active = False
            return self.state

        self.rules.validate_action(self.state, action)
        old_position = self.state.position_m
        if action in ACTION_NAMES:
            logger.info(
                "🎯 이벤트 아이템 사용: %s (현재 %sM, 사용 전 보유량: %s)",
                ACTION_NAMES[action],
                old_position,
                getattr(self.state.items, action.value),
            )
        self.executor.execute(action)
        outcome = self._observe_outcome(action)
        if action is EventAction.SUPER_DASH and outcome is MoveOutcome.FAILURE:
            self.state.active = False
            raise EventRecognitionError(
                "슈퍼럭키 Cancel 상태 확인 후 실패 결과창이 감지되어 안전하게 중지했습니다. "
                "입력 적용 또는 결과창 인식을 확인해주세요."
            )
        observation_tile = self.rules.observation_tile(old_position, action)
        if self.probability_recorder is not None:
            if self.probability_recorder.record(old_position, observation_tile, action, outcome):
                logger.info(
                    "📈 미등록 확률 표본 기록: %sM, %s, %s",
                    observation_tile,
                    ACTION_NAMES.get(action, "일반 달리기"),
                    "성공" if outcome is MoveOutcome.SUCCESS else "실패",
                )
        self.state = self.rules.apply(self.state, action, outcome)
        self._record_plan_success_if_reached()
        if outcome is MoveOutcome.SUCCESS:
            for reward_m in self.rules.crossed_rewards(old_position, self.state.position_m):
                logger.info("🏆 핵심 보상 구간 통과: %sM", reward_m)
        # The next decision must be based on a fresh scan rather than the
        # state predicted by the rules engine.
        self._state_initialized = False
        return self.state

    def _record_plan_success_if_reached(self) -> None:
        target_m = PLAN_TARGETS[self.state.plan.value]
        if self.state.position_m >= target_m and not self.state.plan_success_recorded:
            self.state.stats.plan_successes += 1
            self.state.plan_success_recorded = True
            logger.info("✅ 선택 플랜 성공: %sM 도달", target_m)

    def _observe_outcome(self, action: EventAction) -> MoveOutcome:
        last_error = None
        for _ in range(self.outcome_check_attempts):
            try:
                return self._verify(
                    lambda: self.observer.observe_outcome(action),
                    "이동 결과 인식",
                    deactivate_on_failure=False,
                )
            except EventOutcomePending:
                continue
            except EventRecognitionError as exc:
                last_error = exc
                continue
        self.state.active = False
        detail = f" 마지막 오류: {last_error}" if last_error is not None else ""
        raise EventRecognitionError(
            f"이동 후 M/스택 변화 또는 결과창을 {self.outcome_check_attempts}회 확인하지 못해 안전하게 중지했습니다.{detail}"
        )

    def _observe_state(self) -> EventState:
        last_error = None
        for _ in range(self.outcome_check_attempts):
            try:
                return self._verify(
                    lambda: self.observer.observe(self.state),
                    "이벤트 화면 인식",
                    deactivate_on_failure=False,
                )
            except EventOutcomePending:
                continue
            except EventRecognitionError as exc:
                last_error = exc
                continue
        self.state.active = False
        detail = f" 마지막 오류: {last_error}" if last_error is not None else ""
        raise EventRecognitionError(
            f"팝업 처리 후 기본 화면을 {self.outcome_check_attempts}회 확인하지 못해 안전하게 중지했습니다.{detail}"
        )

    def _verify(self, operation, label, deactivate_on_failure=True):
        last_error = None
        for attempt in range(self.verification_attempts):
            try:
                return operation()
            except EventRecognitionError as exc:
                last_error = exc
                if attempt + 1 < self.verification_attempts:
                    time.sleep(self.VERIFICATION_RETRY_DELAY_SECONDS)
        if deactivate_on_failure:
            self.state.active = False
            failure_action = "안전하게 중지했습니다"
        else:
            failure_action = "다음 확인 주기로 넘어갑니다"
        raise EventRecognitionError(
            f"{label}에 {self.verification_attempts}회 실패하여 {failure_action}: {last_error}"
        ) from last_error
