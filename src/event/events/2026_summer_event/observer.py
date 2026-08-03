"""Screenshot recognition for the 2026 summer event."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, Tuple

import cv2
import numpy as np

from ...models import EventAction, EventState, ItemInventory, MoveOutcome
from ...ports import EventOutcomePending, EventRecognitionError
from .screen_layout import SummerEventScreenLayout

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - handled as a startup error in packaged builds
    RapidOCR = None


class ScreenshotDevice(Protocol):
    def screenshot(self, save_path: str) -> bool:
        ...

    def tap(self, x: int, y: int, delay: float = 0.5) -> bool:
        ...


class EventScreenKind(str, Enum):
    NORMAL = "normal"
    REWARD_POPUP = "reward_popup"
    RESULT_POPUP = "result_popup"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ObservedEventScreen:
    kind: EventScreenKind
    position_m: Optional[int] = None
    items: Optional[ItemInventory] = None


class SummerEventObserver:
    TEMPLATE_THRESHOLD = 0.82

    def __init__(
        self,
        adb: ScreenshotDevice,
        layout: SummerEventScreenLayout,
        screenshot_path: Path,
        template_dir: Path,
        screen_size: Tuple[int, int] = (1280, 720),
        ocr_engine=None,
    ):
        self.adb = adb
        self.layout = layout
        self.screenshot_path = Path(screenshot_path)
        self.template_dir = Path(template_dir)
        self.screen_size = screen_size
        if ocr_engine is not None:
            self.ocr_engine = ocr_engine
        elif RapidOCR is not None:
            self.ocr_engine = RapidOCR()
        else:
            self.ocr_engine = None
        self.reward_template = self._read_image(self.template_dir / "reward_popup_title.png")
        self.result_template = self._read_image(self.template_dir / "result_popup_title.png")
        self._before_action: Optional[EventState] = None

    def observe(self, previous_state: EventState) -> EventState:
        screen = self.capture_and_analyze()
        if screen.kind is EventScreenKind.REWARD_POPUP:
            self._tap("close_reward_popup")
            raise EventOutcomePending("보상 팝업을 닫고 화면 변화를 기다리는 중입니다.")
        if screen.kind is EventScreenKind.RESULT_POPUP:
            self._tap("confirm_result_popup")
            previous_state.position_m = 0
            previous_state.items = ItemInventory()
            self._before_action = None
            raise EventOutcomePending("결과창을 닫고 0M 화면을 기다리는 중입니다.")
        if screen.kind is not EventScreenKind.NORMAL or screen.position_m is None or screen.items is None:
            raise EventRecognitionError("이벤트 기본 화면을 확인할 수 없습니다.")
        previous_state.position_m = screen.position_m
        previous_state.items = screen.items
        self._before_action = EventState(
            position_m=screen.position_m,
            plan=previous_state.plan,
            items=ItemInventory(**vars(screen.items)),
        )
        return previous_state

    def observe_outcome(self, action: EventAction) -> MoveOutcome:
        screen = self.capture_and_analyze()
        if screen.kind is EventScreenKind.REWARD_POPUP:
            self._tap("close_reward_popup")
            raise EventOutcomePending("보상 팝업 처리 후 이동 결과를 기다리는 중입니다.")
        if screen.kind is EventScreenKind.RESULT_POPUP:
            return MoveOutcome.FAILURE
        if screen.kind is not EventScreenKind.NORMAL or screen.position_m is None or screen.items is None:
            raise EventRecognitionError("이동 후 이벤트 화면을 확인할 수 없습니다.")
        if self._before_action is None:
            raise EventRecognitionError("이동 전 기준 상태가 없습니다.")

        before = self._before_action
        if screen.position_m > before.position_m:
            return MoveOutcome.SUCCESS
        if screen.position_m < before.position_m:
            raise EventRecognitionError("결과창 확인 없이 현재 M이 감소했습니다.")
        if action is EventAction.SHIELD and screen.items.shield < before.items.shield:
            return MoveOutcome.FAILURE
        raise EventOutcomePending("현재 M과 스킬 스택의 확정 변화가 아직 없습니다.")

    def capture_and_analyze(self) -> ObservedEventScreen:
        self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.adb.screenshot(str(self.screenshot_path)):
            raise EventRecognitionError("ADB 스크린샷 캡처에 실패했습니다.")
        frame = self._read_image(self.screenshot_path)
        return self.analyze_frame(frame)

    def analyze_frame(self, frame: np.ndarray) -> ObservedEventScreen:
        if frame is None or frame.size == 0:
            return ObservedEventScreen(EventScreenKind.UNKNOWN)
        height, width = frame.shape[:2]
        if (width, height) != self.screen_size:
            self.screen_size = (width, height)
        if self._template_similarity(frame, self.result_template) >= self.TEMPLATE_THRESHOLD:
            return ObservedEventScreen(EventScreenKind.RESULT_POPUP)
        if self._template_similarity(frame, self.reward_template) >= self.TEMPLATE_THRESHOLD:
            return ObservedEventScreen(EventScreenKind.REWARD_POPUP)
        try:
            position = self._recognize_position(frame)
            items = ItemInventory(
                shield=self._count_stars(frame, "shield_stacks"),
                leap=self._count_stars(frame, "leap_stacks"),
                super_dash=self._count_stars(frame, "super_dash_stacks"),
            )
        except EventRecognitionError:
            return ObservedEventScreen(EventScreenKind.UNKNOWN)
        return ObservedEventScreen(EventScreenKind.NORMAL, position_m=position, items=items)

    def _recognize_position(self, frame: np.ndarray) -> int:
        if self.ocr_engine is None:
            raise EventRecognitionError("현재 M 인식을 위한 OCR 엔진을 사용할 수 없습니다.")
        crop = self._crop(frame, "current_node")
        enlarged = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        result, _ = self.ocr_engine(enlarged, use_cls=False)
        candidates = [] if not result else result
        for item in candidates:
            text = str(item[1]).replace(" ", "")
            confidence = float(item[2])
            match = re.search(r"(\d+)[mM]", text)
            if match and confidence >= 0.80:
                position = int(match.group(1))
                if 0 <= position <= 400 and position % 10 == 0:
                    return position
        raise EventRecognitionError("현재 노드의 M 숫자를 인식하지 못했습니다.")

    def _count_stars(self, frame: np.ndarray, region_name: str) -> int:
        crop = self._crop(frame, region_name)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, np.array([15, 120, 130]), np.array([45, 255, 255]))
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(yellow)
        stars = 0
        for index in range(1, component_count):
            area = stats[index, cv2.CC_STAT_AREA]
            component_width = stats[index, cv2.CC_STAT_WIDTH]
            component_height = stats[index, cv2.CC_STAT_HEIGHT]
            if 60 <= area <= 180 and 10 <= component_width <= 24 and 12 <= component_height <= 24:
                stars += 1
        return stars

    def _crop(self, frame: np.ndarray, region_name: str) -> np.ndarray:
        x, y, width, height = self.layout.scale_box(region_name, self.screen_size)
        return frame[y:y + height, x:x + width]

    @staticmethod
    def _template_similarity(frame: np.ndarray, template: np.ndarray) -> float:
        if template is None or frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
            return 0.0
        return float(cv2.minMaxLoc(cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED))[1])

    def _tap(self, point_name: str) -> None:
        x, y = self.layout.scale_point(point_name, self.screen_size)
        if not self.adb.tap(x, y, delay=0.2):
            raise EventRecognitionError(f"{point_name} 팝업 처리 입력에 실패했습니다.")

    @staticmethod
    def _read_image(path: Path) -> np.ndarray:
        data = np.fromfile(Path(path), dtype=np.uint8)
        if data.size == 0:
            raise EventRecognitionError(f"이미지를 읽을 수 없습니다: {path}")
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise EventRecognitionError(f"이미지를 디코딩할 수 없습니다: {path}")
        return image
