"""Connect recruitment to verified exploration nodes with shared cancellation."""

import logging
import time
import hashlib
import json
import random
import subprocess
from pathlib import Path

import numpy as np
import cv2

from .bot import KnightRecruitmentBot, PartyRecruitmentBot, _Stopped, RecognitionTimeout
from .node_observer import NodeObserver
from .event_policy import KoreanEventReader, choose_read_choice
from .errors import RecognitionPending
from .event_flow import run_event_flow, EVENT_STATES, TERMINALS

logger = logging.getLogger(__name__)

EVENT_FOLLOWUPS = {'map', 'battle_setup', 'battle', 'story', 'story_confirm',
    'rank_menu', 'rank_result', 'rank_reward', 'event', 'unknown_event', 'event_result',
    'unknown_event_result', 'loot', 'event_loot_popup', 'event_loot_consume',
    'recruit_reward', 'unclaimed_reward', 'event_warning', 'levelup', 'victory', 'battle_rank_complete'} | TERMINALS

HERO_NAMES = {
    'wukong': '오공',
    'jenua': '제뉴아',
    'shadow_rose': '그림자 로제',
    'destina': '데스티나',
    'savior_adin': '구원자 아딘',
    'rhianna_luciella': '리안나 루시엘라',
    'lisette': '리제트',
}
try:
    _rec_layout = Path(__file__).resolve().parent / 'recruitment_layout.json'
    if _rec_layout.is_file():
        _rec_data = json.loads(_rec_layout.read_text(encoding='utf-8'))
        for _hid, _hinfo in _rec_data.get('heroes', {}).items():
            if 'name' in _hinfo:
                HERO_NAMES.setdefault(_hid, _hinfo['name'])
except Exception:
    pass


