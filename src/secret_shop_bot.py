"""
에픽세븐 비밀상점 자동화 매크로 핵심 로직

ADB 사용 이유:
- 비활성 매크로 구현 (매크로 동작 중 키보드/마우스 자유롭게 사용 가능)
- 앱플레이어와 독립적으로 동작
- 안정적인 화면 캡처 및 입력 제어
"""
import os
import sys
import time
import logging
from typing import Optional, Dict
from pathlib import Path

from .adb_controller import ADBController
from .image_matcher import ImageMatcher

logger = logging.getLogger(__name__)


def get_resource_root() -> Path:
    """Return the folder that contains bundled read-only resources."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def get_runtime_root() -> Path:
    """Return the writable folder next to the executable while bundled."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class SecretShopBot:
    """에픽세븐 비밀상점 자동화 봇"""
    
    # 이미지 파일 경로 (상대 경로)
    ITEMS_DIR = "images/items"
    BUTTONS_DIR = "images/buttons"
    
    # 구매할 아이템 이미지 파일명
    MYSTIC_MEDAL = "mystic_medal.png"  # 신비의 메달
    COVENANT_BOOKMARK = "covenant_bookmark.png"  # 성약의 책갈피
    
    # 버튼 이미지 파일명
    # 상점 갱신 프로세스: 갱신 버튼 -> 확인 버튼
    REFRESH_BUTTON = "refresh_button.png"  # 갱신 버튼 (상점 리프레시)
    REFRESH_CONFIRM_BUTTON = "confirm_button.png"  # 갱신 확인 버튼
    
    # 아이템 구매 프로세스: 구입 버튼 -> 구매 버튼
    PURCHASE_BUTTON = "purchase_button.png"  # 구입 버튼 (첫 번째 단계)
    BUY_BUTTON = "buy_button.png"  # 구매 버튼 (두 번째 단계, 최종 구매)
    PURCHASE_BUTTON_DISABLED = "purchase_button_disabled.png"  # 구매 완료 후 비활성화된 구입 버튼
    
    def _find_image_file(self, directory: Path, base_name: str) -> Optional[Path]:
        """
        대소문자 구분 없이 이미지 파일 찾기
        
        Args:
            directory: 디렉토리 경로
            base_name: 파일명 (확장자 포함)
            
        Returns:
            찾은 파일 경로 또는 None
        """
        # 정확한 파일명으로 먼저 찾기
        exact_path = directory / base_name
        if exact_path.exists():
            return exact_path

        if not directory.exists():
            logger.warning(f"이미지 폴더를 찾을 수 없음: {directory}")
            return None
        
        # 대소문자 구분 없이 찾기
        base_name_lower = base_name.lower()
        for file in directory.iterdir():
            if file.is_file() and file.name.lower() == base_name_lower:
                return file
        
        return None
    
    def __init__(
        self,
        adb_controller: ADBController,
        base_dir: str = None,
        thresholds: dict = None,
        debug_mode: bool = False,
        automation_settings: dict = None,
        runtime_dir = None,
    ):
        """
        Args:
            adb_controller: ADB 컨트롤러 인스턴스
            base_dir: 프로젝트 기본 디렉토리
            thresholds: 이미지별 매칭 임계값 딕셔너리 (기본값: 모두 0.92)
                {
                    "mystic_medal": 0.92,
                    "covenant_bookmark": 0.92,
                    "purchase_button": 0.92,
                    "buy_button": 0.92,
                    "refresh_button": 0.92,
                }
            debug_mode: 디버그 모드 (상세 로그 출력)
        """
        self.adb = adb_controller
        self.resource_dir = Path(base_dir) if base_dir else get_resource_root()
        self.runtime_dir = Path(runtime_dir) if runtime_dir else get_runtime_root() / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.debug_mode = debug_mode
        self.automation_settings = automation_settings or {}
        self.macro_settings = self.automation_settings.get("macro", {})
        self.item_definitions = self._build_item_definitions()
        self.enabled_items = self._build_enabled_items()
        self.button_images = self._build_button_images()
        self.timings = self.macro_settings.get("timings", {})
        self.macro_thresholds = self.macro_settings.get("thresholds", {})
        self.macro_layout = self.macro_settings.get("layout", {})
        
        # 이미지별 임계값 설정
        default_thresholds = {
            "mystic_medal": 0.95,
            "covenant_bookmark": 0.95,
            "purchase_button": 0.92,
            "buy_button": 0.92,
            "refresh_button": 0.92,
        }
        self.thresholds = thresholds if thresholds else default_thresholds
        
        # 기본 매칭 객체 (범용)
        self.matcher = ImageMatcher(threshold=0.92)
        
        # 스크린샷 임시 저장 경로
        self.screenshot_path = self.runtime_dir / "current_screen.png"
        
        # 통계
        self.stats = {
            "total_refreshes": 0,
            "completed_runs": 0,
            "successful_refreshes": 0,
            "mystic_medal_bought": 0,
            "covenant_bookmark_bought": 0,
            "total_cost": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_time": 0
        }
        for item in self.item_definitions.values():
            stat_key = item.get("stat_key")
            if stat_key:
                self.stats.setdefault(stat_key, 0)
        
        # 일시정지 제어
        self.paused = False
        self.user_action = None  # 'buy', 'refresh', 'stop'
        
        # 화면 스와이프 좌표 (화면 크기에 따라 조정 필요)
        # 기본 해상도: 1280x720 (240dpi)
        # 2번 구역(오른쪽 위) 중앙에서 위로 드래그
        self.screen_width, self.screen_height = self.adb.get_screen_size()
        logger.info(f"화면 해상도: {self.screen_width}x{self.screen_height}")
        
        swipe_settings = self.automation_settings.get("swipe", {})
        self.swipe_duration = int(swipe_settings.get("duration_ms", 200))
        self.swipe_x = int(self.screen_width * float(swipe_settings.get("x_ratio", 0.75)))
        self.swipe_start_y = int(self.screen_height * float(swipe_settings.get("start_y_ratio", 0.75)))
        self.swipe_end_y = int(self.screen_height * float(swipe_settings.get("end_y_ratio", 0.25)))

    def _build_item_definitions(self) -> Dict[str, Dict[str, str]]:
        defaults = {
            "mystic_medal": {
                "label": "신비의 메달",
                "image": self.MYSTIC_MEDAL,
                "stat_key": "mystic_medal_bought",
                "log_prefix": "신비의 메달",
            },
            "covenant_bookmark": {
                "label": "성약의 책갈피",
                "image": self.COVENANT_BOOKMARK,
                "stat_key": "covenant_bookmark_bought",
                "log_prefix": "성약의 책갈피",
            },
        }
        remote_items = self.macro_settings.get("items", {})
        if isinstance(remote_items, dict):
            for key, value in remote_items.items():
                if isinstance(value, dict):
                    merged = defaults.get(key, {}).copy()
                    merged.update(value)
                    defaults[key] = merged
        return defaults

    def _build_enabled_items(self) -> list:
        enabled = self.macro_settings.get("enabled_items", [])
        if isinstance(enabled, list):
            filtered = [item for item in enabled if item in self.item_definitions]
            if filtered:
                return filtered
        return ["mystic_medal", "covenant_bookmark"]

    def _build_button_images(self) -> Dict[str, str]:
        defaults = {
            "refresh": self.REFRESH_BUTTON,
            "refresh_confirm": self.REFRESH_CONFIRM_BUTTON,
            "purchase": self.PURCHASE_BUTTON,
            "buy": self.BUY_BUTTON,
            "purchase_disabled": self.PURCHASE_BUTTON_DISABLED,
        }
        remote_buttons = self.macro_settings.get("buttons", {})
        if isinstance(remote_buttons, dict):
            defaults.update(remote_buttons)
        return defaults

    def _timing(self, key: str, default: float) -> float:
        try:
            return float(self.timings.get(key, default))
        except (TypeError, ValueError):
            return default

    def _macro_threshold(self, key: str, default_percent: int) -> float:
        try:
            return float(self.macro_thresholds.get(key, default_percent)) / 100.0
        except (TypeError, ValueError):
            return default_percent / 100.0

    def _item_label(self, item_name: str) -> str:
        return self.item_definitions.get(item_name, {}).get("label", item_name)

    def _capture_screenshot(self, context: str) -> bool:
        screenshot_path = Path(self.screenshot_path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_path = screenshot_path
        if self.adb.screenshot(str(self.screenshot_path)):
            return True
        logger.error("스크린샷 촬영 실패: %s", context)
        return False
        
    def run(self, max_refresh_count: int, buy_count_per_item: int) -> Dict:
        """
        비밀상점 자동화 실행
        
        Args:
            max_refresh_count: 최대 리프레시 횟수
            buy_count_per_item: 아이템당 구매 횟수
            
        Returns:
            통계 정보 딕셔너리
        """
        import time as time_module
        
        # 시작 시간 기록
        self.stats["start_time"] = time_module.time()
        
        logger.info(f"비밀상점 자동화 시작 - 최대 리프레시: {max_refresh_count}회")
        
        for refresh_num in range(max_refresh_count):
            # 중지 요청 확인 (최우선)
            if self.user_action == 'stop':
                logger.info("⛔ 사용자가 중지를 선택했습니다.")
                return self._finish_stats()
            
            logger.info(f"=== 리프레시 {refresh_num + 1}/{max_refresh_count} ===")
            self.stats["completed_runs"] = refresh_num + 1
            self.stats["total_refreshes"] = self.stats["completed_runs"]
            
            # 일시정지 상태 확인
            while self.paused:
                time.sleep(0.1)  # 빠른 반응을 위해 0.1초로 감소
                if self.user_action == 'stop':
                    logger.info("⛔ 사용자가 중지를 선택했습니다.")
                    return self._finish_stats()
            
            # 상점 첫 페이지 스캔
            found_items = self._scan_shop_page(page_num=1)
            
            # 첫 페이지에서 아이템 발견 시 구매
            if found_items:
                logger.info(f"첫 페이지에서 아이템 발견: {list(found_items.keys())}")
                for item_name, item_location in found_items.items():
                    # 중지 요청 확인
                    if self.user_action == 'stop':
                        logger.info("⛔ 사용자가 중지를 선택했습니다.")
                        return self._finish_stats()
                    
                    logger.info(f"⭐ 아이템 발견: {item_name}")
                    if self._purchase_item(item_name, item_location, buy_count_per_item):
                        # 구매 성공 (통계는 _purchase_item 내부에서 업데이트됨)
                        pass
                    else:
                        # 구매 실패 (골드 부족 등) - 중지
                        logger.error("⚠️  구매 검증 실패! 골드 부족 가능성. 매크로를 중지합니다.")
                        return self._finish_stats()
            
            # 첫 페이지 처리 완료 → 드래그하여 두 번째 페이지로 이동
            logger.debug("두 번째 페이지로 이동")
            self._scroll_down()
            time.sleep(self._timing("after_scroll", 0.5))
            
            # 두 번째 페이지 스캔
            found_items = self._scan_shop_page(page_num=2)
            
            # 두 번째 페이지에서 아이템 발견 시 구매
            if found_items:
                logger.info(f"두 번째 페이지에서 아이템 발견: {list(found_items.keys())}")
                for item_name, item_location in found_items.items():
                    # 중지 요청 확인
                    if self.user_action == 'stop':
                        logger.info("⛔ 사용자가 중지를 선택했습니다.")
                        return self._finish_stats()
                    
                    logger.info(f"⭐ 아이템 발견: {item_name}")
                    if self._purchase_item(item_name, item_location, buy_count_per_item):
                        # 구매 성공 (통계는 _purchase_item 내부에서 업데이트됨)
                        pass
                    else:
                        # 구매 실패 (골드 부족 등) - 중지
                        logger.error("⚠️  구매 검증 실패! 골드 부족 가능성. 매크로를 중지합니다.")
                        return self._finish_stats()
            else:
                logger.debug("두 번째 페이지에도 아이템 없음")
            
            # 상점 리프레시
            if refresh_num < max_refresh_count - 1:  # 마지막 회차가 아니면
                if self._refresh_shop():
                    self.stats["successful_refreshes"] += 1
                    time.sleep(self._timing("after_refresh", 1.0))  # 리프레시 후 대기
                else:
                    logger.error("⚠️  상점 갱신에 실패했습니다. 다시 시도합니다...")
                    time.sleep(self._timing("refresh_retry", 2.0))  # 실패 시 조금 더 대기
        
        self._finish_stats()
        
        logger.info("비밀상점 자동화 완료")
        logger.info(
            "완료 요약 - 진행: %s회, 갱신 성공: %s회, 신비의 메달: %s개, 성약의 책갈피: %s개, 소요 시간: %s초",
            self.stats["completed_runs"],
            self.stats["successful_refreshes"],
            self.stats["mystic_medal_bought"],
            self.stats["covenant_bookmark_bought"],
            self.stats["elapsed_time"],
        )
        
        return self.stats

    def _finish_stats(self) -> Dict:
        """종료 시각과 소요 시간을 기록하고 통계를 반환합니다."""
        import time as time_module

        if self.stats.get("start_time") and not self.stats.get("end_time"):
            self.stats["end_time"] = time_module.time()
            self.stats["elapsed_time"] = int(self.stats["end_time"] - self.stats["start_time"])
        return self.stats
    
    def _scan_shop_page(self, page_num: int = 1) -> Dict[str, tuple]:
        """
        현재 상점 페이지 스캠
        
        Returns:
            발견한 아이템 딕셔너리 {아이템명: (x, y, w, h)}
        """
        # 중지 확인
        if self.user_action == 'stop':
            return {}
        
        # 스크린샷 촬영
        if not self._capture_screenshot(f"상점 스캔 {page_num}페이지"):
            return {}
        time.sleep(self._timing("after_screenshot", 0.3))
        
        found_items = {}
        
        for item_name in self.enabled_items:
            item = self.item_definitions.get(item_name, {})
            image_name = item.get("image", f"{item_name}.png")
            image_path = self._find_image_file(self.resource_dir / self.ITEMS_DIR, image_name)
            if not image_path:
                logger.warning(f"⚠️ {self._item_label(item_name)} 이미지 파일을 찾을 수 없음: {image_name} - 이 아이템은 검색하지 않습니다")
                continue

            result = self.matcher.find_image(
                str(self.screenshot_path),
                str(image_path),
                threshold=self.thresholds.get(item_name, 0.92),
            )
            if result:
                found_items[item_name] = result
                similarity = self.matcher.get_similarity_at_location(
                    str(self.screenshot_path),
                    str(image_path),
                    result,
                )
                logger.info(
                    f"⭐ {self._item_label(item_name)} 발견: {result} (매칭률: {similarity * 100:.1f}%)"
                )
        
        if found_items:
            logger.info(f"🔍 스캔 완료 - 발견한 아이템: {list(found_items.keys())}")
        else:
            logger.info(f"🔍 스캔 완료 ({page_num}페이지) - 아이템 없음")
        
        return found_items
    
    def _purchase_item(self, item_name: str, item_location: tuple, verification_count: int) -> bool:
        """
        아이템 구매 (구입 -> 구매 2단계 프로세스) 및 구매 완료 검증
        
        Args:
            item_name: 아이템 이름 (통계 업데이트용)
            item_location: 아이템 위치 (x, y, w, h)
            verification_count: 구매 완료 검증 횟수 (비활성화 버튼 확인 반복 횟수)
            
        Returns:
            구매 성공 여부
        """
        # 중지 확인
        if self.user_action == 'stop':
            logger.info("⛔ 중지 요청 - 구매 중단")
            return False
        
        # 1단계: 아이템과 같은 라인의 오른쪽에 있는 구입 버튼 찾기 및 클릭
        purchase_btn = self._find_purchase_button_on_item_line(item_location)
        if purchase_btn is False:
            # 비활성화된 버튼 (이미 구매한 아이템) - 조용히 건너뛰기
            logger.debug("비활성화된 버튼이므로 구매 건너뜀")
            return True  # 성공으로 처리 (이미 구매했으므로)
        elif purchase_btn is None:
            logger.warning("구입 버튼(1단계)을 찾을 수 없음")
            return False
            
        # 중지 확인
        if self.user_action == 'stop':
            logger.info("⛔ 중지 요청 - 구매 중단")
            return False
        
        # 구입 버튼 클릭
        btn_center_x, btn_center_y = self.matcher.get_center(purchase_btn)
        logger.info(
            "구입 버튼 탭 - 아이템: %s, 아이템 영역: %s, 버튼 영역: %s, 좌표: (%s, %s)",
            item_name,
            item_location,
            purchase_btn,
            btn_center_x,
            btn_center_y,
        )
        self.adb.tap(btn_center_x, btn_center_y, delay=0.5)
        time.sleep(self._timing("after_purchase_tap", 0.5))  # 구매 팝업이 뜰 때까지 대기
        
        # 중지 확인
        if self.user_action == 'stop':
            logger.info("⛔ 중지 요청 - 구매 중단")
            # 화면 닫기
            self.adb.tap(self.screen_width // 4, self.screen_height // 2, delay=self._timing("close_popup_delay", 0.3))
            return False
        
        # 구매 버튼이 나타날 때까지 대기 (최대 2초)
        buy_button_found = False
        buy_button_wait_attempts = int(self.timings.get("buy_button_wait_attempts", 4))
        wait_interval = self._timing("buy_button_wait_interval", 0.5)
        for wait_attempt in range(buy_button_wait_attempts):
            if not self._capture_screenshot(f"구매 버튼 대기 - {item_name}"):
                return False
            time.sleep(self._timing("after_screenshot", 0.2))
            
            buy_button_path = self._find_image_file(self.resource_dir / self.BUTTONS_DIR, self.button_images["buy"])
            if buy_button_path:
                result = self.matcher.find_image(
                    str(self.screenshot_path),
                    str(buy_button_path),
                    threshold=self.thresholds.get("buy_button", 0.92),
                )
                if result:
                    buy_button_found = True
                    logger.debug(f"구매 버튼 발견 (대기 시간: {wait_attempt * wait_interval}초)")
                    break
            
            if wait_attempt < buy_button_wait_attempts - 1:  # 마지막 시도가 아니면 대기
                time.sleep(wait_interval)
        
        if not buy_button_found:
            logger.warning("⚠️ 구매 버튼이 나타나지 않음 - 구매 팝업 로딩 실패")
            # 화면 닫기
            self.adb.tap(self.screen_width // 4, self.screen_height // 2, delay=self._timing("close_popup_delay", 0.3))
            return False
        
        # 2단계: 구매 버튼 클릭 (최종 구매)
        if self._click_button("buy"):
            # 구매 버튼 클릭 성공 - 통계 즉시 업데이트
            stat_key = self.item_definitions.get(item_name, {}).get("stat_key")
            if stat_key:
                self.stats[stat_key] = self.stats.get(stat_key, 0) + 1
                logger.info(f"📊 {self._item_label(item_name)} 구매 카운트 +1")
            
            time.sleep(self._timing("after_purchase_tap", 0.5))
            
            # 구매 완료 검증: 비활성화된 구입 버튼 확인 (여러 번 검증)
            verification_success = 0
            for verify_attempt in range(verification_count):
                if self._verify_purchase_complete():
                    verification_success += 1
                    logger.debug(f"검증 성공 ({verify_attempt + 1}/{verification_count})")
                else:
                    logger.debug(f"검증 실패 ({verify_attempt + 1}/{verification_count})")
                
                # 마지막 시도가 아니면 잠시 대기 후 재확인
                if verify_attempt < verification_count - 1:
                    time.sleep(self._timing("verify_interval", 0.3))
            
            # 과반수 이상 성공하면 구매 성공으로 판단
            if verification_success > verification_count // 2:
                logger.info(f"✅ 구매 완료 검증 성공 ({verification_success}/{verification_count} 성공)")
                # 화면 닫기
                self.adb.tap(self.screen_width // 4, self.screen_height // 2, delay=self._timing("close_popup_delay", 0.3))
                return True
            else:
                logger.warning(f"⚠️  구매 완료 검증 실패 ({verification_success}/{verification_count} 성공) - 골드 부족 또는 구매 실패 가능성")
                # 화면 왼쪽 클릭하여 창 닫기
                self.adb.tap(self.screen_width // 4, self.screen_height // 2, delay=self._timing("close_popup_delay", 0.3))
                return False
        else:
            logger.warning("구매 버튼(2단계)을 찾을 수 없음")
            # 취소 또는 뒤로가기 처리
            self.adb.tap(self.screen_width // 4, self.screen_height // 2, delay=self._timing("close_popup_delay", 0.3))
            return False
    
    def _find_purchase_button_on_item_line(self, item_location: tuple):
        """
        아이템과 같은 라인(비슷한 Y 좌표)의 오른쪽에 있는 구입 버튼 찾기
        활성화/비활성화 이미지 유사도를 비교하여 판단
        
        Args:
            item_location: 아이템 위치 (x, y, w, h)
            
        Returns:
            tuple: 구입 버튼 위치 (x, y, w, h) - 활성화된 버튼
            False: 비활성화된 버튼 (이미 구매한 아이템)
            None: 버튼을 찾을 수 없음
        """
        # 스크린샷 촬영
        if not self._capture_screenshot("구입 버튼 탐색"):
            return None
        time.sleep(self._timing("after_screenshot", 0.2))
        
        # 구입 버튼 이미지 경로 (활성화)
        purchase_button_path = self._find_image_file(
            self.resource_dir / self.BUTTONS_DIR,
            self.button_images["purchase"],
        )
        
        if not purchase_button_path:
            logger.debug("구입 버튼 이미지 파일을 찾을 수 없음")
            return None
        
        # 비활성화된 구입 버튼 이미지 경로
        purchase_button_disabled_path = self._find_image_file(
            self.resource_dir / self.BUTTONS_DIR,
            self.button_images["purchase_disabled"],
        )
        
        if not purchase_button_disabled_path:
            logger.warning("비활성화된 구입 버튼 이미지를 찾을 수 없음 - 기존 방식으로 동작")
            # 기존 방식: 활성화된 버튼만 찾기
            all_buttons = self.matcher.find_all_images(
                str(self.screenshot_path),
                str(purchase_button_path),
                threshold=self.thresholds.get("purchase_button", 0.92),
            )
            if not all_buttons:
                return None
            
            item_x, item_y, item_w, item_h = item_location
            item_center_y = item_y + item_h // 2
            y_tolerance = int(self.macro_layout.get("purchase_line_y_tolerance", 50))
            
            for button in all_buttons:
                btn_x, btn_y, btn_w, btn_h = button
                btn_center_y = btn_y + btn_h // 2
                if abs(btn_center_y - item_center_y) <= y_tolerance and btn_x > item_x:
                    return button
            return None
        
        # 화면에서 모든 구입 버튼 후보 찾기 (활성화 + 비활성화 모두)
        # 임계값을 낮춰서 모든 후보를 찾음
        candidate_threshold = self._macro_threshold("purchase_candidate", 70)
        all_active_buttons = self.matcher.find_all_images(
            str(self.screenshot_path),
            str(purchase_button_path),
            threshold=candidate_threshold,
        )
        all_disabled_buttons = self.matcher.find_all_images(
            str(self.screenshot_path),
            str(purchase_button_disabled_path),
            threshold=candidate_threshold,
        )
        
        # 모든 버튼 후보 합치기
        all_button_candidates = list(set(all_active_buttons + all_disabled_buttons))
        
        if not all_button_candidates:
            logger.debug("구입 버튼 후보를 찾을 수 없음")
            return None
        
        # 아이템의 Y 좌표
        item_x, item_y, item_w, item_h = item_location
        item_center_y = item_y + item_h // 2
        
        # 같은 라인에 있는 버튼 찾기 (약간의 여유 있게 ±50 픽셀)
        y_tolerance = int(self.macro_layout.get("purchase_line_y_tolerance", 50))
        
        for button in all_button_candidates:
            btn_x, btn_y, btn_w, btn_h = button
            btn_center_y = btn_y + btn_h // 2
            
            # Y 좌표가 비슷하고, 아이템보다 오른쪽에 있는 버튼
            if abs(btn_center_y - item_center_y) <= y_tolerance and btn_x > item_x:
                # 활성화/비활성화 이미지 유사도 비교
                active_similarity = self.matcher.get_similarity_at_location(
                    str(self.screenshot_path), 
                    str(purchase_button_path), 
                    button
                )
                disabled_similarity = self.matcher.get_similarity_at_location(
                    str(self.screenshot_path), 
                    str(purchase_button_disabled_path), 
                    button
                )
                
                logger.debug(f"버튼 ({btn_x}, {btn_y}) - 활성화: {active_similarity:.3f}, 비활성화: {disabled_similarity:.3f}")
                
                # 비활성화 이미지가 더 유사하면 비활성화된 버튼
                if disabled_similarity > active_similarity:
                    logger.info(f"⏭️  이미 구매한 아이템 건너뜀 (비활성화 유사도: {disabled_similarity:.3f} > 활성화: {active_similarity:.3f})")
                    return False
                else:
                    # 활성화 이미지가 더 유사하면 활성화된 버튼
                    logger.debug(f"같은 라인의 활성화된 구입 버튼 발견 (활성화 유사도: {active_similarity:.3f} > 비활성화: {disabled_similarity:.3f})")
                    return button
        
        logger.warning("아이템과 같은 라인의 구입 버튼을 찾을 수 없음")
        return None
    
    def _refresh_shop(self) -> bool:
        """상점 리프레시 (갱신 -> 확인 2단계 프로세스)
        
        Returns:
            성공 여부
        """
        logger.debug("상점 갱신 시작")
        
        # 중지 확인
        if self.user_action == 'stop':
            logger.debug("중지 요청으로 갱신 건너뜀")
            return False
        
        # 1단계: 갱신 버튼 찾기 및 클릭
        if self._click_button("refresh"):
            # 2단계: 확인 버튼이 실제로 뜰 때까지 잠시 재시도
            if self._click_button_with_retry(
                "refresh_confirm",
                attempts=int(self.timings.get("refresh_confirm_attempts", 5)),
                initial_delay=self._timing("refresh_confirm_delay", 0.5),
                retry_interval=self._timing("refresh_confirm_retry_interval", 0.3),
            ):
                logger.info("✅ 상점 갱신 성공")
                time.sleep(self._timing("after_refresh", 0.8))
                return True
            else:
                # 중지 요청이면 로그 생략
                if self.user_action != 'stop':
                    logger.warning("⚠️  갱신 확인 버튼을 찾을 수 없음")
                return False
        else:
            # 중지 요청이면 로그 생략
            if self.user_action != 'stop':
                logger.error("❌ 갱신 버튼을 찾을 수 없음")
                if self.debug_mode:
                    logger.error(f"💡 디버깅: 스크린샷이 {self.screenshot_path}에 저장되었습니다.")
                    logger.error(f"💡 버튼 이미지: {self.resource_dir / self.BUTTONS_DIR / self.REFRESH_BUTTON}")
                    logger.error(f"💡 이미지 매칭 정확도를 낮춰보세요 (현재: {int(self.matcher.threshold*100)}%)")
                    
                    # 디버깅용 스크린샷 저장
                    debug_path = self.runtime_dir / "debug_refresh_button.png"
                    debug_path.parent.mkdir(exist_ok=True)
                    import shutil
                    shutil.copy(self.screenshot_path, debug_path)
                    logger.error(f"💡 디버그 스크린샷: {debug_path}")
            return False

    def _click_button_with_retry(
        self,
        button_type: str,
        attempts: int = 1,
        initial_delay: float = 0.0,
        retry_interval: float = 0.0,
    ) -> bool:
        attempts = max(1, int(attempts))
        if initial_delay > 0:
            time.sleep(initial_delay)

        for attempt in range(attempts):
            if self.user_action == "stop":
                return False
            if self._click_button(button_type):
                return True
            if attempt < attempts - 1 and retry_interval > 0:
                time.sleep(retry_interval)
        return False
    
    def _click_button(self, button_type: str) -> bool:
        """
        버튼 찾기 및 클릭
        
        Args:
            button_type: 버튼 타입
                - "refresh": 갱신 버튼 (상점 리프레시 시작)
                - "refresh_confirm": 갱신 확인 버튼 (상점 리프레시 확인)
                - "purchase": 구입 버튼 (아이템 구매 1단계)
                - "buy": 구매 버튼 (아이템 구매 2단계, 최종 구매)
            
        Returns:
            클릭 성공 여부
        """
        # 중지 확인
        if self.user_action == 'stop':
            return False
        
        # 스크린샷 촬영
        if not self._capture_screenshot(f"버튼 탐색 - {button_type}"):
            return False
        time.sleep(self._timing("after_screenshot", 0.2))
        
        # 버튼 이미지 경로 선택
        button_filename = self.button_images.get(button_type)
        
        if not button_filename:
            logger.error(f"알 수 없는 버튼 타입: {button_type}")
            return False
        
        button_path = self._find_image_file(self.resource_dir / self.BUTTONS_DIR, button_filename)
        
        if not button_path:
            logger.error(f"버튼 이미지 파일을 찾을 수 없음: {button_filename}")
            return False
        
        # 버튼 찾기
        # 버튼 타입에 따라 임계값 선택
        threshold_key = {
            "refresh": "refresh_button",
            "refresh_confirm": "refresh_button",
            "purchase": "purchase_button",
            "buy": "buy_button",
        }.get(button_type, "buy_button")
        threshold = self.thresholds.get(threshold_key, 0.92)
        result = self.matcher.find_image(str(self.screenshot_path), str(button_path), threshold=threshold)
        
        if result:
            # 버튼 중심 클릭
            center_x, center_y = self.matcher.get_center(result)
            self.adb.tap(center_x, center_y, delay=0.3)
            logger.debug(f"{button_type} 버튼 클릭: ({center_x}, {center_y})")
            return True
        else:
            logger.debug(f"{button_type} 버튼을 찾을 수 없음")
            return False
    
    def _verify_purchase_complete(self) -> bool:
        """
        구매 완료 검증: 비활성화된 구입 버튼 확인
        
        Returns:
            구매 완료 여부 (비활성화된 버튼이 보이면 True)
        """
        # 스크린샷 촬영
        if not self._capture_screenshot("구매 완료 검증"):
            return False
        time.sleep(self._timing("after_screenshot", 0.2))
        
        # 비활성화된 구입 버튼 찾기 (약간 낮은 임계값 사용)
        disabled_button_path = self._find_image_file(
            self.resource_dir / self.BUTTONS_DIR,
            self.button_images["purchase_disabled"],
        )
        
        if not disabled_button_path:
            logger.warning("비활성화된 구입 버튼 이미지 파일을 찾을 수 없음")
            return False
        
        result = self.matcher.find_image(
            str(self.screenshot_path),
            str(disabled_button_path),
            threshold=self._macro_threshold("verification_disabled_button", 85),
        )
        
        if result:
            logger.debug("구매 완료: 비활성화된 구입 버튼 확인됨")
            return True
        else:
            logger.debug("구매 완료 검증 실패: 비활성화된 구입 버튼을 찾을 수 없음")
            return False
    
    def _scroll_down(self):
        """화면을 위로 스크롤 (두 번째 페이지로 이동)"""
        logger.info(
            "화면 스크롤 시도 1/1 - (%s, %s) -> (%s, %s), duration=%sms",
            self.swipe_x,
            self.swipe_start_y,
            self.swipe_x,
            self.swipe_end_y,
            self.swipe_duration,
        )

        success = self.adb.swipe(
            self.swipe_x,
            self.swipe_start_y,
            self.swipe_x,
            self.swipe_end_y,
            duration=self.swipe_duration,
            delay=0.5,
        )

        if success:
            logger.info("화면 스크롤 시도 1/1 성공")
        else:
            logger.warning("화면 스크롤 시도 1/1 실패")

        logger.info("화면 스크롤 1회 시도 완료")
    
    def set_user_action(self, action: str):
        """
        사용자 액션 설정 (GUI에서 호출)
        
        Args:
            action: 'pause' (일시정지), 'resume' (재개), 'stop' (중지)
        """
        if action == 'pause':
            self.paused = True
            logger.info("⏸️  사용자가 일시정지를 요청했습니다.")
        elif action == 'resume':
            self.paused = False
            self.user_action = None
            logger.info("▶️  사용자가 재개를 요청했습니다.")
        elif action == 'stop':
            self.user_action = 'stop'
            self.paused = False
            logger.info("⛔ 사용자가 중지를 요청했습니다.")
    
    def get_stats(self) -> Dict:
        """통계 정보 반환"""
        return self.stats.copy()
