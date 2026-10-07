import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.chaos.bot import RecognitionTimeout
from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]


class Issue12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def resized_popup(self, scale):
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        for name in ('levelup', 'level_close'):
            x, y, w, h = self.observer.config['markers'][name]['crop']
            template = cv2.resize(self.observer.templates[name], None, fx=scale, fy=scale)
            th, tw = template.shape[:2]
            left, top = int(x+w/2-tw/2), int(y+h/2-th/2)
            screen[top:top+th, left:left+tw] = template
        return screen

    def test_resized_title_and_close_are_recognized_together(self):
        for scale in (.9, 1.1):
            with self.subTest(scale=scale):
                screen = self.resized_popup(scale)
                self.assertEqual(self.observer.classify(screen), 'levelup')
                x, y, w, h = self.observer.find(screen, 'level_close')
                self.assertAlmostEqual(x+w/2, 640, delta=2)
                self.assertAlmostEqual(y+h/2, 638, delta=2)

    def test_close_without_levelup_title_never_authorizes_click(self):
        screen = self.resized_popup(1.1)
        screen[90:195] = 0
        self.assertIsNone(self.observer.find(screen, 'level_close'))
        self.assertNotEqual(self.observer.classify(screen), 'levelup')

    def test_failure_screen_is_saved_without_continuous_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = NodeProgressionBot(Mock(), ROOT, directory, self.observer)
            bot.last_screen = self.resized_popup(1.1)
            bot.stats.update(phase='레벨업 팝업 닫기', reason='시간 초과')
            bot._record('failed')
            frame = read_image(str(bot.runtime_dir / 'failure.png'))
            np.testing.assert_array_equal(frame, bot.last_screen)
            report = json.loads((bot.runtime_dir / 'failure.json').read_text(encoding='utf-8'))
            self.assertEqual(report['phase'], '레벨업 팝업 닫기')
            self.assertEqual(report['state'], 'levelup')
            self.assertIsNotNone(report['markers']['level_close'])
            self.assertFalse(bot.diagnostic_capture)

    def test_failed_diagnostic_write_preserves_original_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = NodeProgressionBot(Mock(), ROOT, directory, self.observer)
            bot.last_screen = self.resized_popup(1.1)
            with patch('src.chaos.exploration.cv2.imencode', side_effect=OSError('disk full')):
                with patch('src.chaos.exploration.KnightRecruitmentBot._wait',
                           side_effect=RecognitionTimeout('original timeout')):
                    with self.assertRaisesRegex(RecognitionTimeout, 'original timeout'):
                        with patch.dict(self.observer.config, recognition_attempts=1):
                            bot._wait('test', Mock())

    def test_supply_entry_routes_intermediate_popup_before_leaving(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = NodeProgressionBot(Mock(), ROOT, directory, Mock())
            bot._capture = Mock(return_value='frame')
            bot._classify = Mock(return_value=None)
            bot.observer.find.side_effect = lambda frame, name: (1, 2, 3, 4) if name == 'supply_loot' else None
            bot._wait = Mock(return_value=('btn', 1, 2, 3, 4))
            bot._tap = Mock()
            bot._state = Mock(return_value='event_loot_popup')
            bot._settle_reward_popups = Mock(return_value='map')
            bot._supply()
            self.assertIn('event_loot_popup', bot._state.call_args.args[1])
            bot._settle_reward_popups.assert_called_once_with('event_loot_popup', {'loot', 'supply', 'map'})
            bot._tap.assert_called_once()
            self.assertEqual(bot.stats['nodes'], 1)
