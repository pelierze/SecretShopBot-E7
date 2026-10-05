import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class ReportedRewardFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)
        cls.observer.config['poll_seconds'] = 0

    def frame(self, name):
        return read_image(str(RAW / name))

    def test_reported_supply_screen_is_recognized_with_selected_card(self):
        screen = self.frame('loot_supply_selected_report_20261005.png')
        self.assertEqual(self.observer.classify(screen), 'loot')
        self.assertEqual(self.observer.selected_loot(screen), (835, 96, 250, 425))
        self.assertIsNotNone(self.observer.find(screen, 'loot_button'))
        self.assertEqual(len(self.observer.loot_choices(screen)), 3)

    def test_cards_without_button_do_not_authorize_loot_screen(self):
        screen = self.frame('loot_supply_selected_report_20261005.png')
        screen[620:705, 480:810] = 0
        self.assertEqual(len(self.observer.all(screen, 'loot_reroll')), 3)
        self.assertIsNone(self.observer.classify(screen))

    def test_dim_button_does_not_authorize_claim_before_selection(self):
        screen = self.frame('loot_cards_live.png')
        self.assertEqual(self.observer.classify(screen), 'loot')
        self.assertIsNone(self.observer.find(screen, 'loot_button'))
        self.assertIsNone(self.observer.selected_loot(screen))

    def test_popup_return_to_victory_continues_to_map(self):
        for popup, victory in [('battle/victory_levelup_live.png', 'battle/victory_live.png'),
                               ('rank_result_event_live.png', 'battle/victory_rank_complete_live.png')]:
            with self.subTest(popup=popup), tempfile.TemporaryDirectory() as tmp:
                bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, max_nodes=1)
                frames = [self.frame(popup), self.frame(victory), self.frame('map_after_rest_live.png')]
                index = [0]
                taps = []
                bot._capture = lambda: frames[index[0]]
                def tap(bounds):
                    taps.append(tuple(bounds))
                    index[0] += 1
                bot._tap = tap
                bot._rankup = Mock()
                result = bot.run()
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['nodes'], 1)
                self.assertEqual(len(taps), 2)
                self.assertEqual(taps[1], self.observer.find(frames[1], 'continue'))
                bot._rankup.assert_not_called()

    def test_supply_claim_popup_is_closed_before_leaving(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            frames = [self.frame('supply_menu_live.png'), self.frame('loot_cards_live.png'),
                      self.frame('event_loot_popup_live.png'), self.frame('supply_menu_live.png'),
                      self.frame('map_after_rest_live.png')]
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                current[0] += 1
            bot._tap = tap
            def claimed():
                current[0] = 2
                return 'event_loot_popup'
            bot._loot = Mock(side_effect=claimed)
            bot._supply()
            self.assertEqual(len(taps), 3)
            self.assertEqual(taps[1], self.observer.find(frames[2], 'event_loot_close'))
            self.assertEqual(bot.stats['nodes'], 1)

    def test_battle_claim_popup_returns_to_victory_before_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            victory = self.frame('battle/victory_live.png')
            frames = [victory, self.frame('loot_cards_live.png'), self.frame('event_loot_popup_live.png'),
                      victory, self.frame('map_after_rest_live.png')]
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                current[0] += 1
            bot._tap = tap
            def claimed():
                current[0] = 2
                return 'event_loot_popup'
            bot._loot = Mock(side_effect=claimed)
            original_find = self.observer.find
            from unittest.mock import patch
            with patch.object(self.observer, 'find', side_effect=lambda s, n, **kw:
                    (300, 500, 100, 30) if current[0] == 0 and n == 'loot_reward' else original_find(s, n, **kw)):
                bot._victory()
            self.assertEqual(taps[-1], original_find(victory, 'continue'))
            self.assertEqual(len(taps), 3)
            self.assertEqual(bot.stats['nodes'], 1)


class SupplyRetrySafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        observer = Mock()
        observer.config = {}
        self.bot = NodeProgressionBot(Mock(), ROOT, tmp.name, observer)
        self.bot.stop_event = Mock()
        self.bot.stop_event.wait.return_value = False
        self.bot._check_stop = Mock()
        self.current = 'supply'
        self.button = (930, 400, 160, 31)
        self.leave = (930, 620, 160, 31)
        self.taps = []
        self.bot._capture = lambda: self.current
        self.bot._classify = lambda screen: screen
        observer.find.side_effect = lambda screen, marker: self.button if screen == 'supply' and marker == 'supply_loot' else None
        self.bot._wait = Mock(side_effect=[('btn', *self.button), self.leave, ('map',)])
        def claimed():
            self.current = 'supply'
            return 'supply'
        self.bot._loot = Mock(side_effect=claimed)

    def test_unrecognized_transition_never_replays_supply_coordinates(self):
        def tap(bounds):
            self.taps.append(tuple(bounds))
            self.current = None if tuple(bounds) == self.button else 'map'
        self.bot._tap = tap
        self.bot._state = Mock(return_value='loot')
        self.bot._supply()
        self.assertEqual(self.taps, [self.button, self.leave])
        self.bot._loot.assert_called_once()
        self.assertEqual(self.bot.stats['nodes'], 1)

    def test_supply_retry_uses_current_button_after_wait(self):
        moved = (940, 400, 160, 31)
        def wait(seconds):
            if seconds == 3:
                self.button = moved
            return False
        self.bot.stop_event.wait.side_effect = wait
        def tap(bounds):
            self.taps.append(tuple(bounds))
            if tuple(bounds) == moved:
                self.current = 'loot'
        self.bot._tap = tap
        self.bot._supply()
        self.assertEqual(self.taps, [(930, 400, 160, 31), moved, self.leave])
        self.bot._loot.assert_called_once()
        self.bot.stop_event.wait.assert_any_call(3)

    def test_supply_transition_during_retry_delay_cancels_input(self):
        def wait(seconds):
            if seconds == 3:
                self.current = 'loot'
            return False
        self.bot.stop_event.wait.side_effect = wait
        self.bot._tap = lambda bounds: self.taps.append(tuple(bounds))
        self.bot._supply()
        self.assertEqual(self.taps, [self.button, self.leave])
        self.bot._loot.assert_called_once()


if __name__ == '__main__':
    unittest.main()
