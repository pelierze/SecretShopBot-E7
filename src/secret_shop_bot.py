"""
에픽세븐 비밀상점 자동화 매크로 핵심 로직

ADB 사용 이유:
- 비활성 매크로 구현 (매크로 동작 중 키보드/마우스 자유롭게 사용 가능)
- 앱플레이어와 독립적으로 동작
- 안정적인 화면 캡처 및 입력 제어
"""
import os
import time
import logging
from typing import Optional, Dict
from pathlib import Path

from .adb_controller import ADBController
from .image_matcher import ImageMatcher

logger = logging.getLogger(__name__)


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
    
    def __init__(self, adb_controller: ADBController, base_dir: str = "."):
        """
        Args:
            adb_controller: ADB 컨트롤러 인스턴스
            base_dir: 프로젝트 기본 디렉토리
        """
        self.adb = adb_controller
        self.matcher = ImageMatcher(threshold=0.8)
        self.base_dir = Path(base_dir)
        
        # 스크린샷 임시 저장 경로
        self.screenshot_path = self.base_dir / "logs" / "current_screen.png"
        
        # 통계
        self.stats = {
            "total_refreshes": 0,
            "mystic_medal_bought": 0,
            "covenant_bookmark_bought": 0,
            "total_cost": 0
        }
        
        # 일시정지 제어
        self.paused = False
        self.user_action = None  # 'buy', 'refresh', 'stop'
        
        # 화면 스와이프 좌표 (화면 크기에 따라 조정 필요)
        # 기본 해상도: 1280x720 (240dpi)
        self.screen_width, self.screen_height = self.adb.get_screen_size()
        logger.info(f"화면 해상도: {self.screen_width}x{self.screen_height}")
        
        self.swipe_start_y = int(self.screen_height * 0.6)
        self.swipe_end_y = int(self.screen_height * 0.3)
        self.swipe_x = int(self.screen_width * 0.5)
        
    def run(self, max_refresh_count: int, buy_count_per_item: int) -> Dict:
        """
        비밀상점 자동화 실행
        
        Args:
            max_refresh_count: 최대 리프레시 횟수
            buy_count_per_item: 아이템당 구매 횟수
            
        Returns:
            통계 정보 딕셔너리
        """
        logger.info(f"비밀상점 자동화 시작 - 최대 리프레시: {max_refresh_count}회")
        
        for refresh_num in range(max_refresh_count):
            logger.info(f"=== 리프레시 {refresh_num + 1}/{max_refresh_count} ===")
            
            # 일시정지 상태 확인
            while self.paused:
                time.sleep(0.5)
                if self.user_action == 'stop':
                    logger.info("사용자가 중지를 선택했습니다.")
                    return self.stats
            
            # 상점 첫 페이지 스캔
            found_items = self._scan_shop_page()
            
            # 상점 두 번째 페이지로 이동 (드래그)
            if not found_items:
                logger.debug("첫 페이지에서 아이템 없음, 두 번째 페이지로 이동")
                self._scroll_down()
                time.sleep(0.5)
                
                # 두 번째 페이지 스캔
                found_items = self._scan_shop_page()
            
            # 발견한 아이템 자동 구매
            if found_items:
                purchase_success = False
                for item_name, item_location in found_items.items():
                    logger.info(f"⭐ 아이템 발견: {item_name}")
                    if self._purchase_item(item_location, buy_count_per_item):
                        # 통계 업데이트
                        if item_name == "mystic_medal":
                            self.stats["mystic_medal_bought"] += buy_count_per_item
                        elif item_name == "covenant_bookmark":
                            self.stats["covenant_bookmark_bought"] += buy_count_per_item
                        purchase_success = True
                    else:
                        # 구매 실패 (골드 부족 등) - 중지
                        logger.error("⚠️  구매 검증 실패! 골드 부족 가능성. 매크로를 중지합니다.")
                        return self.stats
            else:
                logger.debug("원하는 아이템이 없음")
            
            # 상점 리프레시
            if refresh_num < max_refresh_count - 1:  # 마지막 회차가 아니면
                self._refresh_shop()
                self.stats["total_refreshes"] += 1
                time.sleep(1)  # 리프레시 후 대기
        
        logger.info("비밀상점 자동화 완료")
        logger.info(f"통계: {self.stats}")
        
        return self.stats
    
    def _scan_shop_page(self) -> Dict[str, tuple]:
        """
        현재 상점 페이지 스캔
        
        Returns:
            발견한 아이템 딕셔너리 {아이템명: (x, y, w, h)}
        """
        # 스크린샷 촬영
        self.adb.screenshot(str(self.screenshot_path))
        time.sleep(0.3)
        
        found_items = {}
        
        # 신비의 메달 검색
        mystic_medal_path = self.base_dir / self.ITEMS_DIR / self.MYSTIC_MEDAL
        result = self.matcher.find_image(str(self.screenshot_path), str(mystic_medal_path))
        if result:
            found_items["mystic_medal"] = result
            logger.debug(f"신비의 메달 발견: {result}")
        
        # 성약의 책갈피 검색
        covenant_bookmark_path = self.base_dir / self.ITEMS_DIR / self.COVENANT_BOOKMARK
        result = self.matcher.find_image(str(self.screenshot_path), str(covenant_bookmark_path))
        if result:
            found_items["covenant_bookmark"] = result
            logger.debug(f"성약의 책갈피 발견: {result}")
        
        return found_items
    
    def _purchase_item(self, item_location: tuple, count: int) -> bool:
        """
        아이템 구매 (구입 -> 구매 2단계 프로세스) 및 구매 완료 검증
        
        Args:
            item_location: 아이템 위치 (x, y, w, h)
            count: 구매 횟수
            
        Returns:
            구매 성공 여부 (모든 구매가 성공했는지)
        """
        # 아이템 위치의 중심점 계산
        center_x, center_y = self.matcher.get_center(item_location)
        
        all_success = True
        
        for i in range(count):
            logger.info(f"구매 시도 {i + 1}/{count}")
            
            # 아이템 클릭
            self.adb.tap(center_x, center_y, delay=0.5)
            
            # 1단계: 구입 버튼 클릭
            if self._click_button("purchase"):
                time.sleep(0.3)
                
                # 2단계: 구매 버튼 클릭 (최종 구매)
                if self._click_button("buy"):
                    time.sleep(0.5)
                    
                    # 구매 완료 검증: 비활성화된 구입 버튼 확인
                    if self._verify_purchase_complete():
                        logger.info(f"✅ 구매 완료 검증 성공 ({i + 1}/{count})")
                    else:
                        logger.warning(f"⚠️  구매 완료 검증 실패 ({i + 1}/{count}) - 골드 부족 또는 구매 실패 가능성")
                        all_success = False
                        # 화면 왼쪽 클릭하여 창 닫기
                        self.adb.tap(center_x // 2, center_y, delay=0.3)
                        break
                else:
                    logger.warning("구매 버튼(2단계)을 찾을 수 없음")
                    all_success = False
                    # 취소 또는 뒤로가기 처리
                    self.adb.tap(center_x // 2, center_y, delay=0.3)  # 화면 왼쪽 클릭 (취소)
                    break
            else:
                logger.warning("구입 버튼(1단계)을 찾을 수 없음")
                all_success = False
                break
            
            # 화면 닫기 (다음 구매를 위해)
            self.adb.tap(center_x // 2, center_y, delay=0.3)
            time.sleep(0.5)  # 구매 간 대기
        
        return all_success
    
    def _refresh_shop(self):
        """상점 리프레시 (갱신 -> 확인 2단계 프로세스)"""
        logger.debug("상점 갱신 시작")
        
        # 1단계: 갱신 버튼 찾기 및 클릭
        if self._click_button("refresh"):
            time.sleep(0.5)
            
            # 2단계: 확인 버튼 클릭
            if self._click_button("refresh_confirm"):
                logger.info("상점 갱신 완료")
                time.sleep(0.8)
            else:
                logger.warning("갱신 확인 버튼을 찾을 수 없음")
        else:
            logger.error("갱신 버튼을 찾을 수 없음")
    
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
        # 스크린샷 촬영
        self.adb.screenshot(str(self.screenshot_path))
        time.sleep(0.2)
        
        # 버튼 이미지 경로 선택
        button_filename = {
            "refresh": self.REFRESH_BUTTON,
            "refresh_confirm": self.REFRESH_CONFIRM_BUTTON,
            "purchase": self.PURCHASE_BUTTON,
            "buy": self.BUY_BUTTON
        }.get(button_type)
        
        if not button_filename:
            logger.error(f"알 수 없는 버튼 타입: {button_type}")
            return False
        
        button_path = self.base_dir / self.BUTTONS_DIR / button_filename
        
        # 버튼 찾기
        result = self.matcher.find_image(str(self.screenshot_path), str(button_path))
        
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
        self.adb.screenshot(str(self.screenshot_path))
        time.sleep(0.2)
        
        # 비활성화된 구입 버튼 찾기
        disabled_button_path = self.base_dir / self.BUTTONS_DIR / self.PURCHASE_BUTTON_DISABLED
        result = self.matcher.find_image(str(self.screenshot_path), str(disabled_button_path), threshold=0.75)
        
        if result:
            logger.debug("구매 완료: 비활성화된 구입 버튼 확인됨")
            return True
        else:
            logger.debug("구매 완료 검증 실패: 비활성화된 구입 버튼을 찾을 수 없음")
            return False
    
    def _scroll_down(self):
        """화면을 아래로 스크롤 (두 번째 페이지로 이동)"""
        self.adb.swipe(
            self.swipe_x, self.swipe_start_y,
            self.swipe_x, self.swipe_end_y,
            duration=300,
            delay=0.5
        )
        logger.debug("화면 스크롤 (하단으로)")
    
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