class NodeProgressionBot(KnightRecruitmentBot):
    def __init__(self, adb, root, runtime_dir, observer=None, max_nodes=None,
                 event_mode='ocr', save_unknown_events=False, diagnostic_capture=False,
                 rank_priority=None, buy_future_investment=False):
        super().__init__(adb, root, runtime_dir, observer or NodeObserver(root))
        if event_mode not in ('ocr','random'): raise ValueError('지원하지 않는 이벤트 처리 방식')
        self.event_mode = event_mode
        self.buy_future_investment = bool(buy_future_investment)
        self.save_unknown_events = save_unknown_events
        self.diagnostic_capture = diagnostic_capture
        self.rank_priority = list(rank_priority) if rank_priority else ['wukong', 'jenua']
        self.last_screen = None
        self.event_context = False
        self.event_reader = KoreanEventReader(root)
        self.report_root = Path(runtime_dir) / 'unknown_events'
        self.report_dir = None
        self.report_sequence = 0
        self.auto_verified = False
        self.auto_tapped = False
        self.max_nodes = max_nodes
        self.current_node_kind = None
        self.pending_event_id = None
        self.rejected_event_choices = set()
        self._last_event_choice_bounds = None
        self.stats.update(nodes=0, auto_verified=False)

    def _capture(self):
        self._check_stop()
        attempts = self.observer.config.get('recognition_attempts', 3)
        for attempt in range(1, attempts+1):
            try:
                screen = self.adb.capture_frame()
            except (OSError, subprocess.TimeoutExpired, cv2.error) as exc:
                logger.warning('화면 캡처 실패 (%d/%d): %s', attempt, attempts, exc)
                screen = None
            if screen is not None and screen.shape[:2] == (720,1280):
                break
            self.stats['phase'] = f'화면 캡처 재확인 {attempt}/{attempts}'
            if attempt < attempts and self.stop_event.wait(self.observer.config.get('recognition_retry_seconds', 1)):
                raise _Stopped()
        self._check_stop()
        self.observer.validate_screen(screen)
        self.last_screen = screen
        if self.diagnostic_capture:
            cv2.imencode('.png',screen)[1].tofile(str(self.screen_path))
        return screen

    def _wait(self, phase, predicate):
        attempts = self.observer.config.get('recognition_attempts', 3)
        for attempt in range(1, attempts+1):
            try:
                return super()._wait(f'{phase} ({attempt}/{attempts})', predicate)
            except RecognitionTimeout:
                if attempt == attempts:
                    raise
                logger.warning('%s: 화면 인식 재시도 %d/%d (입력 없음)', phase, attempt+1, attempts)
                if self.stop_event.wait(self.observer.config.get('recognition_retry_seconds', 1)):
                    raise _Stopped()

    def _record(self, label):
        if self.diagnostic_capture: super()._record(label)
        if label == 'failed' and self.last_screen is not None:
            if self.event_context and self.report_dir is None:
                self._start_report(self.last_screen, {'mode': self.event_mode,
                    'stage': 'unrecognized_event', 'reason': self.stats.get('reason','')})
            self._report('failed', self.last_screen, {'phase': self.stats.get('phase'),
                'reason': self.stats.get('reason'), 'registered_event': self.pending_event_id})

    def _report(self, label, screen, metadata=None):
        if not self.save_unknown_events or self.report_dir is None or self.report_sequence >= 12: return
        self.report_dir.mkdir(parents=True,exist_ok=True)
        self.report_sequence += 1
        path = self.report_dir / f'{self.report_sequence:02d}_{label}'
        cv2.imencode('.png',screen)[1].tofile(str(path.with_suffix('.png')))
        path.with_suffix('.json').write_text(json.dumps(metadata or {},ensure_ascii=False,indent=2),encoding='utf-8')

    def _start_report(self, screen, metadata):
        if self.save_unknown_events and self.report_dir is None:
            self.report_dir = self.report_root / (time.strftime('%Y%m%d_%H%M%S')+'_'+str(time.time_ns()%1000000))
            self.report_sequence = 0
            self._report('choices',screen,metadata)

    @staticmethod
    def _event_signature(screen):
        hsv = cv2.cvtColor(screen[455:688,75:1205],cv2.COLOR_BGR2HSV)
        text = ((hsv[:,:,1]<110)&(hsv[:,:,2]>170)).astype(np.uint8)
        return hashlib.sha256(cv2.resize(text,(282,58),interpolation=cv2.INTER_AREA).tobytes()).hexdigest()

    def _tap_with_verify(self, bounds, phase, predicate, max_retries=3, wait_seconds=1.2, expected_state=None):
        before = self._capture()
        state = self._classify(before)
        if state is None or (expected_state is not None and state != expected_state):
            raise RecognitionTimeout(f'{phase}: 입력 전 화면 미확인')
        self._tap(bounds)
        def confirmed(after):
            if self._classify(after) is None:
                return None
            ok, result = predicate(after, before)
            return (result,) if ok else None
        return self._wait(phase, confirmed)[0]

    def _classify(self, screen):
        if screen is None: return None
        state = self.observer.classify(screen)
        if state == 'event':
            known = self.observer.known_event(screen)
            if known:
                self.pending_event_id = known
        if state is not None: return state
        if self.event_context:
            if self.observer.event_cards(screen):
                return 'event' if self.pending_event_id or self.observer.known_event_candidates(screen) else 'unknown_event'
            if self.observer.find(screen,'event_advance'): return 'unknown_event_result'
        return None

    def _state(self, phase, allowed, retry_tap=None, max_retries=3):
        # retry_tap is retained for call compatibility, but recognition retries
        # must never replay a previous screen's coordinates.
        return self._wait(phase, lambda s: (kind,) if (kind := self._classify(s)) in allowed else None)[0]

    def _guarded_tap(self, phase, state, marker, *, exiting=False):
        def ready(screen):
            if self.observer.classify(screen) != state:
                return None
            if self.observer.forbidden(screen) and not exiting:
                raise RuntimeError('금지 항목이 발견되어 입력을 중지했습니다.')
            return self.observer.find(screen, marker)
        for attempt in range(self.observer.config.get('recognition_attempts', 3)):
            bounds = self._wait(phase, ready)
            if ready(self._capture()) == bounds:
                self._tap(bounds)
                return
            self._check_stop()
            logger.warning('%s: 클릭 직전 화면 변경, 입력 없이 재확인', phase)
        raise RecognitionTimeout('클릭 직전 화면 변경이 반복되어 중지했습니다.')

    def _story(self, state):
        if state == 'story':
            self._guarded_tap('스토리 건너뛰기', 'story', 'skip')
            allowed = EVENT_FOLLOWUPS - {'story'} if self.event_context else {'story_confirm'}
            state = self._state('스토리 건너뛰기 후 화면 확인', allowed)
            if state != 'story_confirm':
                return state
        self._guarded_tap('스토리 건너뛰기 확인', 'story_confirm', 'story_confirm')
        self._wait('스토리 팝업 닫힘', lambda s: ('closed',) if not self.observer.find(s, 'story_dialog') else None)

    def _battle(self):
        self.stats['phase'] = '전투 진행 확인'
        start = last_progress = time.monotonic()
        reference = None
        progress_hits = 0
        cfg = self.observer.config
        while time.monotonic()-start < cfg['battle_timeout_seconds']:
            screen = self._capture()
            state = self._classify(screen)
            if state == 'defeat':
                self.stats['outcome'] = 'defeat'
                return
            if state == 'expedition_summary':
                # Final boss can skip the ordinary victory/reward page entirely.
                if self.observer.summary_boss_count(screen) == 3:
                    self.stats['outcome'] = 'victory'
                return
            if self.event_context and state in ('event', 'unknown_event'):
                # An event battle can return directly to another choice page.
                # Let the event flow re-observe and validate the next choice.
                logger.info('이벤트 전투 후 선택 화면 복귀: %s', state)
                return
            if state in ('victory', 'battle_rank_complete', 'levelup', 'event_loot_popup', 'rank_result', 'rank_reward',
                         'rank_menu', 'recruit_reward', 'loot', 'event_result', 'unknown_event_result', 'map'):
                self.auto_verified = True
                self.stats['auto_verified'] = True
                return
            if state in ('story', 'story_confirm'):
                self._story(state)
                last_progress = time.monotonic()
                reference = None
                continue
            now = time.monotonic()
            if state == 'battle':
                signature = self.observer.progress_signature(screen)
                if reference is None:
                    reference = signature
                    last_progress = now
                elif float(np.abs(reference-signature).mean()) > cfg['progress_difference']:
                    reference = signature
                    last_progress = now
                    progress_hits += 1
                    if progress_hits >= 2:
                        self.auto_verified = True
                        self.stats['auto_verified'] = True
                if not self.auto_verified and not self.auto_tapped and now-last_progress >= cfg['initial_stall_seconds']:
                    # Portrait controls are a second protection against toggling active auto off.
                    if not self.observer.find(screen, 'auto_controls'):
                        self._guarded_tap('첫 전투 정체: 자동 전투 한 번 켜기', 'battle', 'auto')
                        self.auto_tapped = True
                        self._record('auto_enabled_once')
                        last_progress = time.monotonic()
                    else:
                        self.stats['phase'] = '자동 전투 진행 신호 대기'
                if now-last_progress >= cfg['battle_stall_seconds']:
                    raise RuntimeError('전투 진행 신호 없음 — 자동 전투를 다시 누르지 않고 중지합니다.')
            # Loading/cutscenes do not trigger the initial auto toggle.
            else:
                reference = None
                last_progress = now
            if self.stop_event.wait(2):
                raise _Stopped()
        raise RuntimeError('전투 제한 시간 초과')

    def _rank_target(self, screen):
        if self.observer.classify(screen) != 'rank_menu': return None
        if self.observer.forbidden(screen):
            raise RuntimeError('랭크업 화면에서 금지 항목 발견')
        for i, target in enumerate(self.rank_priority):
            rank = self.observer.rank(screen, target)
            if rank is None:
                sub_rank = None
                for next_target in self.rank_priority[i+1:]:
                    try:
                        r = self.observer.rank(screen, next_target)
                        if r is not None and r < 5:
                            sub_rank = r
                            break
                    except Exception:
                        pass
                if sub_rank is not None:
                    target_name = HERO_NAMES.get(target, target)
                    logger.info('%s 랭크 판독 불가 — %s 5랭크(MAX)로 판단하여 다음 우선순위 영웅으로 전환합니다.', target_name, target_name)
                    rank = 5
                else:
                    raise RecognitionPending(f'{HERO_NAMES.get(target, target)} 랭크를 확실하게 읽지 못했습니다.')
            if rank < 5:
                bounds = self.observer.find(screen, target)
                return (target, rank, *bounds) if bounds else None

        last_hero = self.rank_priority[-1] if self.rank_priority else '영웅'
        raise RuntimeError(f'{HERO_NAMES.get(last_hero, last_hero)} 랭크업 가능 여부를 확인하지 못했습니다.')

    def _rankup(self):
        target = self._wait('우선순위 랭크 확인', self._rank_target)
        if self._rank_target(self._capture()) != target:
            raise RuntimeError('랭크업 대상이 변경됐습니다.')
        hero, old_rank, *bounds = target
        self._tap(bounds)
        # Selected hero name in the left detail panel must match the target name.
        def selected(screen):
            if self.observer.classify(screen) != 'rank_menu': return None
            if self.observer.forbidden(screen): raise RuntimeError('금지 항목 발견')
            return self.observer.find(screen, 'rank_button') if (self.observer.find(screen, hero+'_selected') or self.observer.find(screen, hero)) else None
        button = self._wait('선택 영웅과 랭크업 버튼 확인', selected)
        if selected(self._capture()) != button: raise RuntimeError('랭크업 선택 상태 변경')
        self._tap(button)
        state = self._state('랭크업 결과 대기', {'rank_result', 'battle_rank_complete'})
        if state == 'battle_rank_complete':
            return state
        # Completion uses shared arrow + RANK UP text, independent of hero art
        # and the card's rank-number position. _state requires stable frames.
        close_btn = self._wait('랭크업 결과 닫기 확인', lambda s: self.observer.find(s, 'rank_close') if self.observer.classify(s) == 'rank_result' else None)
        def closed(after, before):
            return (self.observer.classify(after) != 'rank_result'), None
        self._tap_with_verify(close_btn, '랭크업 결과 닫기', closed, expected_state='rank_result')

    def _rest(self):
        screen = self._capture()
        if not self.observer.find(screen, 'rest_done'):
            self._guarded_tap('휴식: 랭크업 선택', 'rest', 'detail_rest')
            self._state('랭크업 영웅 목록 대기', {'rank_menu'})
            self._rankup()
            self._record('rankup_completed')
            def rankup_disabled(s):
                if self.observer.classify(s) != 'rest':
                    return None
                if self.observer.find(s, 'rest_done') or not self.observer.find(s, 'detail_rest'):
                    return self.observer.find(s, 'leave')
                return None
            leave_btn = self._wait('휴식 랭크업 비활성화(완료표시) 및 떠나기 확인', rankup_disabled)
        else:
            leave_btn = self._wait('휴식 떠나기 확인', lambda s: self.observer.find(s, 'leave') if self.observer.classify(s) == 'rest' else None)
        self._guarded_tap('휴식 떠나기', 'rest', 'leave', exiting=True)
        self._state('휴식 후 지도 복귀', {'map'})
        self.stats['nodes'] += 1

    def _loot(self):
        def choice(screen):
            if self.observer.classify(screen) != 'loot': return None
            allowed = self.observer.loot_choices(screen)
            if not allowed: raise RuntimeError('모든 전리품이 금지 항목입니다. 선택 없이 중지합니다.')
            return allowed[0]
        target = self._wait('금지 전리품 제외 후 선택', choice)
        screen = self._capture()
        if choice(screen) != target: raise RuntimeError('전리품 후보가 변경됐습니다.')
        if self.observer.selected_loot(screen) != target:
            self._tap(target)
        def confirmed(screen):
            if self.observer.classify(screen) != 'loot': return None
            allowed = self.observer.loot_choices(screen)
            if target not in allowed: raise RuntimeError('선택 전리품이 금지 항목으로 확인됐습니다.')
            if self.observer.selected_loot(screen) != target: return None
            return self.observer.find(screen, 'loot_button')
        button = self._wait('허용 전리품 선택 상태 확인', confirmed)
        if confirmed(self._capture()) != button: raise RuntimeError('전리품 확정 직전 화면 변경')
        self._tap(button)
        def after_claim(frame):
            state = self._classify(frame)
            if state == 'loot' and self.observer.selected_loot(frame) is not None:
                return None  # A still-selected card has not acknowledged the claim.
            return (state,) if state in ({'supply','victory'} | EVENT_FOLLOWUPS) else None
        return self._wait('전리품 수령 후 다음 화면 확인', after_claim)[0]

    def _supply(self):
        screen = self._capture()
        if screen is not None and (self._classify(screen) in ('unclaimed_reward', 'story_confirm') or self.observer.find(screen, 'story_confirm')):
            logger.info('보급 노드: 진입 시 미획득 알림 팝업 감지 — 취소 버튼으로 닫고 전리품 획득 시도')
            cancel_btn = self.observer.find(screen, 'story_cancel') or (532, 460)
            self._tap(cancel_btn)
            if self.stop_event.wait(0.5):
                raise _Stopped()
            screen = self._capture()

        loot_btn = self.observer.find(screen, 'supply_loot') if screen is not None else None
        done_marker = self.observer.find(screen, 'supply_done') if screen is not None else None

        if not done_marker or loot_btn:
            def find_loot_btn(s):
                if self.observer.find(s, 'supply_done'):
                    return ('already_done',)
                btn = self.observer.find(s, 'supply_loot')
                return ('btn', *btn) if btn else None

            res = self._wait('보급: 전리품 획득 버튼 확인', find_loot_btn)
            if res[0] == 'btn':
                target_loot_btn = res[1:]
                self._tap(target_loot_btn)
                loot_entered = False
                for attempt in range(1, 4):
                    fresh = self._capture()
                    if self._classify(fresh) == 'loot':
                        loot_entered = True
                        break
                    if attempt < 3:
                        if self.stop_event.wait(0.5):
                            raise _Stopped()
                        self._tap(target_loot_btn)
                if loot_entered or self._classify(self._capture()) == 'loot':
                    self._loot()
                else:
                    state = self._state('보급 전리품 목록 진입 대기', {'loot', 'supply'})
                    if state == 'loot':
                        self._loot()

        leave_btn = self._wait('보급 떠나기 확인', lambda s: self.observer.find(s, 'leave') if self._classify(s) == 'supply' or self.observer.find(s, 'leave') else None)
        self._tap(leave_btn)

        def after_leave(s):
            state = self._classify(s)
            if state in ('map', 'unclaimed_reward', 'story_confirm'):
                return (state,)
            if self.observer.find(s, 'unclaimed_dialog') or self.observer.find(s, 'story_confirm'):
                return ('unclaimed_reward',)
            return None

        state = self._wait('보급 떠나기 후 결과(지도 또는 미획득 팝업) 확인', after_leave)[0]
        if state == 'unclaimed_reward':
            logger.info('보급 노드: 미획득 전리품 팝업 감지 — 확인 버튼 클릭하여 퇴장 진행')
            confirm_btn = self._wait('미획득 전리품 팝업 확인 버튼', lambda s: self.observer.find(s, 'story_confirm'))
            def popup_closed(after, before):
                return (self._classify(after) == 'map' or not self.observer.find(after, 'story_confirm')), None
            self._tap_with_verify(confirm_btn, '미획득 전리품 팝업 확인', popup_closed, max_retries=3)
            self._state('팝업 확인 후 지도 복귀', {'map'})

        self.stats['nodes'] += 1

    def _shop(self):
        if self._classify(self._capture()) == 'shop_purchase_confirm':
            # A resumed confirmation has no verified originating selection.
            self._guarded_tap('기존 상점 구매 확인 취소', 'shop_purchase_confirm', 'shop_purchase_cancel', exiting=True)
            self._state('구매 취소 후 상점', {'shop'})
        if self.buy_future_investment:
            self._purchase_future_investment()
        self._guarded_tap('상점 나가기', 'shop', 'shop_exit', exiting=True)
        state = self._state('상점 퇴장 확인', {'map','shop_exit_confirm'})
        if state == 'shop_exit_confirm':
            self._shop_confirm()
        else:
            self.stats['nodes'] += 1

    def _purchase_future_investment(self):
        offer = self._wait('미래 투자 상품·가격·재화 확인', self.observer.shop_investment_offer)
        if offer[0] == 'skip':
            logger.info('미래 투자 구매 생략: 미진열·구매 완료·금지·재화 부족')
            return
        if self.observer.shop_investment_offer(self._capture()) != offer:
            raise RecognitionTimeout('미래 투자 선택 직전 상품 또는 재화 변경')
        _, price, balance, x, y, *button = offer
        self._tap(button)
        def opened(screen):
            state = self._classify(screen)
            if state == 'shop' and self.observer.find(screen, 'shop_insufficient_notice'):
                return ('insufficient',)
            return ('confirm',) if state == 'shop_purchase_confirm' else None
        if self._wait('상품 구매 확인 창 또는 재화 부족 안내', opened)[0] == 'insufficient':
            logger.info('미래 투자 구매 생략: 게임의 재화 부족 안내 확인')
            return
        def confirm(screen):
            if self._classify(screen) != 'shop_purchase_confirm': return None
            if not self.observer.find(screen, 'shop_investment_confirm_item'): return ('cancel',)
            for _, (bx,by,bw,bh) in self.observer.forbidden(screen):
                if 300 <= by+bh/2 <= 415 and 480 <= bx+bw/2 <= 800: return ('cancel',)
            cfg = self.observer.config['shop_purchase']
            if self.observer.shop_price_unaffordable(screen, cfg['confirm_price_region']): return ('cancel',)
            actual_price = self.observer.shop_number(screen, cfg['confirm_price_region'])
            if actual_price != price: return ('cancel',)
            button = self.observer.find(screen, 'shop_purchase_button')
            return ('confirm', *button) if button else None
        action = self._wait('미래 투자 이름·구매 금액 재확인', confirm)
        if confirm(self._capture()) != action:
            raise RecognitionTimeout('구매 확정 직전 화면 변경')
        if action[0] == 'cancel':
            self._guarded_tap('상품 불일치 구매 취소', 'shop_purchase_confirm', 'shop_purchase_cancel', exiting=True)
            self._state('구매 취소 후 상점', {'shop'})
            return
        self._tap(action[1:])
        def completed(screen):
            if self._classify(screen) != 'shop': return None
            if self.observer.find(screen, 'shop_insufficient_notice'): return ('insufficient',)
            if not self.observer.find(screen, 'shop_purchase_done', region=(x,y,164,240)): return None
            remaining = self.observer.shop_number(screen, self.observer.config['shop_purchase']['currency_region'])
            return ('done',) if remaining == balance-price else None
        outcome = self._wait('미래 투자 구매 완료·파편 차감 확인', completed)
        if outcome[0] == 'insufficient':
            logger.info('미래 투자 구매 실패: 재화 부족 안내 — 재클릭 없이 퇴장')
            return
        self.stats['shop_purchases'] = self.stats.get('shop_purchases', 0)+1
        logger.info('미래 투자 구매 완료: 파편 %d → %d', balance, balance-price)

    def _shop_confirm(self):
        self._guarded_tap('상점 구매 없이 퇴장 확인', 'shop_exit_confirm', 'story_confirm', exiting=True)
        self._state('상점 퇴장 후 지도 복귀', {'map'})
        self.stats['nodes'] += 1

    def _defeat(self):
        self.stats['outcome'] = 'defeat'
        self._record('battle_defeat')
        self._guarded_tap('패배 결과 정산으로 이동', 'defeat', 'defeat', exiting=True)
        self._state('탐사 정산 화면 대기', {'expedition_summary'})

    def _finish_results(self):
        cleared = False
        if self.stats.get('outcome') != 'defeat':
            def count(frame):
                value = self.observer.summary_boss_count(frame)
                return (value,) if value is not None else None
            bosses = self._wait('정산 보스 처치 횟수 확인', count)[0]
            self.stats['summary_boss_count'] = bosses
            cleared = bosses == 3
            logger.info('탐사 정산 판정: 보스 처치 %d/3, 완주=%s', bosses, cleared)
            if not cleared:
                self.stats.update(status='stopped', reason=f'정산 보스 처치 {bosses}/3 — 승패 확인 불가')
                logger.warning('탐사 정산 유지: %s', self.stats['reason'])
                return
            self.stats['outcome'] = 'victory'
        self._record('expedition_summary')
        self._guarded_tap('탐사 정산 닫기', 'expedition_summary', 'summary_close', exiting=True)
        self._state('탐사 초기 화면 복귀', {'exploration_entry'}, retry_tap=lambda s: self.observer.find(s, 'summary_close'))
        if self.stats.get('outcome') == 'defeat':
            self.stats.update(status='round_failed', reason='패배 결과 처리 및 초기 화면 복귀 완료')
        elif cleared:
            self.stats.update(status='round_cleared', reason='탐사 완료 및 초기 화면 복귀 완료')
        else:
            self.stats.update(status='stopped', reason='탐사 정산 복귀 완료 — 승패 확인 불가')

    def _event(self):
        screen = self._capture()
        known = self.observer.known_event(screen)
        candidates = self.observer.known_event_candidates(screen)
        if not known and not candidates and not self.pending_event_id:
            return self._unknown_event()
        if known:
            self.pending_event_id = known
        logger.info('이벤트 등록 규칙 우선: %s', self.pending_event_id or candidates)
        def choose(frame):
            state = self._classify(frame)
            if state in EVENT_FOLLOWUPS - {'event', 'unknown_event'}:
                return ('followup', state)
            target = self.observer.event_choice(frame, excluded=self.rejected_event_choices)
            return ('choice', target) if target else None
        ready = self._wait('허용 이벤트 우선순위 확인', choose)
        if ready[0] == 'followup':
            self._accept_event_page(ready[1])
            return ready[1]
        if choose(self._capture()) != ready:
            raise RuntimeError('이벤트 선택 직전 화면 변경')
        target = ready[1]
        self._last_event_choice_bounds = target
        sig = self._event_signature(self._capture())
        self._tap(target)
        state = self._event_transition(sig)
        while state in ('event_loot_consume', 'event_warning', 'unclaimed_reward'):
            if state == 'event_loot_consume':
                state = self._handle_loot_consume()
            elif state in ('event_warning', 'unclaimed_reward'):
                state = self._handle_event_confirm(target)
        if state == 'map':
            self.stats['nodes'] += 1
        return state

    def _event_transition(self, previous_signature=None):
        def changed(screen):
            state = self._classify(screen)
            if state in ('unknown_event', 'event') and previous_signature is not None:
                if self._event_signature(screen) == previous_signature:
                    return None
            return (state,) if state in EVENT_FOLLOWUPS else None
        state = self._wait('이벤트 선택 결과 확인', changed)[0]
        self._accept_event_page(state)
        self._report('result', self._capture(), {'state': state})
        return state

    def _dispatch_event_screen(self, state):
        """A handler performs one verified task, then the flow observes again."""
        if state in ('event', 'unknown_event'):
            return self._event()
        if state in ('event_result', 'unknown_event_result'):
            return self._event_result()
        if state in ('story', 'story_confirm'):
            self._story(state)
            return self._state('스크립트 이후 화면 확인', EVENT_FOLLOWUPS)
        if state == 'loot':
            return self._loot()
        if state == 'event_loot_consume':
            return self._handle_loot_consume()
        if state == 'recruit_reward':
            return self._skip_recruit_reward()
        if state == 'rank_reward':
            return self._event_rank_reward()
        if state == 'rank_menu':
            self._rankup()
            after = self._state('랭크업 이후 화면 확인', EVENT_FOLLOWUPS)
            return self._leave_used_rank_reward(after)
        if state in ('rank_result', 'event_loot_popup', 'levelup'):
            marker = {'rank_result':'rank_close', 'event_loot_popup':'event_loot_close', 'levelup':'level_close'}[state]
            return self._close_event_popup(state, marker)
        if state in ('event_warning', 'unclaimed_reward'):
            return self._handle_event_confirm(self._last_event_choice_bounds)
        if state == 'battle_setup':
            self._guarded_tap('이벤트 전투 시작', state, 'battle_start')
            return self._state('이벤트 전투 시작 후 화면', EVENT_FOLLOWUPS - {'battle_setup'})
        if state == 'battle':
            return self._battle()
        if state == 'victory':
            return self._victory()
        if state == 'battle_rank_complete':
            screen = self._capture()
            if self.observer.find(screen, 'loot_reward'):
                self._guarded_tap('랭크업 후 남은 전리품 보상 열기', state, 'loot_reward')
                return self._state('추가 전투 보상 확인', EVENT_FOLLOWUPS - {state})
            skip_hero = bool(self.observer.find(screen, 'reward_hero'))
            self._guarded_tap('전투 랭크업 완료 후 계속 탐사', state, 'continue', exiting=True)
            after = self._state('전투 랭크업 완료 후속 화면', EVENT_FOLLOWUPS - {state})
            if after == 'unclaimed_reward' and skip_hero:
                return self._confirm_skipped_hero()
            return after
        raise RecognitionTimeout('지원하지 않는 이벤트 화면: ' + state)

    def _leave_used_rank_reward(self, state):
        if state == 'rank_reward':
            self._guarded_tap('랭크업 완료 보상에서 계속 탐사', state, 'event_reward_continue', exiting=True)
            return self._state('랭크업 완료 후속 화면', EVENT_FOLLOWUPS - {'rank_reward'})
        return state

    def _close_event_popup(self, state, marker):
        screen = self._capture()
        signature = self._event_signature(screen)
        self._guarded_tap('이벤트 보상 결과 닫기', state, marker, exiting=True)
        def changed(frame):
            after = self._classify(frame)
            if after == state and self._event_signature(frame) == signature:
                return None
            return (after,) if after in EVENT_FOLLOWUPS else None
        after = self._wait('보상 결과 다음 화면 확인', changed)[0]
        if state == 'rank_result':
            after = self._leave_used_rank_reward(after)
        return after

    def _accept_event_page(self, state):
        # Warnings can return to the same choices; other confirmed pages start
        # a new step even when their card coordinates are unchanged.
        if state not in ('event_warning', 'unclaimed_reward'):
            self.pending_event_id = None
            self.rejected_event_choices.clear()
            self._last_event_choice_bounds = None

    def _handle_loot_consume(self):
        def choice(screen):
            if self._classify(screen) != 'event_loot_consume': return None
            return self.observer.loot_consume_target(screen)
        target = self._wait('소모할 전리품 확인: 금지 전리품 우선', choice)
        screen = self._capture()
        if choice(screen) != target:
            raise RecognitionTimeout('소모 전리품 후보 변경')
        x, y = target
        icon = screen[y-22:y+22, x-22:x+22].copy()
        if not self.observer.loot_consume_selected(screen, icon):
            self._tap((x, y, 0, 0))
        def selected(frame):
            if self._classify(frame) != 'event_loot_consume':
                return None
            if self.observer.loot_consume_selected(frame, icon):
                return tuple(self.observer.config['event_loot_consume_bounds'])
            return None
        confirm = self._wait('소모 대상 아이콘 및 선택 1/1 확인', selected)
        if selected(self._capture()) != confirm:
            raise RecognitionTimeout('전리품 소모 확정 직전 선택 상태 변경')
        self._tap(confirm)
        # The random outcome is never assumed from the selected event text.
        return self._state('전리품 소모 후 실제 보상 종류 확인', EVENT_FOLLOWUPS - {'event_loot_consume'})

    def _handle_event_confirm(self, failed_target=None, available_cards=None):
        # A generic Confirm label does not identify the consequence of a warning.
        def cancel_ready(screen):
            if self._classify(screen) not in ('event_warning', 'unclaimed_reward'):
                return None
            return self.observer.find(screen, 'story_cancel')
        cancel = self._wait('이벤트 경고 취소 버튼 확인', cancel_ready)
        if cancel_ready(self._capture()) != cancel:
            raise RecognitionTimeout('이벤트 경고 화면 변경')
        if failed_target is not None:
            self.rejected_event_choices.add(tuple(failed_target))
        self._tap(cancel)
        # Re-enter the common policy; never choose randomly inside a popup handler.
        state = self._state('이벤트 경고 취소 후 화면 확인', EVENT_FOLLOWUPS - {'event_warning','unclaimed_reward'})
        if state not in ('event', 'unknown_event'):
            self._accept_event_page(state)
        return state

    def _unknown_event(self):
        def ready(screen):
            st = self._classify(screen)
            if st in ('event_result', 'unknown_event_result') or (st is None and not self.observer.event_cards(screen) and self.observer.find(screen, 'event_advance')):
                return ('result', None)
            if st in EVENT_FOLLOWUPS - {'event', 'unknown_event'}:
                return ('followup', st)
            if self.pending_event_id or self.observer.known_event_candidates(screen):
                return ('registered', None)
            if st != 'unknown_event': return None
            cards = self.observer.event_cards(screen)
            return (tuple(cards),self._event_signature(screen)) if cards else None

        ready_val = self._wait('미등록 이벤트 선택지 확인', ready)
        if ready_val[0] == 'followup':
            self._accept_event_page(ready_val[1])
            return ready_val[1]
        if ready_val[0] == 'registered':
            return self._event()
        if ready_val[0] == 'result':
            logger.info('자동 탐사 [미등록 이벤트]: 대기 중 결과/대화 화면 감지 — 결과 닫기 진행')
            return self._event_result()
        cards, signature = ready_val

        screen = self._capture()
        observed = ready(screen)
        if observed and observed[0] == 'registered':
            logger.info('미등록 이벤트 재확인 중 등록 규칙 발견 — 저장 규칙으로 전환')
            return self._event()
        if observed != (cards,signature): raise RuntimeError('이벤트 선택지가 변경됐습니다.')
        self._start_report(screen,{'mode':self.event_mode,'cards':cards})
        available = [c for c in self.observer.available_event_cards(screen,cards)
                     if tuple(c) not in self.rejected_event_choices]
        if not available: raise RuntimeError('금지/비활성 선택지 제외 후 후보 없음')
        rows = []
        if self.event_mode == 'random':
            target = random.choice(available)
        else:
            self.stats['phase'] = '미등록 이벤트 문구 읽기'
            rows = self.event_reader.choices(screen,available)
            self._check_stop()
            money = self.event_reader.currency(screen) if any(r['rule'] and r['rule'][2] for r in rows) else None
            selected = choose_read_choice(rows,money)
            target = selected['bounds']
        fresh = self._capture()
        observed = ready(fresh)
        if observed and observed[0] == 'registered':
            logger.info('이벤트 입력 직전 등록 규칙 발견 — 무작위/OCR 후보 폐기')
            return self._event()
        if observed != (cards,signature) or target not in self.observer.available_event_cards(fresh,cards):
            raise RuntimeError('이벤트 입력 직전 선택지 변경')
        if self.event_mode == 'ocr':
            confirmed = self.event_reader.choices(fresh,[target])[0]
            if any(confirmed[k] != selected[k] for k in ('title','effect','rule')):
                raise RuntimeError('이벤트 효과 재확인 불일치')
            fresh = self._capture()
            if ready(fresh) != (cards,signature) or target not in self.observer.available_event_cards(fresh,cards):
                raise RuntimeError('이벤트 재확인 중 화면 변경')
        self._report('selected',fresh,{'mode':self.event_mode,'target':target,'ocr':rows})
        logger.info('미등록 이벤트 선택 확정: 방식=%s, 후보=%d개, 위치=%s', self.event_mode, len(available), target)
        self._last_event_choice_bounds = target
        self._tap(target)
        state = self._event_transition(signature)
        while state in ('event_loot_consume', 'event_warning', 'unclaimed_reward'):
            if state == 'event_loot_consume':
                state = self._handle_loot_consume()
            elif state in ('event_warning', 'unclaimed_reward'):
                state = self._handle_event_confirm(target, available)
        if state == 'map':
            self.stats['nodes'] += 1
        return state

    def _event_result(self):
        def ready(screen):
            if self._classify(screen) not in ('event_result','unknown_event_result'):
                return None
            if self.observer.event_cards(screen):
                return None
            if not self.observer.find(screen, 'event_advance'):
                return None
            identity = self.observer.event_result_marker(screen) or self._event_signature(screen)
            return (identity, *self.observer.config['event_advance_bounds'])
        target = self._wait('확인된 이벤트 결과 닫기', ready)
        screen = self._capture()
        if ready(screen) != target:
            raise RecognitionTimeout('이벤트 결과 화면 변경')
        if self._classify(screen) == 'unknown_event_result':
            self._start_report(screen, {'mode':self.event_mode, 'stage':'result'})
        self._report('dialogue', screen)
        signature = self._event_signature(screen)
        self._tap(target[1:])
        def changed(frame):
            state = self._classify(frame)
            if state in ('event_result','unknown_event_result'):
                page = ready(frame)
                if not page or (page[0] == target[0] and self._event_signature(frame) == signature):
                    return None
            return (state,) if state in EVENT_FOLLOWUPS else None
        # One page per dispatch: loot, heroes, new choices and text all go through
        # their own validation before any further input.
        state = self._wait('이벤트 결과 다음 화면', changed)[0]
        self.pending_event_id = None
        if state == 'map': self.stats['nodes'] += 1
        return state

    def _event_rank_reward(self):
        self.event_context = True
        self._guarded_tap('이벤트 랭크업 보상 사용', 'rank_reward', 'event_rank_reward_button')
        state = self._state('이벤트 랭크업 영웅 목록 또는 후속 화면', EVENT_FOLLOWUPS - {'rank_reward'})
        if state != 'rank_menu':
            return state
        self._rankup()
        state = self._state('이벤트 랭크업 보상 결과', EVENT_FOLLOWUPS)
        if state == 'rank_reward':
            # Only leave the reward card after _rankup verified the new rank.
            self._guarded_tap('이벤트 랭크업 후 계속 탐사', 'rank_reward', 'event_reward_continue', exiting=True)
            state = self._state('이벤트 랭크업 후속 화면', EVENT_FOLLOWUPS - {'rank_reward'})
        if state == 'map': self.stats['nodes'] += 1
        return state

    def _victory(self):
        self.stats['outcome'] = 'victory'
        # Battle reward cards have a different layout from event reward cards.
        # Consume a verified rank reward before considering the continue button,
        # then re-observe: another reward, dialogue or map may follow.
        if self.observer.find(self._capture(), 'battle_rank_reward'):
            self._guarded_tap('전투 보상 영웅 랭크업 열기', 'victory', 'battle_rank_reward')
            state = self._state('전투 랭크업 보상 다음 화면', EVENT_FOLLOWUPS - {'victory'})
            if state == 'rank_menu':
                self._rankup()
                state = self._state('전투 랭크업 완료 후 보상 재확인', EVENT_FOLLOWUPS)
            return state
        if self.event_context:
            screen = self._capture()
            if self.observer.find(screen, 'loot_reward'):
                self._guarded_tap('이벤트 전투 전리품 보상 열기', 'victory', 'loot_reward')
                return self._state('전투 보상 종류 재확인', EVENT_FOLLOWUPS - {'victory'})
            skip_hero = bool(self.observer.find(screen, 'reward_hero'))
            self._guarded_tap('이벤트 전투 후 계속 탐사', 'victory', 'continue', exiting=True)
            after = self._state('전투 이후 이벤트 화면 확인', EVENT_FOLLOWUPS - {'victory'})
            if after == 'unclaimed_reward' and skip_hero:
                return self._confirm_skipped_hero()
            return after
        if self.observer.find(self._capture(), 'loot_reward'):
            self._guarded_tap('전투 보상 전리품 선택', 'victory', 'loot_reward')
            self._state('전투 보상 전리품 목록', {'loot'})
            self._loot()
        # A hero reward is not part of the configured party; do not recruit it.
        skip_hero = bool(self.observer.find(self._capture(), 'reward_hero'))
        self._guarded_tap('계속 탐사하기', 'victory', 'continue', exiting=True)
        allowed = (EVENT_FOLLOWUPS | {'expedition_summary','exploration_entry'}) - {'victory'}
        if skip_hero: allowed.add('unclaimed_reward')
        state = self._state('승리 후 다음 화면 확인', allowed)
        if state in ('event_loot_popup', 'rank_result'):
            # A resumed event battle has no event_context yet. Let the outer
            # loop handle this reward and all subsequent rewards identically
            # to a run that observed the event entrance.
            return state
        if state == 'unclaimed_reward':
            self._guarded_tap('추가 영웅 보상 없이 진행', state, 'story_confirm', exiting=True)
            state = self._state('보상 확인 후 복귀', {'map','story','story_confirm','expedition_summary','exploration_entry'})
        if state == 'expedition_summary':
            self._finish_results()
        elif state == 'exploration_entry':
            self.stats.update(status='stopped', reason='초기 화면 복귀 — 최종 클리어 정산 미확인')
        elif state == 'map' or (not self.event_context and state in ('story','story_confirm')):
            self.stats['nodes'] += 1

    def _skip_recruit_reward(self):
        self._guarded_tap('영웅 영입 건너뛰기 버튼 확인', 'recruit_reward', 'recruit_continue', exiting=True)
        allowed = EVENT_FOLLOWUPS - {'recruit_reward'}
        state = self._state('영웅 영입 건너뛰기 후 확인', allowed)
        if state == 'unclaimed_reward':
            state = self._confirm_skipped_hero()
        return state

    def _confirm_skipped_hero(self):
        self._guarded_tap('추가 영웅 보상 없이 진행 확인', 'unclaimed_reward', 'story_confirm', exiting=True)
        return self._state('영웅 보상 건너뛰기 이후 화면', EVENT_FOLLOWUPS - {'unclaimed_reward'})

    def _select_node(self):
        def choose(screen):
            if self.observer.classify(screen) != 'map': return None
            kind, bounds = self.observer.choose_node(screen)
            return (kind, *bounds)
        target = self._wait('진입 가능한 노드와 금지 이미지 확인', choose)
        kind = target[0]
        if kind not in self.observer.config['supported_nodes']:
            label = {'elite':'정예 전투','shop':'상점','supply':'보급','event':'랜덤 이벤트','boss':'보스'}.get(kind, kind)
            self.stats.update(status='stopped', phase='지원 범위 끝', reason=f'{label} 노드 내부 규칙 미구현 — 진입 전 중지')
            return False
        current = choose(self._capture())
        if not current:
            if self.stop_event.wait(0.2):
                raise _Stopped()
            current = choose(self._capture())
        if (not current or current[0] != target[0]
                or abs(current[1] - target[1]) > 10 or abs(current[2] - target[2]) > 10):
            raise RuntimeError('노드 후보 변경')
        self.current_node_kind = kind
        logger.info('자동 탐사 선택 노드: %s', kind)
        self.event_context = kind == 'event'
        self._tap(target[1:])
        detail_states = {'battle':{'battle_detail'}, 'rest':{'rest_detail'}, 'supply':{'supply_detail'},
                         'elite':{'elite_detail'}, 'boss':{'boss_detail'}, 'shop':{'node_detail'}, 'event':{'event_detail'}}
        detail = self._state('노드 상세 대기', detail_states[kind])
        enter_bounds = self._wait('노드 진입 버튼 확인', lambda s: self.observer.find(s, 'enter_node'))
        self._tap(enter_bounds)
        target_state = {'battle':'battle_setup','elite':'battle_setup','boss':'battle_setup','rest':'rest','supply':'supply','shop':'shop','event':'event'}[kind]
        allowed = {target_state,'story','story_confirm'}
        if kind == 'event': allowed.update(EVENT_FOLLOWUPS - {'map'})
        if kind == 'supply': allowed.update({'unclaimed_reward'})
        self._state('노드 내부 진입 확인', allowed, retry_tap=lambda s: self.observer.find(s, 'enter_node'))
        return True

    def run(self):
        self.stats.update(status='running', reason='')
        try:
            while True:
                self._check_stop()
                if self.stats.get('status') in ('round_cleared', 'round_failed', 'stopped'):
                    break
                if self.max_nodes is not None and self.stats['nodes'] >= self.max_nodes:
                    self.stats.update(status='completed', reason='지정한 노드 검증 완료')
                    break
                state = self._wait('탐사 화면 확인', lambda s: (v,) if (v:=self._classify(s)) else None)[0]
                self.stats['phase'] = state
                if state in EVENT_STATES and (self.event_context or state in (
                        'event','unknown_event','event_result','unknown_event_result',
                        'event_loot_consume','event_warning','rank_reward','recruit_reward','battle_rank_complete')):
                    run_event_flow(self)
                    continue
                if state == 'defeat':
                    self._defeat()
                    continue
                if state == 'expedition_summary':
                    self._finish_results()
                    break
                if state == 'exploration_entry':
                    if self.stats.get('outcome') == 'defeat':
                        self.stats.update(status='round_failed', reason='패배 결과 처리 및 초기 화면 복귀 완료')
                    else:
                        self.stats.update(status='stopped', reason='초기 화면 복귀 — 최종 클리어 정산 미확인')
                    break
                if state == 'map':
                    self.event_context = False
                    self.report_dir = None
                    self.pending_event_id = None
                    self.rejected_event_choices.clear()
                    if not self._select_node(): break
                elif state == 'battle_setup':
                    self._guarded_tap('전투 시작', state, 'battle_start')
                    self._state('전투 화면 대기', {'battle','story','story_confirm'})
                elif state == 'battle': self._battle()
                elif state in ('story','story_confirm'): self._story(state)
                elif state == 'rest': self._rest()
                elif state == 'supply': self._supply()
                elif state == 'loot': self._loot()
                elif state in ('shop', 'shop_purchase_confirm'): self._shop()
                elif state == 'shop_exit_confirm': self._shop_confirm()
                elif state == 'rank_reward': self._event_rank_reward()
                elif state == 'rank_menu':
                    self._rankup()
                    self._state('이벤트 랭크업 후 결과', EVENT_FOLLOWUPS)
                elif state in ('event','unknown_event'):
                    self.event_context = True
                    self._event()
                elif state in ('event_result','unknown_event_result'):
                    self.event_context = True
                    self._event_result()
                elif state in ('event_loot_popup', 'rank_result'):
                    close_marker = 'rank_close' if state == 'rank_result' else 'event_loot_close'
                    self._guarded_tap('전리품/결과 닫기', state, close_marker, exiting=True)
                    allowed = EVENT_FOLLOWUPS
                    next_state = self._state('결과 닫기 후 복귀', allowed)
                    if state == 'rank_result' and next_state == 'rank_reward':
                        # Resuming on an already completed rank result must not
                        # try to spend the same reward a second time.
                        self._guarded_tap('랭크업 완료 보상에서 계속 탐사', 'rank_reward', 'event_reward_continue', exiting=True)
                        next_state = self._state('랭크업 완료 후속 화면', EVENT_FOLLOWUPS - {'rank_reward'})
                    if next_state == 'map':
                        self.stats['nodes'] += 1
                elif state == 'event_loot_consume':
                    self._handle_loot_consume()
                elif state == 'levelup':
                    close_btn = self._wait('레벨업 팝업 닫기 확인', lambda s: self.observer.find(s, 'level_close') if self.observer.classify(s) == 'levelup' else None)
                    def closed(after, before):
                        return (self.observer.classify(after) != 'levelup'), None
                    self._tap_with_verify(close_btn, '레벨업 팝업 닫기', closed, expected_state='levelup')
                    allowed = EVENT_FOLLOWUPS
                    self._state('레벨업 닫기 후 복귀', allowed)
                elif state == 'victory':
                    self._victory()
                elif state == 'recruit_reward':
                    self._skip_recruit_reward()
                elif state in ('unclaimed_reward', 'event_warning'):
                    if self.event_context:
                        self._handle_event_confirm()
                    elif state == 'unclaimed_reward':
                        confirm_btn = self._wait('미획득 보상 확인 버튼', lambda s: self.observer.find(s, 'story_confirm') if self._classify(s) in ('unclaimed_reward', 'story_confirm') or self.observer.find(s, 'story_confirm') else None)
                        def closed(after, before):
                            return (self.observer.find(after, 'story_confirm') is None), None
                        self._tap_with_verify(confirm_btn, '미획득 보상 확인', closed, max_retries=3)
                        allowed = {'map','story','story_confirm','expedition_summary','exploration_entry','event','unknown_event','event_result','unknown_event_result','event_loot_popup','recruit_reward','rank_result','levelup','event_loot_consume'}
                        self._state('보상 확인 후 복귀', allowed)
                    else:
                        raise RecognitionTimeout('미등록 확인창의 의미를 확인하지 못했습니다.')
                else:
                    raise RuntimeError(f'{state}: 중간 화면에서 재개할 수 없습니다. 지도에서 시작해 주세요.')
            self._record('end')
        except _Stopped:
            self.stats.update(status='stopped', reason='사용자 중지')
        except Exception as exc:
            self.stats.update(status='failed', reason=str(exc))
            self._record('failed')
            logger.exception('노드 진행 중지')
        return self.get_stats()


