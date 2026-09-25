import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.chaos.bot import KnightRecruitmentBot
from src.chaos.observer import KnightObserver
from src.image_matcher import read_image


ROOT = Path(__file__).resolve().parents[1]


class KnightObserverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = KnightObserver(ROOT)
        cls.raw = ROOT / 'images/chaos/hero_selection/raw'

    def screen(self, name):
        image = read_image(str(self.raw / name))
        self.assertIsNotNone(image, name)
        return image

    def test_knight_region_disambiguates_identical_recruit_buttons(self):
        screen = self.screen('Screenshot_2026.09.24_10.44.15.754.png')
        self.assertIsNone(self.observer.find(screen, 'recruit_card'))
        self.assertEqual(self.observer.knight_button(screen), (112, 490, 216, 48))

    def test_disabled_recruit_button_never_looks_active(self):
        for name in ('knight_full.png', 'knight_dark_filter.png'):
            with self.subTest(name=name):
                self.assertIsNone(self.observer.find(self.screen(name), 'recruit_active'))
        self.assertIsNotNone(self.observer.find(self.screen('knight_hero_selected_menu.png'), 'recruit_active'))

    def test_selection_and_recruitment_are_different_states(self):
        selected = self.screen('knight_hero_selected_menu.png')
        self.assertIsNotNone(self.observer.find(selected, 'rose_selected'))
        self.assertFalse(self.observer.completed(selected))
        self.assertTrue(self.observer.completed(self.screen('knight_select_finish.png')))

    def test_filter_open_and_selected_attribute_are_verified(self):
        before = self.screen('knight_filter_menu.png')
        after = self.screen('knight_dark_filter_selected_live.png')
        for screen in (before, after):
            self.assertIsNotNone(self.observer.find(screen, 'filter_panel'))
        self.assertIsNotNone(self.observer.find(before, 'dark_1'))
        self.assertIsNone(self.observer.find(before, 'dark_2'))
        self.assertIsNone(self.observer.find(after, 'dark_1'))
        self.assertIsNotNone(self.observer.find(after, 'dark_2'))

    def test_wrong_resolution_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.observer.validate_screen(np.zeros((1080, 1920, 3), dtype=np.uint8))


class ScriptedObserver:
    config = {
        'timeout_seconds': 0.1, 'poll_seconds': 0, 'stable_frames': 2,
        'popup_dismiss_point': (640, 590), 'filter_dismiss_point': (960, 590),
    }

    def __init__(self):
        self.theme = SimpleNamespace(observe=lambda s: SimpleNamespace(state=s.get('theme', 'unknown'), bounds=(100, 140, 120, 145) if 'theme' in s else None))

    def find(self, screen, name):
        return screen.get(name)

    def completed(self, screen):
        return screen.get('done', False)

    def knight_button(self, screen):
        return screen.get('knight_button')


class KnightFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adb = Mock()
        self.bot = KnightRecruitmentBot(self.adb, ROOT, self.temp.name, ScriptedObserver())
        b = (100, 100, 40, 30)
        self.frames = [
            {'start': b}, {'theme': 'unselected'}, {'theme': 'selected', 'confirm_theme': b},
            {'knight_button': b}, {'knight_header': b, 'filter': b},
            {'knight_header': b, 'filter_panel': b, 'dark_1': b},
            {'knight_header': b, 'filter_panel': b, 'dark_2': b},
            {'knight_header': b, 'rose': b},
            {'knight_header': b, 'rose': b, 'rose_selected': b, 'recruit_active': b},
            {'done': True},
        ]
        self.position = 0
        self.pending = 0

        def tap(*args, **kwargs):
            self.position += 1
            self.pending = 3
            return True

        def capture():
            self.bot._check_stop()
            if self.pending:
                self.pending -= 1
                return {}  # Loading must not cause another tap.
            return self.frames[self.position]

        self.adb.tap.side_effect = tap
        self.bot._capture = capture

    def test_full_run_waits_through_loading_and_stops_after_knight(self):
        result = self.bot.run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.adb.tap.call_count, 9)
        self.assertEqual(self.position, len(self.frames) - 1)

    def test_unlock_popup_is_dismissed_only_once(self):
        self.frames.insert(1, {'unlock': (20, 20, 60, 40)})
        self.assertEqual(self.bot.run()['status'], 'completed')
        self.assertEqual(self.adb.tap.call_count, 10)
        self.assertEqual(self.adb.tap.call_args_list[1].args, (640, 590))

    def test_already_completed_does_not_recruit_again(self):
        self.frames[0] = {'done': True}
        self.assertEqual(self.bot.run()['status'], 'completed')
        self.adb.tap.assert_not_called()

    def test_missing_hero_times_out_without_recruiting_or_scrolling(self):
        self.frames[7] = {'knight_header': (10, 10, 20, 20)}
        with self.assertLogs('src.chaos.bot', level='ERROR'):
            result = self.bot.run()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('그림자 로제 찾기', result['reason'])
        self.assertEqual(self.adb.tap.call_count, 7)
        self.adb.swipe.assert_not_called()

    def test_stop_during_transition_prevents_further_input(self):
        def stop_after_input(*args, **kwargs):
            self.bot.set_user_action('stop')
            return True
        self.adb.tap.side_effect = stop_after_input
        self.assertEqual(self.bot.run()['status'], 'stopped')
        self.assertEqual(self.adb.tap.call_count, 1)

    def test_stop_before_run_sends_no_input(self):
        self.bot.set_user_action('stop')
        self.assertEqual(self.bot.run()['status'], 'stopped')
        self.adb.tap.assert_not_called()

    def test_failed_capture_never_reads_stale_file(self):
        self.adb.screenshot.return_value = False
        with patch('src.chaos.bot.read_image') as read:
            with self.assertRaises(RuntimeError):
                KnightRecruitmentBot._capture(self.bot)
            read.assert_not_called()

    def test_failed_tap_is_not_retried(self):
        self.adb.tap.side_effect = None
        self.adb.tap.return_value = False
        with self.assertLogs('src.chaos.bot', level='ERROR'):
            self.assertEqual(self.bot.run()['status'], 'failed')
        self.assertEqual(self.adb.tap.call_count, 1)
