"""Bounded, stoppable hero recruitment ending before exploration entry."""

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path

from src.image_matcher import read_image
from .observer import KnightObserver, RecruitmentObserver

logger = logging.getLogger(__name__)


class _Stopped(Exception):
    pass


class PartyCostExceededError(RuntimeError):
    """Raised when hero recruitment fails due to exceeding party cost or missing hero."""
    def __init__(self, hero_name, class_id=None, fallback_hero=None, message=None):
        self.hero_name = hero_name
        self.class_id = class_id
        self.fallback_hero = fallback_hero
        default_msg = f"'{hero_name}' 목록 미노출 (영웅 미소지 또는 파티 코스트 초과)"
        super().__init__(message or default_msg)


class KnightRecruitmentBot:
    def __init__(self, adb_controller, resource_root, runtime_dir, observer=None):
        self.adb = adb_controller
        self.observer = observer or KnightObserver(resource_root)
        self.stop_event = threading.Event()
        Path(runtime_dir).mkdir(parents=True, exist_ok=True)
        self.runtime_dir = Path(tempfile.mkdtemp(prefix="chaos_recruitment_", dir=str(runtime_dir)))
        self.screen_path = self.runtime_dir / "current.png"
        self.stats = {"phase": "준비", "status": "ready", "reason": "", "clicks": 0}
        self.sequence = 0
        self.hero_name = "그림자 로제"
        self.completion_phase = "그림자 로제 영입 완료"
        self.completion_reason = "기사 영입 완료 후 종료"

    def set_user_action(self, action):
        if action == "stop":
            self.stop_event.set()

    def get_stats(self):
        return dict(self.stats)

    def _check_stop(self):
        if self.stop_event.is_set():
            raise _Stopped()

    def _capture(self):
        self._check_stop()
        if not self.adb.screenshot(str(self.screen_path)):
            raise RuntimeError("화면 캡처 실패 — 이전 화면으로 입력하지 않습니다.")
        self._check_stop()
        screen = read_image(str(self.screen_path))
        self.observer.validate_screen(screen)
        return screen

    def _record(self, label):
        if self.screen_path.exists():
            self.sequence += 1
            shutil.copyfile(self.screen_path, self.runtime_dir / f"{self.sequence:02d}_{label}.png")

    def _wait(self, phase, predicate):
        self.stats["phase"] = phase
        logger.info("자동 탐사: %s", phase)
        deadline = time.monotonic() + self.observer.config["timeout_seconds"]
        previous, count = None, 0
        while time.monotonic() < deadline:
            value = predicate(self._capture())
            self._check_stop()
            if value is not None:
                # Stable outcomes must refer to the same position, not just any match.
                if value == previous:
                    count += 1
                else:
                    previous, count = value, 1
                if count >= self.observer.config["stable_frames"]:
                    self._record("observed")
                    return value
            else:
                previous, count = None, 0
            if self.stop_event.wait(self.observer.config["poll_seconds"]):
                raise _Stopped()
        raise RuntimeError(f"{phase}: 대기 시간 초과. 화면 또는 대상 영웅을 확인해 주세요.")

    def _tap(self, bounds):
        self._check_stop()
        x, y, w, h = bounds
        px, py = int(x + w // 2), int(y + h // 2)
        if not (0 <= px < 1280 and 0 <= py < 720):
            raise RuntimeError("클릭 좌표가 화면 밖입니다.")
        self._record("before_input")
        if not self.adb.tap(px, py, delay=0):
            raise RuntimeError("ADB 입력 실패 — 중복 입력하지 않고 중지합니다.")
        self.stats["clicks"] += 1
        logger.info("자동 탐사 입력: (%s, %s)", px, py)
        if self.stop_event.wait(self.observer.config["poll_seconds"]):
            raise _Stopped()

    def _point(self, name):
        x, y = self.observer.config[name]
        self._tap((x, y, 0, 0))

    def _entry(self, screen):
        if self.observer.completed(screen):
            return ("done",)
        button = self.observer.find(screen, "start")
        return ("start", *button) if button else None

    def _theme_ready(self, screen):
        if self.observer.find(screen, "unlock"):
            return ("popup",)
        theme = self.observer.theme.observe(screen)
        return (theme.state, *theme.bounds) if theme.bounds else None

    def _theme_confirm(self, screen):
        if self.observer.theme.observe(screen).state == "selected":
            return self.observer.find(screen, "confirm_theme")
        return None

    def _filter_button(self, screen):
        if self.observer.find(screen, "knight_header") and not self.observer.find(screen, "filter_panel"):
            return self.observer.find(screen, "filter")
        return None

    def _element_state(self, screen):
        if not self.observer.find(screen, "knight_header") or not self.observer.find(screen, "filter_panel"):
            return None
        for other in ("fire_2", "ice_2", "forest_2", "light_2"):
            if self.observer.find(screen, other):
                raise RuntimeError("다른 속성이 이미 선택되어 있습니다. 필터를 초기화한 뒤 다시 실행해 주세요.")
        selected = self.observer.find(screen, "dark_2")
        plain = self.observer.find(screen, "dark_1")
        if selected and not plain:
            return ("selected", *selected)
        if plain and not selected:
            return ("unselected", *plain)
        return None

    def _target_portrait(self, screen):
        if self.observer.find(screen, "knight_header") and not self.observer.find(screen, "filter_panel"):
            return self.observer.find(screen, "rose")
        return None

    def _recruit(self, screen):
        if (self._target_portrait(screen) and self.observer.find(screen, "rose_selected")):
            return self.observer.find(screen, "recruit_active")
        return None

    def _class_button(self, screen):
        return self.observer.knight_button(screen)

    def _current_completed(self, screen):
        return self.observer.completed(screen)

    def _recruit_one(self):
        self._tap(self._wait(f"{self.hero_name}: 직업 영입권 확인", self._class_button))
        self._tap(self._wait(f"{self.hero_name}: 목록 및 필터 버튼 확인", self._filter_button))
        element = self._wait("속성 필터 메뉴 확인", self._element_state)
        if element[0] == "unselected":
            self._tap(element[1:])

        def selected_at_target(screen):
            value = self._element_state(screen)
            if value and value[0] == "selected":
                _, x, y, w, h = value
                _, ox, oy, ow, oh = element
                if abs(x + w / 2 - ox - ow / 2) < 10 and abs(y + h / 2 - oy - oh / 2) < 10:
                    return value
            return None

        self._wait("속성 선택 완료 확인", selected_at_target)
        self._point("filter_dismiss_point")
        self._tap(self._wait(f"{self.hero_name} 찾기 (스크롤 없음)", self._target_portrait))
        self._tap(self._wait(f"{self.hero_name} 선택 및 영입 버튼 확인", self._recruit))
        self._wait(f"{self.hero_name} 영입 완료 확인", lambda s: ("done",) if self._current_completed(s) else None)

    def _recruit_all(self):
        self._recruit_one()

    def run(self):
        self.stats["status"] = "running"
        try:
            entry = self._wait("탐사 시작 화면 확인", self._entry)
            if entry[0] != "done":
                if entry[0] == "start":
                    self._tap(entry[1:])
                    theme = self._wait("고용 서약서 화면 대기", self._theme_ready)
                    if theme[0] == "popup":
                        self._point("popup_dismiss_point")
                        theme = self._wait("해금 팝업 닫힘 확인", lambda s: None if self.observer.find(s, "unlock") else self._theme_ready(s))
                    if theme[0] == "unselected":
                        self._tap(theme[1:])
                    self._tap(self._wait("고용 서약서 선택 완료 확인", self._theme_confirm))
                self._recruit_all()
            self.stats.update(status="completed", phase=self.completion_phase, reason=self.completion_reason)
            if "recruited" in self.stats:
                self.stats["recruited"] = len(self.observer.heroes)
            self._record("completed")
        except _Stopped:
            self.stats.update(status="stopped", reason="사용자 중지")
        except PartyCostExceededError as exc:
            self.stats.update(status="failed", phase="영웅 소지/코스트 오류", reason=str(exc))
            self._record("hero_missing_or_cost_exceeded")
            logger.error("영웅 영입 실패: %s", exc)
        except Exception as exc:
            self.stats.update(status="failed", reason=str(exc))
            self._record("failed")
            logger.exception("자동 탐사 중지: %s", exc)
        logger.info("자동 탐사 결과: %s, %s (기록: %s)", self.stats["status"], self.stats["reason"], self.runtime_dir)
        return self.get_stats()


class PartyRecruitmentBot(KnightRecruitmentBot):
    """Use one verified recruitment sequence for each configured class."""

    def __init__(self, adb_controller, resource_root, runtime_dir, hero_ids=None, observer=None, auto_fallback=True):
        observer = observer or RecruitmentObserver(resource_root, hero_ids)
        super().__init__(adb_controller, resource_root, runtime_dir, observer)
        self.active_hero = observer.heroes[0]
        self.completion_phase = "영웅 4명 영입 완료"
        self.completion_reason = "탐사 입장 전 중지"
        self.auto_fallback = auto_fallback
        if len(observer.heroes) != 4:
            raise ValueError("기사·전사·정령사·도적을 각각 한 명씩 선택해 주세요.")
        self.stats["recruited"] = 0

    def _entry(self, screen):
        value = super()._entry(screen)
        if value is not None:
            return value
        # Resume only from a verified card screen; never replace an occupied slot.
        if any(self.observer.class_button(screen, hero) for hero in self.observer.heroes):
            return ("cards",)
        return None

    def _class_button(self, screen):
        return self.observer.class_button(screen, self.active_hero)

    def _current_completed(self, screen):
        return self.observer.hero_completed(screen, self.active_hero)

    def _filter_button(self, screen):
        if self.observer.header(screen, self.active_hero) and not self.observer.find(screen, "filter_panel"):
            return self.observer.find(screen, "filter")
        return None

    def _element_state(self, screen):
        if not self.observer.header(screen, self.active_hero) or not self.observer.find(screen, "filter_panel"):
            return None
        element = self.active_hero["element"]
        for other in ("dark", "fire", "ice", "forest", "light"):
            if other != element and self.observer.find(screen, other + "_2"):
                raise RuntimeError("다른 속성이 이미 선택되어 있습니다. 필터를 초기화해 주세요.")
        selected = self.observer.find(screen, element + "_2")
        plain = self.observer.find(screen, element + "_1")
        if selected and not plain:
            return ("selected", *selected)
        if plain and not selected:
            return ("unselected", *plain)
        return None

    def _target_portrait(self, screen):
        if self.observer.header(screen, self.active_hero) and not self.observer.find(screen, "filter_panel"):
            return self.observer.find(screen, self.active_hero["portrait"])
        return None

    def _recruit(self, screen):
        if self._target_portrait(screen) and self.observer.find(screen, self.active_hero["selected"]):
            return self.observer.find(screen, "recruit_active")
        return None

    def _return_to_cards(self):
        """Safely dismiss hero detail / list back to the class cards screen."""
        back_point = self.observer.config.get("back_button_point", [42, 35])
        for _ in range(6):
            screen = self._capture()
            if self._class_button(screen) is not None:
                return True
            self._tap((*back_point, 0, 0))
            if self.stop_event.wait(self.observer.config.get("poll_seconds", 0.3)):
                raise _Stopped()
        return self._class_button(self._capture()) is not None

    def _wait_recruit_action(self):
        """Wait for active recruit button or detect cost overflow."""
        self.stats["phase"] = f"{self.hero_name} 선택 및 영입 버튼 확인"
        logger.info("자동 탐사: %s", self.stats["phase"])
        timeout = self.observer.config.get("timeout_seconds", 30)
        poll = self.observer.config.get("poll_seconds", 0.3)
        deadline = time.monotonic() + timeout
        disabled_count = 0
        max_disabled_checks = 3

        while time.monotonic() < deadline:
            screen = self._capture()
            self._check_stop()

            recruit_btn = self._recruit(screen)
            if recruit_btn:
                return ("active", recruit_btn)

            if self._target_portrait(screen) and self.observer.find(screen, self.active_hero["selected"]):
                disabled_count += 1
                if disabled_count >= max_disabled_checks:
                    logger.warning("영웅 '%s' 선택 확인되었으나 영입 버튼 비활성화 (파티 코스트 초과 감지)", self.hero_name)
                    return ("cost_exceeded", None)
            else:
                disabled_count = 0

            if self.stop_event.wait(poll):
                raise _Stopped()

        raise RuntimeError(f"{self.hero_name} 선택 및 영입 버튼 확인: 대기 시간 초과.")

    def _handle_cost_exceeded(self):
        """Handle party cost overflow: fallback to alternative hero or raise error."""
        fallback = self.observer.get_fallback_hero(self.active_hero) if hasattr(self.observer, "get_fallback_hero") else None
        old_name = self.hero_name
        old_id = self.active_hero["id"]

        if self.auto_fallback and fallback and fallback["id"] != old_id:
            logger.warning(
                "파티 코스트 초과: '%s' 영입 불가 -> 대체 영웅 '%s'(으)로 자동 전환합니다.",
                old_name, fallback["name"]
            )
            self.stats["phase"] = f"{old_name} 코스트 초과 -> {fallback['name']} 대체 영입"
            self._return_to_cards()
            self.active_hero = fallback
            self.hero_name = fallback["name"]
            if hasattr(self.observer, "replace_hero"):
                self.observer.replace_hero(old_id, fallback)
            self._recruit_one()
            return

        self._return_to_cards()
        raise PartyCostExceededError(old_name, self.active_hero.get("class"), fallback)

    def _wait_hero_portrait(self):
        """Wait for target hero portrait or detect hero missing (not owned / cost exceeded)."""
        self.stats["phase"] = f"{self.hero_name} 찾기 (스크롤 없음)"
        logger.info("자동 탐사: %s", self.stats["phase"])
        timeout = self.observer.config.get("timeout_seconds", 30)
        poll = self.observer.config.get("poll_seconds", 0.3)
        deadline = time.monotonic() + timeout
        missing_count = 0
        max_missing_checks = 3

        while time.monotonic() < deadline:
            screen = self._capture()
            self._check_stop()

            portrait = self._target_portrait(screen)
            if portrait:
                return portrait

            # Check if hero list is actively displayed (header present, filter panel closed)
            if self.observer.header(screen, self.active_hero) and not self.observer.find(screen, "filter_panel"):
                missing_count += 1
                if missing_count >= max_missing_checks:
                    logger.warning(
                        "영웅 '%s' 목록 미노출 (영웅 미소지 또는 파티 코스트 초과)",
                        self.hero_name
                    )
                    return None
            else:
                missing_count = 0

            if self.stop_event.wait(poll):
                raise _Stopped()

        return None

    def _handle_hero_not_found(self):
        """Handle missing hero: fallback to alternative hero or raise error with clear guidance."""
        fallback = self.observer.get_fallback_hero(self.active_hero) if hasattr(self.observer, "get_fallback_hero") else None
        old_name = self.hero_name
        old_id = self.active_hero["id"]

        notice = f"'{old_name}' 영웅을 목록에서 찾을 수 없습니다. (영웅 미소지 또는 파티 코스트 초과로 미노출)"

        if self.auto_fallback and fallback and fallback["id"] != old_id:
            logger.warning(
                "%s -> 대체 영웅 '%s'(으)로 자동 전환합니다.",
                notice, fallback["name"]
            )
            self.stats["phase"] = f"{old_name} 미노출 -> {fallback['name']} 대체 영입"
            self._return_to_cards()
            self.active_hero = fallback
            self.hero_name = fallback["name"]
            if hasattr(self.observer, "replace_hero"):
                self.observer.replace_hero(old_id, fallback)
            self._recruit_one()
            return

        error_msg = f"{notice} — 영웅 보유 여부 또는 스킬트리 코스트 확장을 확인해 주세요."
        raise PartyCostExceededError(old_name, self.active_hero.get("class"), fallback, message=error_msg)

    def _recruit_one(self):
        self._tap(self._wait(f"{self.hero_name}: 직업 영입권 확인", self._class_button))
        self._tap(self._wait(f"{self.hero_name}: 목록 및 필터 버튼 확인", self._filter_button))
        element = self._wait("속성 필터 메뉴 확인", self._element_state)
        if element[0] == "unselected":
            self._tap(element[1:])

        def selected_at_target(screen):
            value = self._element_state(screen)
            if value and value[0] == "selected":
                _, x, y, w, h = value
                _, ox, oy, ow, oh = element
                if abs(x + w / 2 - ox - ow / 2) < 10 and abs(y + h / 2 - oy - oh / 2) < 10:
                    return value
            return None

        self._wait("속성 선택 완료 확인", selected_at_target)
        self._point("filter_dismiss_point")

        portrait = self._wait_hero_portrait()
        if portrait is None:
            self._handle_hero_not_found()
            return

        self._tap(portrait)

        action = self._wait_recruit_action()
        if action[0] == "cost_exceeded":
            self._handle_cost_exceeded()
            return

        self._tap(action[1])
        self._wait(f"{self.hero_name} 영입 완료 확인", lambda s: ("done",) if self._current_completed(s) else None)

    def _recruit_all(self):
        for hero in list(self.observer.heroes):
            current_hero = next((h for h in self.observer.heroes if h["class"] == hero["class"]), hero)
            self.active_hero = current_hero
            self.hero_name = current_hero["name"]
            def card_state(screen):
                if self._current_completed(screen):
                    return ("done",)
                button = self._class_button(screen)
                return ("available", *button) if button else None
            state = self._wait(f"{self.hero_name}: 영입 상태 확인", card_state)
            if state[0] != "done":
                self._recruit_one()
            self.stats["recruited"] += 1
        self._wait("네 영웅 영입 완료 확인", lambda s: ("done",) if self.observer.completed(s) else None)
