"""Connect recruitment to verified exploration nodes with shared cancellation."""

import logging
import time
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import cv2

from .bot import KnightRecruitmentBot, PartyRecruitmentBot, _Stopped
from .node_observer import NodeObserver
from .event_policy import KoreanEventReader, choose_read_choice

logger = logging.getLogger(__name__)


class NodeProgressionBot(KnightRecruitmentBot):
    def __init__(self, adb, root, runtime_dir, observer=None, max_nodes=None,
                 event_mode='ocr', save_unknown_events=False, diagnostic_capture=False):
        super().__init__(adb, root, runtime_dir, observer or NodeObserver(root))
        if event_mode not in ('ocr','random'): raise ValueError('지원하지 않는 이벤트 처리 방식')
        self.event_mode = event_mode
        self.save_unknown_events = save_unknown_events
        self.diagnostic_capture = diagnostic_capture
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
        self.stats.update(nodes=0, auto_verified=False)

    def _capture(self):
        self._check_stop()
        screen = self.adb.capture_frame()
        self._check_stop()
        self.observer.validate_screen(screen)
        self.last_screen = screen
        if self.diagnostic_capture:
            cv2.imencode('.png',screen)[1].tofile(str(self.screen_path))
        return screen

    def _record(self, label):
        if self.diagnostic_capture: super()._record(label)
        if label == 'failed' and self.last_screen is not None:
            if self.event_context and self.report_dir is None and self.observer.classify(self.last_screen) is None:
                self._start_report(self.last_screen, {'mode': self.event_mode,
                    'stage': 'unrecognized_event', 'reason': self.stats.get('reason','')})
            self._report('failed', self.last_screen)

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

    def _tap_with_verify(self, bounds, phase, predicate, max_retries=3, wait_seconds=1.2):
        for attempt in range(1, max_retries + 1):
            before = self._capture()
            self._tap(bounds)
            deadline = time.monotonic() + wait_seconds
            after = None
            while time.monotonic() < deadline:
                after = self._capture()
                ok, res = predicate(after, before)
                if ok:
                    return res
                if self.stop_event.wait(0.25):
                    raise _Stopped()
            if after is None:
                after = self._capture()
            diff = float(np.mean(np.abs(after.astype(float) - before.astype(float)))) if isinstance(after, np.ndarray) and isinstance(before, np.ndarray) else 0.0
            logger.warning(
                '자동 탐사 [%s]: 입력 신호 후 진행 확인 안 됨 (시도 %d/%d, 화면 변화도: %.2f) — 재입력 시도',
                phase, attempt, max_retries, diff
            )
        return None

    def _classify(self, screen):
        state = self.observer.classify(screen)
        if state is not None: return state
        if self.event_context:
            if self.observer.event_cards(screen): return 'unknown_event'
            if self.observer.find(screen,'event_advance'): return 'unknown_event_result'
        return None

    def _state(self, phase, allowed, retry_tap=None, max_retries=3):
        def check(s):
            kind = self._classify(s)
            return (kind,) if kind in allowed else None

        if retry_tap is not None:
            for attempt in range(1, max_retries + 1):
                before = self._capture()
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    after = self._capture()
                    val = check(after)
                    if val is not None:
                        return val[0]
                    if self.stop_event.wait(0.2):
                        raise _Stopped()
                diff = float(np.mean(np.abs(after.astype(float) - before.astype(float)))) if isinstance(before, np.ndarray) and isinstance(after, np.ndarray) else 0.0
                logger.warning('자동 탐사 [%s]: 입력 후 다음 화면 미진행 (시도 %d/%d, 화면 변화도: %.2f) — 재입력 시도',
                               phase, attempt, max_retries, diff)
                self._tap(retry_tap)

        return self._wait(phase, check)[0]

    def _guarded_tap(self, phase, state, marker, *, exiting=False):
        def ready(screen):
            if self.observer.classify(screen) != state:
                return None
            if self.observer.forbidden(screen) and not exiting:
                raise RuntimeError('금지 항목이 발견되어 입력을 중지했습니다.')
            return self.observer.find(screen, marker)
        bounds = self._wait(phase, ready)
        # Do not click coordinates from a prior frame if screen changes meanwhile.
        if ready(self._capture()) != bounds:
            raise RuntimeError('클릭 직전 화면이 변경되어 중지했습니다.')
        self._tap(bounds)

    def _story(self, state):
        if state == 'story':
            self._guarded_tap('스토리 건너뛰기', 'story', 'skip')
            self._state('스토리 확인 팝업 대기', {'story_confirm'})
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
            state = self.observer.classify(screen)
            if state == 'defeat':
                self.stats['outcome'] = 'defeat'
                return
            if state in ('victory', 'levelup'):
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
        rank = self.observer.rank(screen, 'wukong')
        if rank is None:
            jenua_rank = None
            try:
                jenua_rank = self.observer.rank(screen, 'jenua')
            except Exception:
                pass
            if jenua_rank is not None and jenua_rank < 5:
                logger.info('오공 랭크 판독 불가 — 오공 5랭크(MAX)로 판단하여 제뉴아(%d랭크)로 전환합니다.', jenua_rank)
                rank = 5
            else:
                raise RuntimeError('오공 랭크를 확실하게 읽지 못했습니다.')
        target = 'wukong' if rank < 5 else 'jenua'
        current = rank if target == 'wukong' else self.observer.rank(screen, target)
        if current is None or current >= 5:
            raise RuntimeError('제뉴아 랭크업 가능 여부를 확인하지 못했습니다.')
        bounds = self.observer.find(screen, target)
        return (target, current, *bounds) if bounds else None

    def _rankup(self):
        target = self._wait('오공 우선 랭크 확인', self._rank_target)
        if self._rank_target(self._capture()) != target:
            raise RuntimeError('랭크업 대상이 변경됐습니다.')
        hero, old_rank, *bounds = target
        self._tap(bounds)
        # Selected hero name in the left detail panel must match the target name.
        def selected(screen):
            if self.observer.classify(screen) != 'rank_menu': return None
            if self.observer.forbidden(screen): raise RuntimeError('금지 항목 발견')
            return self.observer.find(screen, 'rank_button') if self.observer.find(screen, hero+'_selected') else None
        button = self._wait('선택 영웅과 랭크업 버튼 확인', selected)
        if selected(self._capture()) != button: raise RuntimeError('랭크업 선택 상태 변경')
        self._tap(button)
        self._state('랭크업 결과 대기', {'rank_result'})
        result = self._capture()
        if self.observer.read_rank_digit(result[540:568,365:384]) != old_rank+1:
            raise RuntimeError('랭크업 후 숫자가 예상과 다릅니다. 결과 화면에서 중지합니다.')
        close_btn = self._wait('랭크업 결과 닫기 확인', lambda s: self.observer.find(s, 'rank_close') if self.observer.classify(s) == 'rank_result' else None)
        def closed(after, before):
            return (self.observer.classify(after) != 'rank_result'), None
        self._tap_with_verify(close_btn, '랭크업 결과 닫기', closed, max_retries=3)

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
        self._state('휴식 후 지도 복귀', {'map'}, retry_tap=leave_btn)
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
            for attempt in range(1, 4):
                fresh = self._capture()
                if self.observer.selected_loot(fresh) == target:
                    break
                if attempt < 3:
                    diff = float(np.mean(np.abs(fresh.astype(float) - screen.astype(float)))) if isinstance(fresh, np.ndarray) and isinstance(screen, np.ndarray) else 0.0
                    logger.warning('자동 탐사 [전리품 카드 선택]: 카드 선택 미반영 (시도 %d/3, 화면 변화도: %.2f) — 재선택 시도', attempt, diff)
                    self._tap(target)
                    if self.stop_event.wait(0.3):
                        raise _Stopped()
        def confirmed(screen):
            if self.observer.classify(screen) != 'loot': return None
            allowed = self.observer.loot_choices(screen)
            if target not in allowed: raise RuntimeError('선택 전리품이 금지 항목으로 확인됐습니다.')
            if self.observer.selected_loot(screen) != target: return None
            return self.observer.find(screen, 'loot_button')
        button = self._wait('허용 전리품 선택 상태 확인', confirmed)
        if confirmed(self._capture()) != button: raise RuntimeError('전리품 확정 직전 화면 변경')
        self._tap(button)
        self._state('전리품 수령 후 복귀', {'supply','victory','map','event_result','unknown_event_result'}, retry_tap=button)

    def _supply(self):
        if not self.observer.find(self._capture(), 'supply_done'):
            self._guarded_tap('보급: 전리품 획득', 'supply', 'supply_loot')
            self._state('보급 전리품 목록', {'loot'})
            self._loot()
        leave_btn = self._wait('보급 떠나기 확인', lambda s: self.observer.find(s, 'leave') if self.observer.classify(s) == 'supply' else None)
        self._state('보급 후 지도 복귀', {'map'}, retry_tap=leave_btn)
        self.stats['nodes'] += 1

    def _shop(self):
        self._guarded_tap('상점 구매 없이 나가기', 'shop', 'shop_exit', exiting=True)
        state = self._state('상점 퇴장 확인', {'map','shop_exit_confirm'})
        if state == 'shop_exit_confirm':
            self._shop_confirm()
        else:
            self.stats['nodes'] += 1

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
        self._record('expedition_summary')
        self._guarded_tap('탐사 정산 닫기', 'expedition_summary', 'summary_close', exiting=True)
        self._state('탐사 초기 화면 복귀', {'exploration_entry'})
        if self.stats.get('outcome') == 'defeat':
            self.stats.update(status='round_failed', reason='패배 결과 처리 및 초기 화면 복귀 완료')
        else:
            self.stats.update(status='stopped', reason='탐사 결과 복귀 완료 — 이전 승패 미확인')

    def _event(self):
        if not self.observer.known_event(self._capture()):
            return self._unknown_event()
        target = self._wait('허용 이벤트 우선순위 확인', self.observer.event_choice)
        if self.observer.event_choice(self._capture()) != target:
            raise RuntimeError('이벤트 선택 직전 화면 변경')
        self._last_event_choice_bounds = target
        self._tap(target)
        state = self._event_transition()
        if state == 'map': self.stats['nodes'] += 1

    def _event_transition(self, previous_signature=None):
        states = {'battle_setup','battle','map','story','story_confirm','rank_menu','event_result',
                  'event_loot_popup','unknown_event_result','unknown_event','loot','unclaimed_reward','recruit_reward','levelup'}
        def changed(screen):
            state = self._classify(screen)
            if state in ('unknown_event', 'event'):
                if previous_signature is not None and self._event_signature(screen) == previous_signature:
                    return None
            return (state,) if state in states else None

        retry_bounds = getattr(self, '_last_event_choice_bounds', None)
        if retry_bounds is not None:
            for attempt in range(1, 4):
                before = self._capture()
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    after = self._capture()
                    val = changed(after)
                    if val is not None:
                        state = val[0]
                        self._report('result', self._capture(), {'state': state})
                        return state
                    if self.stop_event.wait(0.2):
                        raise _Stopped()
                diff = float(np.mean(np.abs(after.astype(float) - before.astype(float)))) if isinstance(before, np.ndarray) and isinstance(after, np.ndarray) else 0.0
                logger.warning('자동 탐사 [이벤트 선택]: 입력 신호 후 진행/변화 없음 (시도 %d/3, 화면 변화도: %.2f) — 재입력 시도',
                               attempt, diff)
                self._tap(retry_bounds)

        state = self._wait('이벤트 선택 결과 확인', changed)[0]
        self._report('result',self._capture(),{'state':state})
        return state

    def _unknown_event(self):
        def ready(screen):
            if self._classify(screen) != 'unknown_event': return None
            cards = self.observer.event_cards(screen)
            return (tuple(cards),self._event_signature(screen)) if cards else None
        cards, signature = self._wait('미등록 이벤트 선택지 2/3개 확인',ready)
        screen = self._capture()
        if ready(screen) != (cards,signature): raise RuntimeError('이벤트 선택지가 변경됐습니다.')
        self._start_report(screen,{'mode':self.event_mode,'cards':cards})
        available = self.observer.available_event_cards(screen,cards)
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
        if ready(fresh) != (cards,signature) or target not in self.observer.available_event_cards(fresh,cards):
            raise RuntimeError('이벤트 입력 직전 선택지 변경')
        if self.event_mode == 'ocr':
            confirmed = self.event_reader.choices(fresh,[target])[0]
            if any(confirmed[k] != selected[k] for k in ('title','effect','rule')):
                raise RuntimeError('이벤트 효과 재확인 불일치')
            fresh = self._capture()
            if ready(fresh) != (cards,signature) or target not in self.observer.available_event_cards(fresh,cards):
                raise RuntimeError('이벤트 재확인 중 화면 변경')
        self._report('selected',fresh,{'mode':self.event_mode,'target':target,'ocr':rows})
        self._last_event_choice_bounds = target
        self._tap(target)
        state = self._event_transition(signature)
        if state == 'map': self.stats['nodes'] += 1

    def _event_result(self):
        def ready(screen):
            if self._classify(screen) not in ('event_result','unknown_event_result'): return None
            if self.observer.forbidden(screen): raise RuntimeError('이벤트 결과에서 금지 이미지 발견')
            # The continuation arrow bobs; compare the page identity and use its
            # verified hit region instead of requiring identical animation pixels.
            if not self.observer.find(screen, 'event_advance'): return None
            identity = self.observer.event_result_marker(screen) or self._event_signature(screen)
            return (identity, *self.observer.config['event_advance_bounds'])
        target = self._wait('확인된 이벤트 결과 닫기', ready)
        screen = self._capture()
        if ready(screen) != target: raise RuntimeError('이벤트 결과 화면 변경')
        if self._classify(screen) == 'unknown_event_result':
            self._start_report(screen,{'mode':self.event_mode,'stage':'result'})
        self._report('dialogue',screen)
        target_sig = self._event_signature(screen)
        self._tap(target[1:])
        def changed(screen):
            state = self._classify(screen)
            if state == 'map': return (state,)
            if state in ('event_result','unknown_event_result'):
                page = ready(screen)
                if page and (page[0] != target[0] or self._event_signature(screen) != target_sig): return (state,)
            if state in ('event','unknown_event','rank_menu','event_loot_popup','battle_setup','levelup','recruit_reward'): return (state,)
            return None

        advanced = False
        for attempt in range(1, 4):
            before = self._capture()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                after = self._capture()
                val = changed(after)
                if val is not None:
                    state = val[0]
                    advanced = True
                    break
                if self.stop_event.wait(0.2):
                    raise _Stopped()
            if advanced:
                break
            diff = float(np.mean(np.abs(after.astype(float) - before.astype(float)))) if isinstance(before, np.ndarray) and isinstance(after, np.ndarray) else 0.0
            logger.warning('자동 탐사 [이벤트 결과 닫기]: 입력 신호 후 다음 화면 미진행 (시도 %d/3, 화면 변화도: %.2f) — 재입력 시도',
                           attempt, diff)
            self._tap(target[1:])

        if not advanced:
            state = self._wait('이벤트 결과 다음 화면', changed)[0]
        if state == 'map': self.stats['nodes'] += 1

    def _victory(self):
        if self.observer.find(self._capture(), 'loot_reward'):
            self._guarded_tap('전투 보상 전리품 선택', 'victory', 'loot_reward')
            self._state('전투 보상 전리품 목록', {'loot'})
            self._loot()
        # A hero reward is not part of the configured party; do not recruit it.
        skip_hero = bool(self.observer.find(self._capture(), 'reward_hero'))
        self._guarded_tap('계속 탐사하기', 'victory', 'continue', exiting=True)
        allowed = {'map','story','story_confirm','event_result','unknown_event_result'}
        if skip_hero: allowed.add('unclaimed_reward')
        state = self._state('승리 후 다음 화면 확인', allowed)
        if state == 'unclaimed_reward':
            self._guarded_tap('추가 영웅 보상 없이 진행', state, 'story_confirm', exiting=True)
            self._state('보상 확인 후 복귀', {'map','story','story_confirm'})
        if state not in ('event_result','unknown_event_result'): self.stats['nodes'] += 1

    def _skip_recruit_reward(self):
        btn = self._wait('영웅 영입 건너뛰기 버튼 확인', lambda s: self.observer.find(s, 'recruit_continue') if self.observer.classify(s) == 'recruit_reward' else None)
        self._tap(btn)
        allowed = {'map','story','story_confirm','unclaimed_reward','event_result','unknown_event_result'}
        state = self._state('영웅 영입 건너뛰기 후 확인', allowed, retry_tap=btn)
        if state == 'unclaimed_reward':
            confirm_btn = self._wait('추가 영웅 보상 확인 버튼', lambda s: self.observer.find(s, 'story_confirm') if self.observer.classify(s) == 'unclaimed_reward' else None)
            self._tap(confirm_btn)
            self._state('보상 확인 후 복귀', {'map','story','story_confirm'}, retry_tap=confirm_btn)

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
        if choose(self._capture()) != target: raise RuntimeError('노드 후보 변경')
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
        if kind == 'event': allowed.update({'unknown_event','event_result','unknown_event_result'})
        self._state('노드 내부 진입 확인', allowed, retry_tap=enter_bounds)
        return True

    def run(self):
        self.stats.update(status='running', reason='')
        try:
            while True:
                self._check_stop()
                if self.max_nodes is not None and self.stats['nodes'] >= self.max_nodes:
                    self.stats.update(status='completed', reason='지정한 노드 검증 완료')
                    break
                state = self._wait('탐사 화면 확인', lambda s: (v,) if (v:=self._classify(s)) else None)[0]
                self.stats['phase'] = state
                if state == 'defeat':
                    self._defeat()
                    continue
                if state == 'expedition_summary':
                    self._finish_results()
                    break
                if state == 'map':
                    self.event_context = False
                    self.report_dir = None
                    if not self._select_node(): break
                elif state == 'battle_setup':
                    self._guarded_tap('전투 시작', state, 'battle_start')
                    self._state('전투 화면 대기', {'battle','story','story_confirm'})
                elif state == 'battle': self._battle()
                elif state in ('story','story_confirm'): self._story(state)
                elif state == 'rest': self._rest()
                elif state == 'supply': self._supply()
                elif state == 'loot': self._loot()
                elif state == 'shop': self._shop()
                elif state == 'shop_exit_confirm': self._shop_confirm()
                elif state == 'rank_menu':
                    self._rankup()
                    self._state('이벤트 랭크업 후 결과', {'event_result','unknown_event_result','map','levelup','event_loot_popup','event'})
                elif state in ('event','unknown_event'):
                    self.event_context = True
                    self._event()
                elif state in ('event_result','unknown_event_result'):
                    self.event_context = True
                    self._event_result()
                elif state == 'event_loot_popup':
                    self._guarded_tap('이벤트 전리품 결과 닫기', state, 'event_loot_close', exiting=True)
                    self._state('이벤트 전리품 후 결과', {'event_result','unknown_event_result','map','levelup'})
                elif state == 'levelup':
                    close_btn = self._wait('레벨업 팝업 닫기 확인', lambda s: self.observer.find(s, 'level_close') if self.observer.classify(s) == 'levelup' else None)
                    def closed(after, before):
                        return (self.observer.classify(after) != 'levelup'), None
                    self._tap_with_verify(close_btn, '레벨업 팝업 닫기', closed, max_retries=3)
                    self._state('레벨업 닫기 후 복귀', {'victory', 'event_result', 'unknown_event_result', 'event', 'map', 'battle', 'levelup'})
                elif state == 'victory':
                    self._victory()
                elif state == 'recruit_reward':
                    self._skip_recruit_reward()
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
    def __init__(self, adb, root, runtime_dir, hero_ids=None, max_nodes=None, repeat_on_failure=True,
                 event_mode='ocr', save_unknown_events=False, diagnostic_capture=False):
        self._args = (adb, root, runtime_dir, hero_ids, max_nodes)
        self.node_options = dict(event_mode=event_mode,save_unknown_events=save_unknown_events,diagnostic_capture=diagnostic_capture)
        self.repeat_on_failure = repeat_on_failure
        self.failed_rounds = 0
        self.attempt = 1
        self.recruitment = PartyRecruitmentBot(adb, root, runtime_dir, hero_ids=hero_ids)
        self.nodes = NodeProgressionBot(adb, root, runtime_dir, max_nodes=max_nodes, **self.node_options)
        self.nodes.stop_event = self.recruitment.stop_event
        self.active = self.recruitment

    def set_user_action(self, action):
        self.active.set_user_action(action)

    def get_stats(self):
        return dict(self.active.get_stats(), failed_rounds=self.failed_rounds, attempt=self.attempt)

    def run(self):
        try:
            while True:
                result = self._run_stages()
                if result.get('status') != 'round_failed':
                    return dict(result, failed_rounds=self.failed_rounds, attempt=self.attempt)
                self.failed_rounds += 1
                if not self.repeat_on_failure:
                    self.active.stats.update(status='stopped', reason='패배 결과 처리 후 중지')
                    break
                stop = self.nodes.stop_event
                if stop.is_set(): raise _Stopped()
                self.attempt += 1
                adb, root, runtime_dir, hero_ids, max_nodes = self._args
                self.recruitment = PartyRecruitmentBot(adb, root, runtime_dir, hero_ids=hero_ids)
                self.nodes = NodeProgressionBot(adb, root, runtime_dir, max_nodes=max_nodes, **self.node_options)
                self.recruitment.stop_event = self.nodes.stop_event = stop
                self.active = self.recruitment
                logger.info('탐사 패배 후 새 회차 시작: %s', self.attempt)
        except _Stopped:
            self.active.stats.update(status='stopped', reason='사용자 중지')
        except Exception as exc:
            self.active.stats.update(status='failed', reason=str(exc))
            self.active._record('failed')
            logger.exception('자동 탐사 단계 전환 실패')
        return self.get_stats()

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