class ExplorationBot:
    """GUI facade: one stop event and live stats across both stages."""
    def __init__(self, adb, root, runtime_dir, hero_ids=None, rank_priority=None, max_nodes=None, repeat_on_failure=True,
                 target_clears=1, event_mode='ocr', save_unknown_events=False, diagnostic_capture=False, auto_fallback=True,
                 buy_future_investment=False):
        self._args = (adb, root, runtime_dir, hero_ids, rank_priority, max_nodes)
        self.node_options = dict(event_mode=event_mode, save_unknown_events=save_unknown_events,
                                 diagnostic_capture=diagnostic_capture, rank_priority=rank_priority,
                                 buy_future_investment=buy_future_investment)
        self.repeat_on_failure = repeat_on_failure
        self.target_clears = max(1, int(target_clears)) if target_clears is not None else 1
        self.auto_fallback = auto_fallback
        self.cleared_rounds = 0
        self.failed_rounds = 0
        self.attempt = 1
        self.recruitment = PartyRecruitmentBot(adb, root, runtime_dir, hero_ids=hero_ids, auto_fallback=self.auto_fallback)
        self.nodes = NodeProgressionBot(adb, root, runtime_dir, max_nodes=max_nodes, **self.node_options)
        self.nodes.stop_event = self.recruitment.stop_event
        self.active = self.recruitment

    def set_user_action(self, action):
        self.active.set_user_action(action)

    def get_stats(self):
        stats = getattr(self.active, 'stats', {})
        if hasattr(self.active, 'get_stats'):
            res = self.active.get_stats()
            if isinstance(res, dict):
                stats = res
        base = dict(stats) if isinstance(stats, dict) else {}
        return dict(base,
                    cleared_rounds=self.cleared_rounds,
                    failed_rounds=self.failed_rounds,
                    target_clears=self.target_clears,
                    attempt=self.attempt)

    def run(self):
        try:
            logger.info('자동 탐사 반복 설정: 목표 완주 %d회, 패배 재도전=%s', self.target_clears, self.repeat_on_failure)
            while True:
                result = self._run_stages()
                status = result.get('status') if isinstance(result, dict) else None
                logger.info('탐사 회차 결과: %d회차, 상태=%s, 사유=%s, 누적 완주=%d/%d',
                            self.attempt, status, result.get('reason', '') if isinstance(result, dict) else '',
                            self.cleared_rounds, self.target_clears)
                if status == 'round_failed':
                    self.failed_rounds += 1
                    if not self.repeat_on_failure:
                        if hasattr(self.active, 'stats') and isinstance(self.active.stats, dict):
                            self.active.stats.update(status='stopped', reason='패배 결과 처리 후 중지')
                        base = dict(result) if isinstance(result, dict) else self.get_stats()
                        return dict(base,
                                    status='stopped',
                                    reason='패배 결과 처리 후 중지',
                                    cleared_rounds=self.cleared_rounds,
                                    failed_rounds=self.failed_rounds,
                                    target_clears=self.target_clears,
                                    attempt=self.attempt)
                    stop = self.nodes.stop_event
                    if stop.is_set(): raise _Stopped()
                    self.attempt += 1
                    adb, root, runtime_dir, hero_ids, rank_priority, max_nodes = self._args
                    self.recruitment = PartyRecruitmentBot(adb, root, runtime_dir, hero_ids=hero_ids, auto_fallback=self.auto_fallback)
                    self.nodes = NodeProgressionBot(adb, root, runtime_dir, max_nodes=max_nodes, **self.node_options)
                    self.recruitment.stop_event = self.nodes.stop_event = stop
                    self.active = self.recruitment
                    logger.info('탐사 패배 후 재도전 시작: %d회차 (완주 %d/%d회, 패배 %d회)',
                                self.attempt, self.cleared_rounds, self.target_clears, self.failed_rounds)
                    continue

                if status == 'round_cleared':
                    self.cleared_rounds += 1
                    if self.cleared_rounds >= self.target_clears:
                        if hasattr(self.active, 'stats') and isinstance(self.active.stats, dict):
                            self.active.stats.update(status='completed', reason=f'목표 완주 {self.target_clears}회 달성')
                        base = dict(result) if isinstance(result, dict) else self.get_stats()
                        base.update(status='completed', reason=f'목표 완주 {self.target_clears}회 달성')
                        return dict(base,
                                    cleared_rounds=self.cleared_rounds,
                                    failed_rounds=self.failed_rounds,
                                    target_clears=self.target_clears,
                                    attempt=self.attempt)
                    stop = self.nodes.stop_event
                    if stop.is_set(): raise _Stopped()
                    self.attempt += 1
                    adb, root, runtime_dir, hero_ids, rank_priority, max_nodes = self._args
                    self.recruitment = PartyRecruitmentBot(adb, root, runtime_dir, hero_ids=hero_ids, auto_fallback=self.auto_fallback)
                    self.nodes = NodeProgressionBot(adb, root, runtime_dir, max_nodes=max_nodes, **self.node_options)
                    self.recruitment.stop_event = self.nodes.stop_event = stop
                    self.active = self.recruitment
                    logger.info('탐사 완주 후 다음 회차 시작: %d회차 (완주 %d/%d회, 패배 %d회)',
                                self.attempt, self.cleared_rounds, self.target_clears, self.failed_rounds)
                    continue

                if isinstance(result, dict):
                    return dict(result,
                                cleared_rounds=self.cleared_rounds,
                                failed_rounds=self.failed_rounds,
                                target_clears=self.target_clears,
                                attempt=self.attempt)
                return self.get_stats()
        except _Stopped:
            if hasattr(self.active, 'stats') and isinstance(self.active.stats, dict):
                self.active.stats.update(status='stopped', reason='사용자 중지')
            return dict(self.get_stats(), status='stopped', reason='사용자 중지')
        except Exception as exc:
            if hasattr(self.active, 'stats') and isinstance(self.active.stats, dict):
                self.active.stats.update(status='failed', reason=str(exc))
            if hasattr(self.active, '_record'):
                self.active._record('failed')
            logger.exception('자동 탐사 단계 전환 실패')
            return dict(self.get_stats(), status='failed', reason=str(exc))

    def _run_stages(self):
        screen = self.nodes._capture()
        state = self.nodes.observer.classify(screen)
        if state == 'exploration_entry': state = None
        if state is None and self.recruitment._entry(screen) is None:
            self.active = self.nodes
            def ready(frame):
                kind = self.nodes.observer.classify(frame)
                if kind: return ('nodes', kind)
                return ('recruitment',) if self.recruitment._entry(frame) else None
            entry = self.nodes._wait('현재 탐사 화면 안정화 대기', ready)
            state = entry[1] if entry[0] == 'nodes' else None
        if state == 'exploration_entry': state = None
        if state is None:
            self.active = self.recruitment
            result = self.recruitment.run()
            if result['status'] != 'completed': return result
            self.nodes._wait('네 영웅 구성 및 입장 확인', lambda s: self.nodes.observer.find(s,'enter') if self.recruitment.observer.completed(s) else None)
            self.active = self.nodes
            screen = self.nodes._capture()
            if not self.recruitment.observer.completed(screen):
                raise RuntimeError('영웅 구성 상태가 변경됐습니다.')
            bounds = self.nodes.observer.find(screen, 'enter')
            if not bounds: raise RuntimeError('탐사 입장 버튼 없음')
            self.nodes._tap(bounds)
        else:
            self.active = self.nodes
        return self.nodes.run()
