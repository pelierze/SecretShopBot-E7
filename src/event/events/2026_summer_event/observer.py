"""Screenshot recognition for the 2026 summer event."""

from __future__ import annotations

import logging
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


logger = logging.getLogger(__name__)

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
    success_probability: Optional[float] = None


class SummerEventObserver:
    TEMPLATE_THRESHOLD = 0.82
    SKILL_SELECTION_THRESHOLD = 0.93
    SKILL_BUTTON_REGIONS = {
        EventAction.SHIELD: "shield_button",
        EventAction.LEAP: "leap_button",
        EventAction.SUPER_DASH: "super_dash_button",
    }

    def __init__(
        self,
        adb: ScreenshotDevice,
        layout: SummerEventScreenLayout,
        screenshot_path: Path,
        template_dir: Path,
        screen_size: Tuple[int, int] = (1280, 720),
        ocr_engine=None,
        confirmed_probabilities=None,
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
        self._lower_position_key = None
        self._lower_position_count = 0
        self.last_observed_success_probability: Optional[float] = None
        self.last_template_similarities = {"result": 0.0, "reward": 0.0}
        self.confirmed_probabilities = dict(confirmed_probabilities or {})

    def set_confirmed_probability(self, position_m: int, probability: float) -> None:
        self.confirmed_probabilities[int(position_m)] = float(probability)

    def is_skill_selected(self, action: EventAction) -> bool:
        """Capture the skill button and verify that it changed to Cancel."""
        region_name = self.SKILL_BUTTON_REGIONS.get(action)
        if region_name is None or self.ocr_engine is None:
            return False
        self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.adb.screenshot(str(self.screenshot_path)):
            logger.warning("스킬 Cancel 상태 확인용 스크린샷 캡처에 실패했습니다.")
            return False
        frame = self._read_image(self.screenshot_path)
        return self.analyze_skill_selection(frame, action)

    def analyze_skill_selection(self, frame: np.ndarray, action: EventAction) -> bool:
        region_name = self.SKILL_BUTTON_REGIONS.get(action)
        if region_name is None or self.ocr_engine is None or frame is None or frame.size == 0:
            return False
        crop = self._crop(frame, region_name)
        enlarged = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        result, _ = self.ocr_engine(enlarged, use_cls=False)
        for item in [] if not result else result:
            text = re.sub(r"[^a-z]", "", str(item[1]).lower())
            confidence = float(item[2])
            if "cancel" in text and confidence >= self.SKILL_SELECTION_THRESHOLD:
                return True
        return False

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
            raise EventRecognitionError(
                f"이벤트 기본 화면을 확인할 수 없습니다. "
                f"({self._template_similarity_summary()})"
            )
        previous_state.position_m = screen.position_m
        previous_state.items = screen.items
        self.last_observed_success_probability = screen.success_probability
        self._before_action = EventState(
            position_m=screen.position_m,
            plan=previous_state.plan,
            items=ItemInventory(**vars(screen.items)),
        )
        self._reset_lower_position_tracking()
        return previous_state

    def observe_outcome(self, action: EventAction) -> MoveOutcome:
        screen = self.capture_and_analyze()
        if screen.kind is EventScreenKind.REWARD_POPUP:
            self._tap("close_reward_popup")
            raise EventOutcomePending("보상 팝업 처리 후 이동 결과를 기다리는 중입니다.")
        if screen.kind is EventScreenKind.RESULT_POPUP:
            self._reset_lower_position_tracking()
            self._tap("confirm_result_popup")
            return MoveOutcome.FAILURE
        if screen.kind is not EventScreenKind.NORMAL or screen.position_m is None or screen.items is None:
            raise EventRecognitionError(
                f"이동 후 이벤트 화면을 확인할 수 없습니다. "
                f"({self._template_similarity_summary()})"
            )
        if self._before_action is None:
            raise EventRecognitionError("이동 전 기준 상태가 없습니다.")

        before = self._before_action
        if screen.position_m > before.position_m:
            self._reset_lower_position_tracking()
            return MoveOutcome.SUCCESS
        if screen.position_m < before.position_m:
            key = (action, before.position_m, screen.position_m)
            if key == self._lower_position_key:
                self._lower_position_count += 1
            else:
                self._lower_position_key = key
                self._lower_position_count = 1
            if (
                self._lower_position_count >= 3
                and action in (EventAction.BASIC, EventAction.LEAP)
            ):
                logger.warning(
                    "결과창을 놓쳤지만 현재 M 감소가 반복 확인되어 실패로 처리합니다: %sM -> %sM",
                    before.position_m,
                    screen.position_m,
                )
                self._reset_lower_position_tracking()
                return MoveOutcome.FAILURE
            raise EventOutcomePending("이동 애니메이션 중 현재 M 감소가 보여 재확인합니다.")
        if action is EventAction.SHIELD and screen.items.shield < before.items.shield:
            self._reset_lower_position_tracking()
            return MoveOutcome.FAILURE
        raise EventOutcomePending("현재 M과 스킬 스택의 확정 변화가 아직 없습니다.")

    def _reset_lower_position_tracking(self) -> None:
        self._lower_position_key = None
        self._lower_position_count = 0

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
        result_similarity = self._template_similarity(frame, self.result_template)
        reward_similarity = self._template_similarity(frame, self.reward_template)
        self.last_template_similarities = {
            "result": result_similarity,
            "reward": reward_similarity,
        }
        if result_similarity >= self.TEMPLATE_THRESHOLD:
            return ObservedEventScreen(EventScreenKind.RESULT_POPUP)
        if reward_similarity >= self.TEMPLATE_THRESHOLD:
            return ObservedEventScreen(EventScreenKind.REWARD_POPUP)
        try:
            position = self._recognize_position(frame)
            if position in self.confirmed_probabilities:
                success_probability = self.confirmed_probabilities[position]
            else:
                try:
                    success_probability = self._recognize_success_probability(frame)
                except EventRecognitionError:
                    success_probability = None
            items = ItemInventory(
                shield=self._count_stars(frame, "shield_stacks"),
                leap=self._count_stars(frame, "leap_stacks"),
                super_dash=self._count_stars(frame, "super_dash_stacks"),
            )
        except EventRecognitionError:
            return ObservedEventScreen(EventScreenKind.UNKNOWN)
        return ObservedEventScreen(
            EventScreenKind.NORMAL,
            position_m=position,
            items=items,
            success_probability=success_probability,
        )

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
                if position >= 0 and position % 10 == 0:
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

    def _recognize_success_probability(self, frame: np.ndarray) -> float:
        if self.ocr_engine is None:
            raise EventRecognitionError("성공 확률 OCR 엔진을 사용할 수 없습니다.")
        crop = self._crop(frame, "success_probability")
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        saturated = cv2.inRange(hsv, np.array([0, 80, 100]), np.array([179, 255, 255]))
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(saturated)
        digit_boxes = []
        for index in range(1, component_count):
            x, y, width, height, area = stats[index]
            if (
                20 <= x <= 130
                and 20 <= y <= 45
                and 20 <= width <= 55
                and 50 <= height <= 70
                and area >= 800
            ):
                digit_boxes.append((int(x), int(y), int(width), int(height)))
        digit_boxes.sort()
        if not 1 <= len(digit_boxes) <= 3:
            raise EventRecognitionError("성공 확률 숫자 영역을 분리하지 못했습니다.")

        if len(digit_boxes) == 3 and digit_boxes[0][2] < digit_boxes[1][2]:
            value = 100
        else:
            digits = []
            for x, y, width, height in digit_boxes:
                digit_crop = crop[y:y + height, x:x + width]
                recognized = self._recognize_single_digit(digit_crop)
                if recognized is None:
                    digits = []
                    break
                digits.append(recognized)
            value = (
                int("".join(digits))
                if digits
                else self._recognize_probability_from_full_crop(crop, len(digit_boxes))
            )
        if not 0 <= value <= 100:
            raise EventRecognitionError(f"성공 확률 OCR 값이 범위를 벗어났습니다: {value}")
        return value / 100.0

    def _recognize_single_digit(self, crop: np.ndarray) -> Optional[str]:
        candidates = []
        for padding in (10, 20):
            padded = cv2.copyMakeBorder(
                crop,
                padding,
                padding,
                padding,
                padding,
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            )
            enlarged = cv2.resize(padded, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            for image in (enlarged, cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)):
                result, _ = self.ocr_engine(image, use_cls=False)
                for item in result or []:
                    text = str(item[1]).strip().replace("O", "0").replace("o", "0")
                    confidence = float(item[2])
                    match = re.fullmatch(r"(\d)", text)
                    if match and confidence >= 0.65:
                        candidates.append((confidence, match.group(1)))
        return max(candidates)[1] if candidates else None

    def _recognize_probability_from_full_crop(self, crop: np.ndarray, digit_count: int) -> int:
        result, _ = self.ocr_engine(crop, use_cls=False)
        pieces = []
        for item in result or []:
            text = str(item[1]).replace("O", "0").replace("o", "0")
            pieces.extend(re.findall(r"\d", text))
        if len(pieces) != digit_count:
            raise EventRecognitionError("성공 확률 숫자를 OCR로 인식하지 못했습니다.")
        return int("".join(pieces))

    def _crop(self, frame: np.ndarray, region_name: str) -> np.ndarray:
        x, y, width, height = self.layout.scale_box(region_name, self.screen_size)
        return frame[y:y + height, x:x + width]

    @staticmethod
    def _template_similarity(frame: np.ndarray, template: np.ndarray) -> float:
        if template is None or frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
            return 0.0
        return float(cv2.minMaxLoc(cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED))[1])

    def _template_similarity_summary(self) -> str:
        return (
            f"결과 팝업 유사도 "
            f"{self.last_template_similarities.get('result', 0.0):.3f}, "
            f"보상 팝업 유사도 "
            f"{self.last_template_similarities.get('reward', 0.0):.3f}"
        )

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
