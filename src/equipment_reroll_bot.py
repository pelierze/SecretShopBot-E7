"""
Equipment option reroll automation.

This module uses image templates only. It does not include OCR, so option names,
target values, and buttons must be provided as image files before the automation
can run successfully.
"""
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from .adb_controller import ADBController
from .image_matcher import ImageMatcher

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
    """장비 옵션 리롤 자동화 봇"""

    ASSET_DIR = "images/equipment_options"
    SPEED_OPTION_IMAGE = "speed_option.png"
    REROLL_BUTTON_IMAGE = "reroll_button.png"
    CLAIM_BUTTON_IMAGE = "claim_button.png"

    def __init__(
        self,
        adb_controller: ADBController,
        target_speed: int,
        max_rerolls: int,
        delay_before_reroll: float,
        threshold: float = 0.9,
        claim_on_match: bool = True,
        debug_mode: bool = False,
        base_dir: str = None,
        runtime_dir=None,
    ):
        self.adb = adb_controller
        self.target_speed = target_speed
        self.max_rerolls = max_rerolls
        self.delay_before_reroll = delay_before_reroll
        self.threshold = threshold
        self.claim_on_match = claim_on_match
        self.debug_mode = debug_mode
        self.resource_dir = Path(base_dir) if base_dir else get_resource_root()
        self.runtime_dir = Path(runtime_dir) if runtime_dir else get_runtime_root() / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.matcher = ImageMatcher(threshold=threshold)
        self.screenshot_path = self.runtime_dir / "equipment_reroll_screen.png"
        self.paused = False
        self.user_action = None
        self.stats = {
            "attempts": 0,
            "rerolls": 0,
            "option_found": 0,
            "target_found": 0,
            "claimed": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_time": 0,
        }

    def _find_image_file(self, base_name: str) -> Optional[Path]:
        directory = self.resource_dir / self.ASSET_DIR
        exact_path = directory / base_name
        if exact_path.exists():
            return exact_path

        if not directory.exists():
            logger.warning("장비 리롤 이미지 폴더를 찾을 수 없음: %s", directory)
            return None

        base_name_lower = base_name.lower()
        for file in directory.iterdir():
            if file.is_file() and file.name.lower() == base_name_lower:
                return file
        return None

    def _required_images(self) -> Dict[str, Optional[Path]]:
        value_image = f"speed_{self.target_speed}.png"
        images = {
            "속도 옵션": self._find_image_file(self.SPEED_OPTION_IMAGE),
            "목표 속도 값": self._find_image_file(value_image),
            "리롤 버튼": self._find_image_file(self.REROLL_BUTTON_IMAGE),
        }
        if self.claim_on_match:
            images["수령 버튼"] = self._find_image_file(self.CLAIM_BUTTON_IMAGE)
        return images

    def _validate_images(self) -> Optional[Dict[str, Path]]:
        images = self._required_images()
        missing = [name for name, path in images.items() if not path]
        if missing:
            logger.error("장비 리롤 이미지가 준비되지 않았습니다: %s", ", ".join(missing))
            logger.error("필요 폴더: %s", self.resource_dir / self.ASSET_DIR)
            logger.error("목표 속도 값 이미지는 speed_%s.png 파일명으로 준비하세요.", self.target_speed)
            return None
        return {name: path for name, path in images.items() if path}

    def run(self) -> Dict:
        import time as time_module

        images = self._validate_images()
        self.stats["start_time"] = time_module.time()
        if not images:
            return self._finish_stats()

        logger.info(
            "장비 옵션 리롤 시작 - 목표 속도: %s, 최대 리롤: %s회, 리롤 전 대기: %s초",
            self.target_speed,
            self.max_rerolls,
            self.delay_before_reroll,
        )

        for attempt in range(1, self.max_rerolls + 1):
            if self.user_action == "stop":
                logger.info("사용자가 중지를 선택했습니다.")
                return self._finish_stats()

            while self.paused:
                time.sleep(0.1)
                if self.user_action == "stop":
                    logger.info("사용자가 중지를 선택했습니다.")
                    return self._finish_stats()

            self.stats["attempts"] = attempt
            logger.info("장비 옵션 스캔 %s/%s", attempt, self.max_rerolls)
            self.adb.screenshot(str(self.screenshot_path))
            time.sleep(0.2)

            option_location = self.matcher.find_image(
                str(self.screenshot_path),
                str(images["속도 옵션"]),
                threshold=self.threshold,
            )
            if option_location:
                self.stats["option_found"] += 1
                logger.info("속도 옵션 발견: %s", option_location)

                value_location = self.matcher.find_image(
                    str(self.screenshot_path),
                    str(images["목표 속도 값"]),
                    threshold=self.threshold,
                )
                if value_location:
                    self.stats["target_found"] += 1
                    logger.info("목표 속도 %s 발견: %s", self.target_speed, value_location)
                    if self.claim_on_match:
                        if self._click_image(images["수령 버튼"], "수령 버튼"):
                            self.stats["claimed"] += 1
                    return self._finish_stats()
                logger.info("속도 옵션은 있으나 목표 수치가 아닙니다.")
            else:
                logger.info("속도 옵션을 찾지 못했습니다.")

            if attempt >= self.max_rerolls:
                logger.warning("최대 리롤 횟수에 도달했습니다.")
                return self._finish_stats()

            if self.delay_before_reroll > 0:
                logger.info("리롤 전 %.1f초 대기합니다.", self.delay_before_reroll)
                if not self._sleep_with_stop(self.delay_before_reroll):
                    return self._finish_stats()

            if self._click_image(images["리롤 버튼"], "리롤 버튼"):
                self.stats["rerolls"] += 1
                if not self._sleep_with_stop(0.5):
                    return self._finish_stats()
            else:
                logger.error("리롤 버튼을 찾지 못해 중지합니다.")
                return self._finish_stats()

        return self._finish_stats()

    def _sleep_with_stop(self, seconds: float) -> bool:
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self.user_action == "stop":
                logger.info("사용자가 중지를 선택했습니다.")
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
            logger.warning("%s을 찾을 수 없습니다.", label)
            return False
        center_x, center_y = self.matcher.get_center(location)
        self.adb.tap(center_x, center_y, delay=0.3)
        logger.info("%s 클릭: (%s, %s)", label, center_x, center_y)
        return True

    def _finish_stats(self) -> Dict:
        import time as time_module

        if self.stats.get("start_time") and not self.stats.get("end_time"):
            self.stats["end_time"] = time_module.time()
            self.stats["elapsed_time"] = int(self.stats["end_time"] - self.stats["start_time"])
        return self.stats

    def set_user_action(self, action: str):
        if action == "pause":
            self.paused = True
            logger.info("사용자가 일시정지를 요청했습니다.")
        elif action == "resume":
            self.paused = False
            self.user_action = None
            logger.info("사용자가 재개를 요청했습니다.")
        elif action == "stop":
            self.user_action = "stop"
            self.paused = False
            logger.info("사용자가 중지를 요청했습니다.")

    def get_stats(self) -> Dict:
        return self.stats.copy()
