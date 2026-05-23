"""
Penguin purchase automation.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .adb_controller import ADBController
from .image_matcher import read_image

logger = logging.getLogger(__name__)


def get_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class PenguinBot:
    """Automates penguin purchases from the dedicated shop tab."""

    ASSET_DIR = "images/penguin"
    EGG_IMAGE = "egg.png"
    BUY_BUTTON_IMAGE = "buy_button.png"
    MAX_BUTTON_IMAGE = "max_button.png"
    FIFTY_CHECK_IMAGE = "50check.png"
    CLOSE_IMAGE = "close.png"

    EGG_MIN_X = 42
    EGG_MAX_X = 344
    EGG_LINE_PADDING = 36
    EGG_MATCH_SCALES = (0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0)
    POPUP_FIFTY_CHECK_ROI = (540, 380, 740, 470)
    POPUP_MAX_BUTTON_ROI = (840, 430, 980, 520)
    POPUP_FINAL_BUY_ROI = (700, 540, 940, 630)
    POPUP_FINAL_BUY_SCALES = (0.95, 1.0, 1.05, 1.1, 1.15)

    DEFAULT_THRESHOLDS = {
        "egg": 0.9,
        "buy_button": 0.9,
        "max_button": 0.9,
        "fifty_check": 0.9,
        "close": 0.9,
    }

    def __init__(
        self,
        adb_controller: ADBController,
        cycle_count: int,
        thresholds: Optional[Dict[str, float]] = None,
        debug_mode: bool = False,
        runtime_dir=None,
        base_dir: str = None,
    ):
        self.adb = adb_controller
        self.cycle_count = max(1, int(cycle_count))
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.debug_mode = debug_mode
        self.resource_dir = Path(base_dir) if base_dir else get_resource_root()
        self.runtime_dir = Path(runtime_dir) if runtime_dir else get_runtime_root() / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_path = self.runtime_dir / "penguin_screen.png"
        self.user_action = None
        self.paused = False
        self.screen_width, self.screen_height = self.adb.get_screen_size()
        self._template_cache: Dict[str, np.ndarray] = {}
        self.stats = {
            "cycles_completed": 0,
            "purchase_attempts": 0,
            "penguins_bought": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_time": 0,
        }

    def run(self) -> Dict:
        self.stats["start_time"] = time.time()
        logger.info("펭귄 구매 자동화를 시작합니다. 목표 사이클: %s회", self.cycle_count)

        for cycle_index in range(1, self.cycle_count + 1):
            if not self._wait_if_paused():
                return self._finish_stats()
            if self.user_action == "stop":
                logger.info("사용자 요청으로 펭귄 구매를 중지합니다.")
                return self._finish_stats()

            logger.info("펭귄 구매 사이클 %s/%s", cycle_index, self.cycle_count)
            success = self._run_single_cycle()
            if not success:
                logger.error("펭귄 구매 사이클 %s에서 중단합니다.", cycle_index)
                return self._finish_stats()
            self.stats["cycles_completed"] = cycle_index

        logger.info("펭귄 구매 자동화를 완료했습니다.")
        return self._finish_stats()

    def _run_single_cycle(self) -> bool:
        if not self._capture_screen("펭귄 알 탐색"):
            return False

        screen = read_image(str(self.screenshot_path), cv2.IMREAD_COLOR)
        if screen is None:
            logger.error("펭귄 스크린샷을 불러오지 못했습니다: %s", self.screenshot_path)
            return False

        egg_match = self._find_egg_match(screen)
        if not egg_match:
            logger.warning("지정한 X축 범위(42~344) 안에서 펭귄 알을 찾지 못했습니다.")
            return False

        buy_match = self._find_buy_button_for_egg(screen, egg_match)
        if not buy_match:
            logger.warning("펭귄 알이 있는 줄에서 구매 버튼을 찾지 못했습니다.")
            return False

        if not self._tap_box(buy_match, "펭귄 구매 버튼"):
            return False
        self.stats["purchase_attempts"] += 1
        time.sleep(0.5)

        if not self._capture_screen("구매 팝업 확인"):
            return False
        popup_screen = read_image(str(self.screenshot_path), cv2.IMREAD_COLOR)
        if popup_screen is None:
            logger.error("구매 팝업 스크린샷을 불러오지 못했습니다.")
            return False

        if not self._has_popup_fifty_check(popup_screen):
            logger.info("50 / 50 상태가 아니어서 최대 버튼을 누릅니다.")
            max_match = self._find_popup_max_button(popup_screen)
            if not max_match:
                logger.warning("최대 버튼을 찾지 못했습니다.")
                return False
            if not self._tap_box(max_match, "최대 버튼"):
                return False
            time.sleep(0.4)
            if not self._capture_screen("최대 수량 적용 후 구매 버튼 확인"):
                return False
            popup_screen = read_image(str(self.screenshot_path), cv2.IMREAD_COLOR)
            if popup_screen is None:
                logger.error("최대 수량 적용 후 팝업 스크린샷을 불러오지 못했습니다.")
                return False

        confirm_buy_match = self._find_popup_final_buy_button(popup_screen)
        if not confirm_buy_match:
            logger.warning("팝업 안에서 최종 구매 버튼을 찾지 못했습니다.")
            return False
        if not self._tap_box(confirm_buy_match, "최종 구매 버튼"):
            return False
        time.sleep(0.7)

        if not self._capture_screen("구매 완료 팝업 닫기"):
            return False
        result_screen = read_image(str(self.screenshot_path), cv2.IMREAD_COLOR)
        if result_screen is None:
            logger.error("구매 완료 팝업 스크린샷을 불러오지 못했습니다.")
            return False

        close_match = self._find_best_match(result_screen, self.CLOSE_IMAGE, self.thresholds["close"])
        if not close_match:
            logger.warning("구매 완료 팝업의 닫기 화살표를 찾지 못했습니다.")
            return False
        if not self._tap_box(close_match, "구매 완료 팝업 닫기"):
            return False

        self.stats["penguins_bought"] += 1
        time.sleep(0.5)
        return True

    def _wait_if_paused(self) -> bool:
        while self.paused:
            if self.user_action == "stop":
                return False
            time.sleep(0.1)
        return True

    def _capture_screen(self, context: str) -> bool:
        if self.adb.screenshot(str(self.screenshot_path)):
            return True
        logger.error("스크린샷 촬영 실패: %s", context)
        return False

    def _find_egg_match(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        best_match = None
        best_score = -1.0
        for scale in self.EGG_MATCH_SCALES:
            matches = self._find_all_matches(
                screen,
                self.EGG_IMAGE,
                self.thresholds["egg"],
                scales=(scale,),
            )
            for match in matches:
                x, _, w, _ = match
                center_x = x + (w // 2)
                if not (self.EGG_MIN_X <= center_x <= self.EGG_MAX_X):
                    continue
                score = self._match_score_for_box(screen, self.EGG_IMAGE, match)
                if score > best_score:
                    best_score = score
                    best_match = match
        if best_match:
            logger.info("펭귄 알 발견: %s (유사도 %.3f)", best_match, best_score)
            return best_match
        return None

    def _find_buy_button_for_egg(
        self,
        screen: np.ndarray,
        egg_match: Tuple[int, int, int, int],
    ) -> Optional[Tuple[int, int, int, int]]:
        egg_x, egg_y, egg_w, egg_h = egg_match
        egg_center_x = egg_x + (egg_w // 2)
        egg_bottom_y = egg_y + egg_h
        candidates = self._find_all_matches(screen, self.BUY_BUTTON_IMAGE, self.thresholds["buy_button"])
        filtered = []
        for candidate in candidates:
            btn_x, btn_y, btn_w, btn_h = candidate
            btn_center_x = btn_x + (btn_w // 2)
            btn_center_y = btn_y + (btn_h // 2)
            if btn_center_y <= egg_bottom_y:
                continue
            horizontal_distance = abs(btn_center_x - egg_center_x)
            filtered.append((horizontal_distance, btn_center_y, candidate))

        if not filtered:
            return None

        filtered.sort(key=lambda item: (item[0], item[1]))
        best = filtered[0][2]
        logger.info("펭귄 칸의 구매 버튼 발견: %s", best)
        return best

    def _has_template(self, screen: np.ndarray, image_name: str, threshold: float) -> bool:
        return self._find_best_match(screen, image_name, threshold) is not None

    def _has_popup_fifty_check(self, screen: np.ndarray) -> bool:
        return self._find_in_roi(
            screen,
            self.POPUP_FIFTY_CHECK_ROI,
            self.FIFTY_CHECK_IMAGE,
            self.thresholds["fifty_check"],
        ) is not None

    def _find_popup_max_button(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        return self._find_in_roi(
            screen,
            self.POPUP_MAX_BUTTON_ROI,
            self.MAX_BUTTON_IMAGE,
            self.thresholds["max_button"],
        )

    def _find_popup_final_buy_button(self, screen: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        return self._find_in_roi(
            screen,
            self.POPUP_FINAL_BUY_ROI,
            self.BUY_BUTTON_IMAGE,
            self.thresholds["buy_button"],
            scales=self.POPUP_FINAL_BUY_SCALES,
        )

    def _find_best_match(
        self,
        screen: np.ndarray,
        image_name: str,
        threshold: float,
    ) -> Optional[Tuple[int, int, int, int]]:
        return self._find_best_match_in_image(screen, image_name, threshold)

    def _find_in_roi(
        self,
        screen: np.ndarray,
        roi_bounds: Tuple[int, int, int, int],
        image_name: str,
        threshold: float,
        scales: Optional[Tuple[float, ...]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        x1, y1, x2, y2 = roi_bounds
        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return None

        if scales:
            best_match = None
            best_score = -1.0
            for scale in scales:
                match = self._find_best_match_in_image(roi, image_name, threshold, scale=scale)
                if not match:
                    continue
                score = self._match_score_for_box(roi, image_name, match, scale=scale)
                if score > best_score:
                    best_score = score
                    best_match = match
            if not best_match:
                return None
            rel_x, rel_y, width, height = best_match
            return (x1 + rel_x, y1 + rel_y, width, height)

        match = self._find_best_match_in_image(roi, image_name, threshold)
        if not match:
            return None
        rel_x, rel_y, width, height = match
        return (x1 + rel_x, y1 + rel_y, width, height)

    def _find_best_match_in_image(
        self,
        image: np.ndarray,
        image_name: str,
        threshold: float,
        scale: float = 1.0,
    ) -> Optional[Tuple[int, int, int, int]]:
        template = self._load_template(image_name, scale=scale)
        if template is None:
            return None
        if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
            return None

        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            if self.debug_mode:
                logger.debug("%s 매칭 실패: 최대 유사도 %.3f", image_name, max_val)
            return None

        height, width = template.shape[:2]
        return (max_loc[0], max_loc[1], width, height)

    def _find_all_matches(
        self,
        screen: np.ndarray,
        image_name: str,
        threshold: float,
        scales: Optional[Tuple[float, ...]] = None,
    ) -> List[Tuple[int, int, int, int]]:
        candidates: List[Tuple[float, Tuple[int, int, int, int]]] = []
        scale_values = scales or (1.0,)
        for scale in scale_values:
            template = self._load_template(image_name, scale=scale)
            if template is None:
                continue
            if screen.shape[0] < template.shape[0] or screen.shape[1] < template.shape[1]:
                continue

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            points = np.where(result >= threshold)
            height, width = template.shape[:2]
            for point in zip(*points[::-1]):
                score = float(result[point[1], point[0]])
                candidates.append((score, (point[0], point[1], width, height)))
        candidates.sort(key=lambda item: item[0], reverse=True)

        matches: List[Tuple[int, int, int, int]] = []
        for _, candidate in candidates:
            if any(self._boxes_overlap(candidate, existing) for existing in matches):
                continue
            matches.append(candidate)
        return matches

    def _load_template(self, image_name: str, scale: float = 1.0) -> Optional[np.ndarray]:
        cache_key = f"{image_name}@{scale:.2f}"
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        path = self.resource_dir / self.ASSET_DIR / image_name
        template = read_image(str(path), cv2.IMREAD_COLOR)
        if template is None:
            logger.error("템플릿 이미지를 불러오지 못했습니다: %s", path)
            return None
        if scale != 1.0:
            interpolation = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
            template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
        self._template_cache[cache_key] = template
        return template

    def _match_score_for_box(
        self,
        screen: np.ndarray,
        image_name: str,
        box: Tuple[int, int, int, int],
        scale: Optional[float] = None,
    ) -> float:
        x, y, width, height = box
        roi = screen[y:y + height, x:x + width]
        if roi.size == 0:
            return 0.0

        base_template = self._load_template(image_name)
        if base_template is None:
            return 0.0
        target_scale = scale if scale is not None else (width / max(base_template.shape[1], 1))
        template = self._load_template(image_name, scale=target_scale)
        if template is None or roi.shape[:2] != template.shape[:2]:
            return 0.0
        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return float(max_val)

    def _tap_box(self, box: Tuple[int, int, int, int], label: str) -> bool:
        if self.user_action == "stop":
            return False
        x, y, width, height = box
        center_x = x + (width // 2)
        center_y = y + (height // 2)
        logger.info("%s 클릭: (%s, %s)", label, center_x, center_y)
        return self.adb.tap(center_x, center_y, delay=0.3)

    def _boxes_overlap(
        self,
        first: Tuple[int, int, int, int],
        second: Tuple[int, int, int, int],
    ) -> bool:
        x1, y1, w1, h1 = first
        x2, y2, w2, h2 = second
        overlap_x = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
        overlap_y = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
        if overlap_x == 0 or overlap_y == 0:
            return False
        overlap_area = overlap_x * overlap_y
        smaller_area = min(w1 * h1, w2 * h2)
        return overlap_area / float(smaller_area) > 0.3

    def _finish_stats(self) -> Dict:
        if self.stats.get("start_time") and not self.stats.get("end_time"):
            self.stats["end_time"] = time.time()
            self.stats["elapsed_time"] = int(self.stats["end_time"] - self.stats["start_time"])
        return self.stats

    def set_user_action(self, action: str):
        if action == "pause":
            self.paused = True
            logger.info("사용자 요청으로 펭귄 구매를 일시정지합니다.")
        elif action == "resume":
            self.paused = False
            self.user_action = None
            logger.info("사용자 요청으로 펭귄 구매를 재개합니다.")
        elif action == "stop":
            self.user_action = "stop"
            self.paused = False
            logger.info("사용자 요청으로 펭귄 구매를 중지합니다.")

    def get_stats(self) -> Dict:
        return self.stats.copy()
