"""Event traversal is a bounded loop over observed screens, not event names."""
import logging
import time
from collections import Counter

from .bot import RecognitionTimeout

logger = logging.getLogger(__name__)
TERMINALS = {'defeat', 'expedition_summary', 'exploration_entry'}
EVENT_STATES = {'event', 'unknown_event', 'event_result', 'unknown_event_result',
                'event_loot_consume', 'event_warning', 'unclaimed_reward',
                'rank_reward', 'rank_menu', 'rank_result', 'event_loot_popup',
                'loot', 'recruit_reward', 'levelup', 'victory', 'story',
                'story_confirm', 'battle_setup', 'battle', 'battle_rank_complete'}


def run_event_flow(bot):
    """Re-observe after every handler. Only a stable map completes this node."""
    bot.event_context = True
    starting_nodes = bot.stats['nodes']
    deadline = time.monotonic() + bot.observer.config.get('event_timeout_seconds', 1200)
    limit = bot.observer.config.get('event_max_steps', 100)
    visits = Counter()
    for step in range(1, limit + 1):
        bot._check_stop()
        if time.monotonic() >= deadline:
            raise RecognitionTimeout('이벤트 전체 진행 시간 초과')
        state = bot._state('이벤트 현재 화면 재판별', EVENT_STATES | TERMINALS | {'map'})
        bot.stats['event_step'] = step
        bot.stats['phase'] = '이벤트: ' + state
        logger.info('이벤트 흐름 %d: %s', step, state)
        if state == 'map':
            bot.stats['nodes'] = starting_nodes + 1
            bot.event_context = False
            bot.pending_event_id = None
            bot.rejected_event_choices.clear()
            bot._last_event_choice_bounds = None
            logger.info('이벤트 완료: 지도 복귀 확인')
            return state
        if state in TERMINALS:
            return state
        signature = bot._event_signature(bot._capture())
        visits[state, signature] += 1
        if visits[state, signature] > bot.observer.config.get('event_same_page_limit', 6):
            raise RecognitionTimeout('동일 이벤트 화면 반복 — 추가 입력 없이 중지')
        bot._dispatch_event_screen(state)
    raise RecognitionTimeout('이벤트 화면 처리 횟수 제한 초과')
