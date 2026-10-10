"""ADB input sequence for the 2026 summer event."""

from __future__ import annotations

import logging
from typing import Optional, Protocol, Tuple

from ...models import EventAction
from ...ports import EventInputError
from .screen_layout import SummerEventScreenLayout


logger = logging.getLogger(__name__)


class TapDevice(Protocol):
    def tap(self, x: int, y: int, delay: float = 0.5) -> bool:
        ...


class SkillSelectionVerifier(Protocol):
    def is_skill_selected(self, action: EventAction) -> bool:
        """Return whether the requested skill button currently shows Cancel."""
        ...


class SummerEventExecutor:
    """Select an optional skill, then confirm the move with the run button."""

    ACTION_TAPS = {
        EventAction.SHIELD: "shield",
        EventAction.LEAP: "leap",
        EventAction.SUPER_DASH: "super_dash",
    }

    def __init__(
        self,
        adb: TapDevice,
        layout: SummerEventScreenLayout,
        screen_size: Tuple[int, int] = (1280, 720),
        selection_delay: float = 0.25,
        action_delay: float = 0.5,
        selection_verifier: Optional[SkillSelectionVerifier] = None,
        selection_attempts: int = 3,
    ):
        if selection_attempts <= 0:
            raise ValueError("Selection attempts must be positive")
        self.adb = adb
        self.layout = layout
        self.screen_size = screen_size
        self.selection_delay = selection_delay
        self.action_delay = action_delay
        self.selection_verifier = selection_verifier
        self.selection_attempts = selection_attempts

    def execute(self, action: EventAction) -> None:
        if action is EventAction.STOP:
            return
        skill_tap = self.ACTION_TAPS.get(action)
        if skill_tap is not None:
            if self.selection_verifier is None:
                raise EventInputError("스킬 Cancel 상태를 확인할 검증기가 없습니다.")
            for attempt in range(1, self.selection_attempts + 1):
                self._tap(skill_tap, self.selection_delay)
                if self.selection_verifier.is_skill_selected(action):
                    logger.info(
                        "✅ 이벤트 스킬 선택 확인: %s (Cancel OCR 93%% 이상, %s/%s)",
                        action.display_name,
                        attempt,
                        self.selection_attempts,
                    )
                    break
                logger.warning(
                    "이벤트 스킬 Cancel 상태를 확인하지 못해 선택을 재시도합니다: %s (%s/%s)",
                    action.display_name,
                    attempt,
                    self.selection_attempts,
                )
            else:
                raise EventInputError(
                    f"{action.display_name} 선택 후 Cancel 상태를 "
                    f"{self.selection_attempts}회 확인하지 못해 달리기를 실행하지 않았습니다."
                )
        self._tap("basic", self.action_delay)

    def _tap(self, point_name: str, delay: float) -> None:
        x, y = self.layout.scale_point(point_name, self.screen_size)
        if not self.adb.tap(x, y, delay=delay):
            raise EventInputError(f"{point_name} 입력에 실패했습니다: ({x}, {y})")
