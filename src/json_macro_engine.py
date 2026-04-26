"""
Data-only JSON macro runner.

This executes a small, validated action set from remote_script.json. It does
not evaluate Python code or shell commands.
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


class JsonMacroEngine:
    ITEMS_DIR = "images/items"
    BUTTONS_DIR = "images/buttons"

    def __init__(
        self,
        adb_controller: ADBController,
        macro_definition: dict,
        thresholds: dict = None,
        automation_settings: dict = None,
        debug_mode: bool = False,
        runtime_dir=None,
    ):
        self.adb = adb_controller
        self.macro_definition = macro_definition
        self.thresholds = thresholds or {}
        self.automation_settings = automation_settings or {}
        self.debug_mode = debug_mode
        self.resource_dir = get_resource_root()
        self.runtime_dir = Path(runtime_dir) if runtime_dir else get_runtime_root() / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.matcher = ImageMatcher(threshold=0.92)
        self.macro_settings = self.automation_settings.get("macro", {})
        self.items = self._build_items()
        self.buttons = self._build_buttons()
        self.timings = self.macro_settings.get("timings", {})
        self.screenshot_path = self.runtime_dir / "current_screen.png"
        self.paused = False
        self.user_action = None
        self.screen_width, self.screen_height = self.adb.get_screen_size()
        self.stats = {
            "total_refreshes": 0,
            "completed_runs": 0,
            "successful_refreshes": 0,
            "mystic_medal_bought": 0,
            "covenant_bookmark_bought": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_time": 0,
        }

    def _build_items(self) -> Dict[str, Dict[str, str]]:
        defaults = {
            "mystic_medal": {"image": "mystic_medal.png", "label": "신비의 메달"},
            "covenant_bookmark": {"image": "covenant_bookmark.PNG", "label": "성약의 책갈피"},
        }
        remote_items = self.macro_settings.get("items", {})
        if isinstance(remote_items, dict):
            for key, value in remote_items.items():
                if isinstance(value, dict):
                    merged = defaults.get(key, {}).copy()
                    merged.update(value)
                    defaults[key] = merged
        return defaults

    def _build_buttons(self) -> Dict[str, str]:
        defaults = {
            "refresh": "refresh_button.png",
            "refresh_confirm": "confirm_button.png",
            "purchase": "purchase_button.png",
            "buy": "buy_button.png",
            "purchase_disabled": "purchase_button_disabled.png",
        }
        remote_buttons = self.macro_settings.get("buttons", {})
        if isinstance(remote_buttons, dict):
            defaults.update(remote_buttons)
        return defaults

    def run(self, max_refresh_count: int, buy_count_per_item: int = 1) -> Dict:
        self.stats["start_time"] = time.time()
        macro_name = self.macro_definition.get("name", self.macro_definition.get("id", "macro"))
        logger.info("JSON 매크로 시작: %s", macro_name)
        if buy_count_per_item != 1:
            logger.info(
                "JSON steps 매크로는 '구매 완료 검증 횟수' 대신 각 step 구성을 사용합니다. 현재 입력값 %s는 실행 로직에 직접 반영되지 않습니다.",
                buy_count_per_item,
            )

        try:
            for run_index in range(max_refresh_count):
                if self._should_stop():
                    break
                self.stats["completed_runs"] = run_index + 1
                self.stats["total_refreshes"] = self.stats["completed_runs"]
                logger.info("=== JSON 매크로 실행 %s/%s ===", run_index + 1, max_refresh_count)
                if not self._execute_steps(self.macro_definition.get("steps", [])):
                    break
                self.stats["successful_refreshes"] += 1
        finally:
            self._finish_stats()

        logger.info("JSON 매크로 완료")
        return self.stats

    def _execute_steps(self, steps: list[dict]) -> bool:
        for step in steps:
            if self._should_stop():
                return False
            self._wait_if_paused()

            action = step.get("action")
            if action == "log":
                logger.info(step.get("message", ""))
            elif action == "wait":
                if not self._sleep_with_stop(float(step.get("seconds", 0))):
                    return False
            elif action == "screenshot":
                if not self._screenshot():
                    return False
            elif action == "tap_image":
                if not self._tap_image(step):
                    return False
            elif action == "swipe":
                if not self._swipe(step):
                    return False
            elif action == "repeat":
                count = int(step.get("count", 1))
                for _ in range(count):
                    if not self._execute_steps(step.get("steps", [])):
                        return False
            else:
                logger.error("지원하지 않는 JSON 액션: %s", action)
                return False
        return True

    def _tap_image(self, step: dict) -> bool:
        if not self._screenshot():
            logger.error("스크린샷에 실패해 tap_image 단계를 중지합니다.")
            return False
        image_path = self._resolve_image_path(step)
        required = bool(step.get("required", True))
        if not image_path:
            message = f"이미지 파일을 찾을 수 없음: {step.get('target') or step.get('image')}"
            if required:
                logger.error(message)
            else:
                logger.info(message)
            return not required

        threshold = self._resolve_threshold(step)
        result = self.matcher.find_image(str(self.screenshot_path), str(image_path), threshold=threshold)
        if not result:
            message = f"이미지를 찾을 수 없음: {image_path.name}"
            if required:
                logger.warning(message)
            else:
                logger.info(message)
            return not required

        center_x, center_y = self.matcher.get_center(result)
        if not self.adb.tap(center_x, center_y, delay=0.3):
            logger.error("입력 탭 명령이 실패했습니다: %s", image_path.name)
            return False
        logger.debug("JSON tap_image: %s (%s, %s)", image_path.name, center_x, center_y)
        return True

    def _screenshot(self) -> bool:
        self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.adb.screenshot(str(self.screenshot_path))
        time.sleep(float(self.timings.get("after_screenshot", 0.2)))
        return result

    def _swipe(self, step: dict) -> bool:
        defaults = self.automation_settings.get("swipe", {})
        x_ratio = float(step.get("x_ratio", defaults.get("x_ratio", 0.75)))
        start_y_ratio = float(step.get("start_y_ratio", defaults.get("start_y_ratio", 0.75)))
        end_y_ratio = float(step.get("end_y_ratio", defaults.get("end_y_ratio", 0.25)))
        duration_ms = int(step.get("duration_ms", defaults.get("duration_ms", 200)))

        x = int(self.screen_width * x_ratio)
        start_y = int(self.screen_height * start_y_ratio)
        end_y = int(self.screen_height * end_y_ratio)
        if not self.adb.swipe(x, start_y, x, end_y, duration=duration_ms, delay=0.5):
            logger.error("JSON swipe 단계가 실패했습니다.")
            return False
        return True

    def _resolve_image_path(self, step: dict) -> Optional[Path]:
        image = step.get("image")
        target = step.get("target")
        target_type = step.get("target_type")

        if not image and target:
            if target in self.buttons:
                image = self.buttons[target]
                target_type = "button"
            elif target in self.items:
                image = self.items[target].get("image")
                target_type = "item"

        if not image:
            return None

        directory = self.BUTTONS_DIR if target_type != "item" else self.ITEMS_DIR
        return self._find_image_file(self.resource_dir / directory, image)

    def _resolve_threshold(self, step: dict) -> float:
        if "threshold" in step:
            return float(step["threshold"]) / 100.0

        target = step.get("target", "")
        threshold_key = {
            "refresh": "refresh_button",
            "refresh_confirm": "refresh_button",
            "purchase": "purchase_button",
            "buy": "buy_button",
        }.get(target, target)
        default_threshold = 0.95 if threshold_key in {"mystic_medal", "covenant_bookmark"} else 0.92
        return float(self.thresholds.get(threshold_key, default_threshold))

    def _find_image_file(self, directory: Path, base_name: str) -> Optional[Path]:
        exact_path = directory / base_name
        if exact_path.exists():
            return exact_path
        if not directory.exists():
            return None
        base_name_lower = base_name.lower()
        for file in directory.iterdir():
            if file.is_file() and file.name.lower() == base_name_lower:
                return file
        return None

    def _wait_if_paused(self) -> None:
        while self.paused and self.user_action != "stop":
            time.sleep(0.1)

    def _sleep_with_stop(self, seconds: float) -> bool:
        end_time = time.time() + max(0.0, seconds)
        while time.time() < end_time:
            if self._should_stop():
                logger.info("⛔ 대기 중 중지 요청을 감지했습니다.")
                return False
            self._wait_if_paused()
            time.sleep(min(0.1, end_time - time.time()))
        return not self._should_stop()

    def _should_stop(self) -> bool:
        return self.user_action == "stop"

    def _finish_stats(self) -> None:
        if self.stats.get("start_time") and not self.stats.get("end_time"):
            self.stats["end_time"] = time.time()
            self.stats["elapsed_time"] = int(self.stats["end_time"] - self.stats["start_time"])

    def get_stats(self) -> Dict:
        return self.stats

    def set_user_action(self, action: str) -> None:
        if action == "pause":
            self.paused = True
            logger.info("⏸️  사용자가 일시정지를 요청했습니다.")
        elif action == "resume":
            self.paused = False
            self.user_action = None
            logger.info("▶️  사용자가 재개를 요청했습니다.")
        elif action == "stop":
            self.user_action = "stop"
            self.paused = False
            logger.info("⛔ 사용자가 중지를 요청했습니다.")
