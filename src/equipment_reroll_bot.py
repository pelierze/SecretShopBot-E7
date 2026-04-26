"""
Equipment option reroll automation.

This module scans only the rerolled option panel on the right side of the
comparison dialog. It finds the target option via template matching and reads
the numeric value from the same row via OCR.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from .adb_controller import ADBController
from .image_matcher import ImageMatcher, read_image

logger = logging.getLogger(__name__)


def get_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class EquipmentRerollBot:
    """Automates equipment option rerolling on the right-hand option panel."""

    ASSET_DIR = "images/equipment_options"
    REROLL_BUTTON_IMAGE = "reroll_button.png"
    OPTION_IMAGE_MAP = {
        "speed": "speed_option.png",
        "attack": "attack_option.png",
        "life": "life_option.png",
        "defense": "defence_option.png",
        "crit_chance": "crit-chance_option.png",
        "crit_damage": "crit-damage_option.png",
        "effect_resistance": "effect-resistance_option.png",
        "effectiveness": "effectiveness_option.png",
    }

    # Ratios tuned for the 1280x720 reroll comparison screen shared by the user.
    # The region covers only the rerolled option list on the right side.
    OPTION_PANEL_BOUNDS = {
        "left": 0.405,
        "top": 0.18,
        "right": 0.655,
        "bottom": 0.545,
    }
    ROW_COUNT = 4
    ROW_VERTICAL_PADDING_RATIO = 0.08
    OPTION_MATCH_WIDTH_RATIO = 0.78
    NUMBER_SCAN_WIDTH_RATIO = 0.26
    NUMBER_SCAN_HEIGHT_RATIO = 1.6
    NUMBER_SCAN_LEFT_GAP_RATIO = 0.08
    OCR_SCALE = 3
    OCR_MIN_CONFIDENCE = 0.35

    def __init__(
        self,
        adb_controller: ADBController,
        target_speed: int,
        max_rerolls: int,
        delay_before_reroll: float,
        threshold: float = 0.9,
        target_is_percent: bool = False,
        debug_mode: bool = False,
        base_dir: str = None,
        runtime_dir=None,
        target_option: str = "speed",
    ):
        self.adb = adb_controller
        self.target_option = self._normalize_target_option(target_option)
        self.target_speed = target_speed
        self.max_rerolls = max_rerolls
        self.delay_before_reroll = delay_before_reroll
        self.threshold = threshold
        self.target_is_percent = target_is_percent
        self.debug_mode = debug_mode
        self.resource_dir = Path(base_dir) if base_dir else get_resource_root()
        self.runtime_dir = Path(runtime_dir) if runtime_dir else get_runtime_root() / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.matcher = ImageMatcher(threshold=threshold)
        self.ocr_engine = RapidOCR()
        self.screenshot_path = self.runtime_dir / "equipment_reroll_screen.png"
        self.paused = False
        self.user_action = None
        self.stats = {
            "attempts": 0,
            "rerolls": 0,
            "option_found": 0,
            "target_found": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_time": 0,
        }

    def _normalize_target_option(self, target_option: str) -> str:
        if target_option is None:
            return "speed"
        normalized = target_option.strip().lower()
        alias_map = {
            "속도": "speed",
            "speed": "speed",
            "공격력": "attack",
            "attack": "attack",
            "생명력": "life",
            "life": "life",
            "방어력": "defense",
            "defense": "defense",
            "defence": "defense",
            "치명타 확률": "crit_chance",
            "치명확률": "crit_chance",
            "crit chance": "crit_chance",
            "crit_chance": "crit_chance",
            "치명타 피해": "crit_damage",
            "치피": "crit_damage",
            "crit damage": "crit_damage",
            "crit_damage": "crit_damage",
            "효과저항": "effect_resistance",
            "effect resistance": "effect_resistance",
            "effect_resistance": "effect_resistance",
            "효과적중": "effectiveness",
            "effectiveness": "effectiveness",
            "effect hit": "effectiveness",
        }
        return alias_map.get(normalized, normalized)

    def _target_option_label(self) -> str:
        label_map = {
            "speed": "속도",
            "attack": "공격력",
            "life": "생명력",
            "defense": "방어력",
            "crit_chance": "치명타 확률",
            "crit_damage": "치명타 피해",
            "effect_resistance": "효과저항",
            "effectiveness": "효과적중",
        }
        return label_map.get(self.target_option, self.target_option)

    def _find_image_file(self, base_name: str) -> Optional[Path]:
        directory = self.resource_dir / self.ASSET_DIR
        exact_path = directory / base_name
        if exact_path.exists():
            return exact_path

        if not directory.exists():
            logger.warning("장비 리롤 이미지 폴더를 찾을 수 없습니다: %s", directory)
            return None

        base_name_lower = base_name.lower()
        for file in directory.iterdir():
            if file.is_file() and file.name.lower() == base_name_lower:
                return file
        return None

    def _required_images(self) -> Dict[str, Optional[Path]]:
        option_image = self.OPTION_IMAGE_MAP.get(self.target_option)
        images = {
            "target_option": self._find_image_file(option_image) if option_image else None,
            "reroll_button": self._find_image_file(self.REROLL_BUTTON_IMAGE),
        }
        return images

    def _validate_images(self) -> Optional[Dict[str, Path]]:
        images = self._required_images()
        missing = [name for name, path in images.items() if not path]
        if missing:
            logger.error("장비 리롤 이미지가 준비되지 않았습니다: %s", ", ".join(missing))
            logger.error("필요한 폴더: %s", self.resource_dir / self.ASSET_DIR)
            logger.error("숫자 이미지는 더 이상 필요하지 않으며 옵션 이미지와 버튼 이미지만 준비하면 됩니다.")
            return None
        return {name: path for name, path in images.items() if path}

    def run(self) -> Dict:
        self.stats["start_time"] = time.time()
        images = self._validate_images()
        if not images:
            return self._finish_stats()

        logger.info(
            "장비 옵션 리롤 시작 - 대상 옵션: %s%s, 목표 수치: %s, 최대 리롤: %s회, 리롤 전 대기: %.1f초",
            self._target_option_label(),
            "%" if self.target_is_percent else "",
            self.target_speed,
            self.max_rerolls,
            self.delay_before_reroll,
        )

        for attempt in range(1, self.max_rerolls + 1):
            if self.user_action == "stop":
                logger.info("사용자 요청으로 장비 리롤을 중지합니다.")
                return self._finish_stats()

            while self.paused:
                time.sleep(0.1)
                if self.user_action == "stop":
                    logger.info("사용자 요청으로 장비 리롤을 중지합니다.")
                    return self._finish_stats()

            self.stats["attempts"] = attempt
            logger.info("장비 옵션 스캔 %s/%s", attempt, self.max_rerolls)

            screen = self._capture_screen()
            if screen is None:
                return self._finish_stats()

            match = self._find_target_option_row(screen, images["target_option"])
            if match is not None:
                self.stats["option_found"] += 1
                row_index, option_box, row_bounds = match
                detected_value, detected_has_percent = self._read_row_numeric_value(screen, row_bounds, option_box, row_index)
                logger.info(
                    "대상 옵션 발견 - 행 %s, 위치: %s, 인식 숫자: %s%s",
                    row_index + 1,
                    option_box,
                    detected_value if detected_value is not None else "없음",
                    "%" if detected_value is not None and detected_has_percent else "",
                )
                if detected_value == self.target_speed and detected_has_percent == self.target_is_percent:
                    self.stats["target_found"] += 1
                    logger.info("목표 수치 %s%s를 찾았습니다.", self.target_speed, "%" if self.target_is_percent else "")
                    return self._finish_stats()
                if detected_value is None:
                    logger.info(
                        "대상 옵션 '%s'은(는) 찾았지만 숫자 OCR에 실패했습니다. 안전을 위해 즉시 중지합니다.",
                        self._target_option_label(),
                    )
                    return self._finish_stats()
                if detected_has_percent != self.target_is_percent:
                    logger.info(
                        "대상 옵션 '%s'은(는) 찾았지만 %% 여부가 다릅니다. 목표: %s, 현재: %s",
                        self._target_option_label(),
                        "%" if self.target_is_percent else "고정 수치",
                        "%" if detected_has_percent else "고정 수치",
                    )
                else:
                    logger.info(
                        "대상 옵션 '%s'은(는) 찾았지만 목표 수치 %s%s가 아닙니다. 현재 수치: %s%s",
                        self._target_option_label(),
                        self.target_speed,
                        "%" if self.target_is_percent else "",
                        detected_value,
                        "%" if detected_has_percent else "",
                    )
            else:
                logger.info(
                    "대상 옵션 '%s'을(를) 우측 리롤 패널에서 찾지 못했습니다.",
                    self._target_option_label(),
                )

            if attempt >= self.max_rerolls:
                logger.warning("최대 리롤 횟수에 도달했습니다.")
                return self._finish_stats()

            if self.delay_before_reroll > 0:
                logger.info("리롤 전 %.1f초 대기합니다.", self.delay_before_reroll)
                if not self._sleep_with_stop(self.delay_before_reroll):
                    return self._finish_stats()

            if self._click_image(images["reroll_button"], "보조 능력치 변경 버튼"):
                self.stats["rerolls"] += 1
                if not self._sleep_with_stop(0.5):
                    return self._finish_stats()
            else:
                logger.error("보조 능력치 변경 버튼을 찾지 못해 중지합니다.")
                return self._finish_stats()

        return self._finish_stats()

    def _capture_screen(self) -> Optional[np.ndarray]:
        try:
            self.adb.screenshot(str(self.screenshot_path))
            time.sleep(0.2)
            screen = read_image(str(self.screenshot_path))
            if screen is None:
                logger.error("리롤 스크린샷을 불러오지 못했습니다: %s", self.screenshot_path)
                return None
            return screen
        except Exception as e:
            logger.error("리롤 스크린샷 캡처 중 오류: %s", e, exc_info=self.debug_mode)
            return None

    def _find_target_option_row(
        self,
        screen: np.ndarray,
        option_image_path: Path,
    ) -> Optional[Tuple[int, Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
        rows = self._get_row_bounds(screen.shape[1], screen.shape[0])
        template = read_image(str(option_image_path), cv2.IMREAD_COLOR)
        if template is None:
            logger.error("옵션 템플릿을 불러오지 못했습니다: %s", option_image_path)
            return None

        for row_index, bounds in enumerate(rows):
            x1, y1, x2, y2 = bounds
            row_image = screen[y1:y2, x1:x2]
            option_scan_width = max(int((x2 - x1) * self.OPTION_MATCH_WIDTH_RATIO), template.shape[1])
            option_scan = row_image[:, :option_scan_width]
            location, similarity = self._match_template_in_image(option_scan, template)
            if self.debug_mode:
                self._save_debug_image(f"row_{row_index + 1}_option_scan.png", option_scan)
            if location is None:
                logger.debug("행 %s에서 대상 옵션을 찾지 못했습니다.", row_index + 1)
                continue

            local_x, local_y, width, height = location
            global_box = (x1 + local_x, y1 + local_y, width, height)
            logger.info(
                "행 %s에서 대상 옵션 매칭 성공 - 신뢰도 %.1f%%, 위치 %s",
                row_index + 1,
                similarity * 100,
                global_box,
            )
            return row_index, global_box, bounds
        return None

    def _match_template_in_image(
        self,
        image: np.ndarray,
        template: np.ndarray,
    ) -> Tuple[Optional[Tuple[int, int, int, int]], float]:
        if image.size == 0 or template.size == 0:
            return None, 0.0
        if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
            return None, 0.0

        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < self.threshold:
            return None, float(max_val)
        h, w = template.shape[:2]
        return (max_loc[0], max_loc[1], w, h), float(max_val)

    def _get_row_bounds(self, screen_width: int, screen_height: int) -> List[Tuple[int, int, int, int]]:
        x1 = int(screen_width * self.OPTION_PANEL_BOUNDS["left"])
        y1 = int(screen_height * self.OPTION_PANEL_BOUNDS["top"])
        x2 = int(screen_width * self.OPTION_PANEL_BOUNDS["right"])
        y2 = int(screen_height * self.OPTION_PANEL_BOUNDS["bottom"])

        row_height = max((y2 - y1) // self.ROW_COUNT, 1)
        vertical_padding = int(row_height * self.ROW_VERTICAL_PADDING_RATIO)
        bounds = []
        for row_index in range(self.ROW_COUNT):
            row_top = y1 + row_index * row_height + vertical_padding
            row_bottom = y1 + (row_index + 1) * row_height - vertical_padding
            bounds.append((x1, row_top, x2, max(row_top + 1, row_bottom)))
        return bounds

    def _read_row_numeric_value(
        self,
        screen: np.ndarray,
        row_bounds: Tuple[int, int, int, int],
        option_box: Tuple[int, int, int, int],
        row_index: int,
    ) -> Tuple[Optional[int], bool]:
        x1, y1, x2, y2 = row_bounds
        option_x, option_y, option_w, option_h = option_box

        row_width = x2 - x1
        number_width = max(int(row_width * self.NUMBER_SCAN_WIDTH_RATIO), option_w * 2)
        number_x1 = max(option_x + option_w + int(row_width * self.NUMBER_SCAN_LEFT_GAP_RATIO), x2 - number_width)
        number_x2 = x2

        option_center_y = option_y + (option_h // 2)
        target_height = max(int(option_h * self.NUMBER_SCAN_HEIGHT_RATIO), option_h + 12)
        number_y1 = max(y1, option_center_y - (target_height // 2))
        number_y2 = min(y2, option_center_y + (target_height // 2))
        if number_y2 <= number_y1:
            number_y1, number_y2 = y1, y2

        number_roi = screen[number_y1:number_y2, number_x1:number_x2]
        processed_images = self._build_ocr_variants(number_roi)

        if self.debug_mode:
            self._save_debug_image(f"row_{row_index + 1}_number_roi.png", number_roi)
            for variant_name, variant_image in processed_images:
                self._save_debug_image(f"row_{row_index + 1}_{variant_name}.png", variant_image)

        best_candidate = None
        best_confidence = 0.0
        best_has_percent = False
        for _, image in processed_images:
            candidate, confidence, has_percent = self._ocr_numeric_image(image, use_detection=False)
            if candidate is None:
                candidate, confidence, has_percent = self._ocr_numeric_image(image, use_detection=True)
            if candidate is None:
                continue
            if confidence > best_confidence:
                best_candidate = candidate
                best_confidence = confidence
                best_has_percent = has_percent

        if best_candidate is None:
            logger.info("행 %s 숫자 OCR 결과가 비어 있습니다.", row_index + 1)
            return None, False

        logger.info(
            "행 %s 숫자 OCR 결과: %s%s (신뢰도 %.1f%%)",
            row_index + 1,
            best_candidate,
            "%" if best_has_percent else "",
            best_confidence * 100,
        )
        return best_candidate, best_has_percent

    def _build_ocr_variants(self, number_roi: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        if number_roi.size == 0:
            return []

        gray = cv2.cvtColor(number_roi, cv2.COLOR_BGR2GRAY)
        enlarged = cv2.resize(gray, None, fx=self.OCR_SCALE, fy=self.OCR_SCALE, interpolation=cv2.INTER_CUBIC)
        enlarged = cv2.copyMakeBorder(enlarged, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=0)
        _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        inverted = cv2.bitwise_not(binary)
        blurred = cv2.GaussianBlur(enlarged, (3, 3), 0)
        _, binary_blurred = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            enlarged,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
        return [
            ("ocr_gray", enlarged),
            ("ocr_binary", binary),
            ("ocr_inverted", inverted),
            ("ocr_binary_blurred", binary_blurred),
            ("ocr_adaptive", adaptive),
        ]

    def _ocr_numeric_image(self, image: np.ndarray, use_detection: bool) -> Tuple[Optional[int], float, bool]:
        try:
            ocr_res, _ = self.ocr_engine(image, use_det=use_detection, use_cls=False, use_rec=True)
        except Exception as e:
            logger.error("숫자 OCR 중 오류: %s", e, exc_info=self.debug_mode)
            return None, 0.0, False

        if not ocr_res:
            return None, 0.0, False

        best_candidate = None
        best_confidence = 0.0
        best_has_percent = False
        for item in ocr_res:
            if use_detection:
                if len(item) < 3:
                    continue
                text = str(item[1])
                confidence = float(item[2])
            else:
                if len(item) < 2:
                    continue
                text = str(item[0])
                confidence = float(item[1])
            has_percent = "%" in text
            digits = "".join(ch for ch in text if ch.isdigit())
            if not digits or confidence < self.OCR_MIN_CONFIDENCE:
                continue
            try:
                value = int(digits)
            except ValueError:
                continue
            if confidence > best_confidence:
                best_candidate = value
                best_confidence = confidence
                best_has_percent = has_percent
        return best_candidate, best_confidence, best_has_percent

    def _save_debug_image(self, name: str, image: np.ndarray):
        debug_dir = self.runtime_dir / "reroll_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        target_path = debug_dir / name
        ext = target_path.suffix or ".png"
        success, encoded = cv2.imencode(ext, image)
        if success:
            encoded.tofile(str(target_path))

    def _sleep_with_stop(self, seconds: float) -> bool:
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self.user_action == "stop":
                logger.info("사용자 요청으로 장비 리롤을 중지합니다.")
                return False
            time.sleep(min(0.1, end_time - time.time()))
        return True

    def _click_image(self, image_path: Path, label: str) -> bool:
        self.adb.screenshot(str(self.screenshot_path))
        time.sleep(0.2)
        location = self.matcher.find_image(
            str(self.screenshot_path),
            str(image_path),
            threshold=self.threshold,
        )
        if not location:
            logger.warning("%s을(를) 찾을 수 없습니다.", label)
            return False
        center_x, center_y = self.matcher.get_center(location)
        self.adb.tap(center_x, center_y, delay=0.3)
        logger.info("%s 클릭: (%s, %s)", label, center_x, center_y)
        return True

    def _finish_stats(self) -> Dict:
        if self.stats.get("start_time") and not self.stats.get("end_time"):
            self.stats["end_time"] = time.time()
            self.stats["elapsed_time"] = int(self.stats["end_time"] - self.stats["start_time"])
        return self.stats

    def set_user_action(self, action: str):
        if action == "pause":
            self.paused = True
            logger.info("사용자 요청으로 장비 리롤을 일시정지합니다.")
        elif action == "resume":
            self.paused = False
            self.user_action = None
            logger.info("사용자 요청으로 장비 리롤을 재개합니다.")
        elif action == "stop":
            self.user_action = "stop"
            self.paused = False
            logger.info("사용자 요청으로 장비 리롤을 중지합니다.")

    def get_stats(self) -> Dict:
        return self.stats.copy()
