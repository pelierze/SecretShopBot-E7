import itertools
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.chaos.bot import RecognitionTimeout, _Stopped
from src.chaos.exploration import NodeProgressionBot


ROOT = Path(__file__).resolve().parents[1]


class PopupCloseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.observer = Mock()
        self.observer.config = dict(timeout_seconds=12, poll_seconds=0,
                                    stable_frames=2, recognition_attempts=1)
        self.bot = NodeProgressionBot(Mock(), ROOT, tmp.name, self.observer)
        self.screen = 'rank_result'
        self.bounds = (10, 20, 30, 40)
        self.bot._capture = lambda: self.screen
        self.observer.classify.side_effect = lambda screen: screen
        self.observer.find.side_effect = lambda screen, marker: self.bounds if screen == 'rank_result' else None
        self.bot._record = Mock()
        self.taps = []
        self.bot._tap = lambda bounds: self.taps.append(bounds)
        ticks = itertools.count(step=0.25)
        clock = patch('src.chaos.exploration.time.monotonic', side_effect=lambda: next(ticks))
        clock.start()
        self.addCleanup(clock.stop)

    def close(self):
        return self.bot._dismiss_popup('결과 닫기', 'rank_result', 'rank_close', {'rank_result', 'map', 'rest'})

    def test_dropped_close_is_retried_and_rest_return_is_verified(self):
        sent_at = []
        def tap(bounds):
            self.taps.append(bounds)
            sent_at.append(time.monotonic())
            if len(self.taps) == 2:
                self.screen = 'rest'
        self.bot._tap = tap
        self.assertEqual(self.close(), 'rest')
        self.assertEqual(self.taps, [self.bounds, self.bounds])
        self.assertGreaterEqual(sent_at[1] - sent_at[0], 3)

    def test_loading_then_map_does_not_receive_another_click(self):
        def tap(bounds):
            self.taps.append(bounds)
            frames = iter([None, None, 'map', 'map'])
            self.bot._capture = lambda: next(frames)
        self.bot._tap = tap
        self.assertEqual(self.close(), 'map')
        self.assertEqual(len(self.taps), 1)

    def test_unknown_screen_times_out_without_replaying_close(self):
        def tap(bounds):
            self.taps.append(bounds)
            self.screen = None
        self.bot._tap = tap
        with self.assertRaises(RecognitionTimeout):
            self.close()
        self.assertEqual(len(self.taps), 1)

    def test_remaining_popup_has_bounded_retries_and_specific_reason(self):
        with self.assertRaisesRegex(RecognitionTimeout, '결과창이 남아'):
            self.close()
        self.assertEqual(len(self.taps), 3)

    def test_transition_just_before_retry_prevents_click(self):
        wait = self.bot._wait
        def wait_then_transition(phase, predicate):
            value = wait(phase, predicate)
            if value[0] == 'retry':
                self.screen = 'map'
            return value
        self.bot._wait = wait_then_transition
        self.assertEqual(self.close(), 'map')
        self.assertEqual(len(self.taps), 1)

    def test_changed_close_coordinates_are_reobserved(self):
        wait = self.bot._wait
        old_bounds = self.bounds
        new_bounds = (50, 60, 30, 40)
        def wait_then_move(phase, predicate):
            value = wait(phase, predicate)
            if value[0] == 'retry':
                self.bounds = new_bounds
            return value
        self.bot._wait = wait_then_move
        def tap(bounds):
            self.taps.append(bounds)
            if len(self.taps) == 2:
                self.screen = 'map'
        self.bot._tap = tap
        self.assertEqual(self.close(), 'map')
        self.assertEqual(self.taps, [old_bounds, new_bounds])

    def test_loot_and_levelup_close_also_recover_dropped_input(self):
        for state, marker in [('event_loot_popup', 'event_loot_close'), ('levelup', 'level_close')]:
            with self.subTest(state=state):
                self.screen = state
                self.taps.clear()
                self.observer.find.side_effect = lambda screen, name: self.bounds if screen == state and name == marker else None
                def tap(bounds):
                    self.taps.append(bounds)
                    if len(self.taps) == 2:
                        self.screen = 'map'
                self.bot._tap = tap
                self.assertEqual(self.bot._dismiss_popup('닫기', state, marker, {'map'}), 'map')
                self.assertEqual(len(self.taps), 2)

    def test_repeated_changes_before_retry_are_bounded_without_clicks(self):
        wait = self.bot._wait
        candidates = []
        def wait_then_move(phase, predicate):
            value = wait(phase, predicate)
            if value[0] == 'retry':
                candidates.append(value)
                x, y, w, h = self.bounds
                self.bounds = (x + 1, y, w, h)
            return value
        self.bot._wait = wait_then_move
        with self.assertRaises(RecognitionTimeout):
            self.close()
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(self.taps), 1)

    def test_missing_close_control_does_not_authorize_retry(self):
        def tap(bounds):
            self.taps.append(bounds)
            self.observer.find.return_value = None
            self.observer.find.side_effect = None
        self.bot._tap = tap
        with self.assertRaises(RecognitionTimeout):
            self.close()
        self.assertEqual(len(self.taps), 1)

    def test_stop_after_first_input_prevents_retry(self):
        def tap(bounds):
            self.taps.append(bounds)
            self.bot.stop_event.set()
        self.bot._tap = tap
        with self.assertRaises(_Stopped):
            self.close()
        self.assertEqual(len(self.taps), 1)

    def test_event_reward_transition_to_rank_result_is_dispatched_without_stale_click(self):
        # Reported frame: rank animation has finished after initial generic popup recognition.
        self.assertEqual(self.bot._dismiss_popup('이벤트 닫기', 'event_loot_popup',
                         'event_loot_close', {'rank_result', 'map'}), 'rank_result')
        self.assertEqual(self.taps, [])
        def tap(bounds):
            self.taps.append(bounds)
            self.screen = 'map'
        self.bot._tap = tap
        self.assertEqual(self.close(), 'map')
        self.assertEqual(self.taps, [self.bounds])

    def test_popup_transition_immediately_before_first_click_is_reobserved(self):
        self.screen = 'event_loot_popup'
        self.observer.config['recognition_attempts'] = 3
        self.observer.find.side_effect = lambda screen, marker: self.bounds
        wait = self.bot._wait
        def transition(phase, predicate):
            value = wait(phase, predicate)
            self.screen = 'rank_result'
            return value
        self.bot._wait = transition
        self.assertEqual(self.bot._dismiss_popup('닫기', 'event_loot_popup', 'event_loot_close',
                         {'rank_result', 'map'}), 'rank_result')
        self.assertEqual(self.taps, [])

    def test_unexpected_screen_before_first_click_does_not_authorize_input(self):
        self.screen = 'shop'
        with self.assertRaises(RecognitionTimeout):
            self.bot._dismiss_popup('닫기', 'event_loot_popup', 'event_loot_close', {'rank_result', 'map'})
        self.assertEqual(self.taps, [])


if __name__ == '__main__':
    unittest.main()
