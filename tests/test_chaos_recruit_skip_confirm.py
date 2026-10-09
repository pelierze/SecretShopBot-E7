import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.chaos.bot import RecognitionTimeout
from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class RecruitSkipConfirmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)
        cls.observer.config.update(poll_seconds=0, stable_frames=2, timeout_seconds=5, recognition_attempts=1)
        cls.dialog = read_image(str(RAW / 'recruit_skip_confirm_local_live.png'))
        cls.battle_dialog = read_image(str(RAW / 'battle_hero_skip_confirm_local_live.png'))
        cls.battle_rewards = read_image(str(RAW / 'boss_victory_rewards_live.png'))
        cls.map_frame = read_image(str(RAW / 'map_after_rest_live.png'))

    def bot(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        bot = NodeProgressionBot(Mock(), ROOT, directory.name, self.observer)
        bot._guarded_tap = Mock()
        bot._tap = Mock()
        bot._state = Mock(return_value='map')
        return bot

    def test_reported_dialog_confirms_only_after_skip_input(self):
        self.assertEqual(self.observer.classify(self.dialog), 'event_warning')
        bot = self.bot()
        bot._capture = Mock(return_value=self.dialog)
        self.assertEqual(bot._skip_recruit_reward(), 'map')
        bot._guarded_tap.assert_called_once_with('영웅 영입 건너뛰기 버튼 확인',
                                               'recruit_reward', 'recruit_continue', exiting=True)
        bot._tap.assert_called_once_with(self.observer.find(self.dialog, 'story_confirm'))
        self.assertFalse(bot._recruit_skip_confirmation_pending)

    def test_reported_battle_warning_confirms_after_verified_hero_skip(self):
        self.assertEqual(self.observer.classify(self.battle_dialog), 'event_warning')
        # Model the already-claimed loot card, leaving the real hero button.
        rewards = self.battle_rewards.copy()
        rewards[495:570, 560:710] = 0
        self.assertIsNotNone(self.observer.find(rewards, 'reward_hero'))
        self.assertIsNone(self.observer.find(rewards, 'loot_reward'))
        for path in ('normal', 'event', 'rank_complete'):
            with self.subTest(path=path):
                bot = self.bot()
                bot.event_context = path == 'event'
                frames = iter([rewards] * (3 if path == 'normal' else 2 if path == 'event' else 1))
                bot._capture = lambda: next(frames, self.battle_dialog)
                if path == 'rank_complete':
                    self.assertEqual(bot._dispatch_event_screen('battle_rank_complete'), 'map')
                else:
                    result = bot._victory()
                    if path == 'event':
                        self.assertEqual(result, 'map')
                    else:
                        self.assertEqual(bot.stats['nodes'], 1)
                bot._tap.assert_called_once_with(self.observer.find(self.battle_dialog, 'story_confirm'))
                self.assertEqual(bot._guarded_tap.call_count, 1)
                self.assertFalse(bot._recruit_skip_confirmation_pending)

    def test_battle_warning_without_hero_reward_is_not_confirmed(self):
        bot = self.bot()
        bot.event_context = True
        bot._capture = Mock(return_value=read_image(str(RAW / 'battle/victory_live.png')))
        bot._state.return_value = 'event_warning'
        self.assertEqual(bot._victory(), 'event_warning')
        bot._capture.return_value = self.battle_dialog
        bot._handle_event_confirm()
        bot._tap.assert_called_once_with(self.observer.find(self.battle_dialog, 'story_cancel'))

    def test_failed_continue_input_never_authorizes_confirmation(self):
        bot = self.bot()
        bot._guarded_tap.side_effect = RecognitionTimeout('continue not verified')
        bot._capture = Mock(return_value=self.battle_dialog)
        with self.assertRaises(RecognitionTimeout):
            bot._skip_recruit_reward()
        bot._tap.assert_not_called()
        self.assertFalse(getattr(bot, '_recruit_skip_confirmation_pending', False))

    def test_same_dialog_outside_skip_context_is_still_cancelled(self):
        bot = self.bot()
        bot._capture = Mock(return_value=self.dialog)
        bot._handle_event_confirm()
        bot._tap.assert_called_once_with(self.observer.find(self.dialog, 'story_cancel'))

    def test_direct_map_return_needs_no_confirmation(self):
        bot = self.bot()
        bot._capture = Mock(return_value=self.map_frame)
        self.assertEqual(bot._skip_recruit_reward(), 'map')
        bot._tap.assert_not_called()
        self.assertFalse(bot._recruit_skip_confirmation_pending)

    def test_single_button_does_not_authorize_confirmation(self):
        screen = self.dialog.copy()
        screen[420:540, 470:620] = 0
        bot = self.bot()
        bot._capture = Mock(return_value=screen)
        with self.assertRaises(RecognitionTimeout):
            bot._skip_recruit_reward()
        bot._tap.assert_not_called()
        self.assertFalse(bot._recruit_skip_confirmation_pending)

    def test_screen_change_before_input_does_not_click_stale_confirm(self):
        bot = self.bot()
        frames = iter([self.dialog, self.dialog, self.map_frame])
        bot._capture = lambda: next(frames, self.map_frame)
        # Allow the read-only retry after the pre-input screen changes.
        original = self.observer.config['recognition_attempts']
        self.observer.config['recognition_attempts'] = 2
        try:
            self.assertEqual(bot._skip_recruit_reward(), 'map')
        finally:
            self.observer.config['recognition_attempts'] = original
        bot._tap.assert_not_called()
        self.assertFalse(bot._recruit_skip_confirmation_pending)


if __name__ == '__main__':
    unittest.main()
