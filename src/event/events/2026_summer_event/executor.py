"""ADB input sequence for the 2026 summer event."""

from __future__ import annotations

from typing import Protocol, Tuple

from ...models import EventAction
from ...ports import EventInputError
from .screen_layout import SummerEventScreenLayout


class TapDevice(Protocol):
    def tap(self, x: int, y: int, delay: float = 0.5) -> bool:
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
    ):
        self.adb = adb
        self.layout = layout
        self.screen_size = screen_size
        self.selection_delay = selection_delay
        self.action_delay = action_delay

    def execute(self, action: EventAction) -> None:
        if action is EventAction.STOP:
            return
        skill_tap = self.ACTION_TAPS.get(action)
        if skill_tap is not None:
            self._tap(skill_tap, self.selection_delay)
        self._tap("basic", self.action_delay)

    def _tap(self, point_name: str, delay: float) -> None:
        x, y = self.layout.scale_point(point_name, self.screen_size)
        if not self.adb.tap(x, y, delay=delay):
            raise EventInputError(f"{point_name} 입력에 실패했습니다: ({x}, {y})")
