import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2

from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class ConsumePlusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)
        cls.observer.config.update(poll_seconds=0, stable_frames=2)

    def image(self, name='event_loot_consume_local_live.png'):
        return read_image(str(RAW / name))

    def test_latest_and_existing_empty_slots_use_plus(self):
        for name in ('event_loot_consume_local_live.png', 'event_loot_consume_live.png',
                     'event_loot_consume_leaf_live.png'):
            with self.subTest(name=name):
                screen = self.image(name)
                self.assertTrue(self.observer.loot_consume_plus(screen))
                self.assertEqual(self.observer.classify(screen), 'event_loot_consume')
        self.assertEqual(len(self.observer.loot_consume_choices(self.image())), 4)

    def test_text_and_background_change_do_not_hide_plus(self):
        screen = self.image()
        screen[480:514, 780:1010] = 0  # Previous dialog text marker.
        x, y, w, h = self.observer.config['event_loot_consume_plus_region']
        sample = screen[y:y+h, x:x+w]
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        sample[gray < 190] = (100, 25, 100)
        self.assertEqual(self.observer.classify(screen), 'event_loot_consume')

    def test_slot_border_without_plus_does_not_authorize_empty_slot(self):
        screen = self.image()
        screen[540:575, 879:915] = 0
        self.assertFalse(self.observer.is_loot_consume(screen))

    def test_plus_requires_inventory_and_other_shapes_do_not_match(self):
        screen = self.image()
        screen[145:470, 650:1140] = 0
        self.assertTrue(self.observer.loot_consume_plus(screen))
        self.assertFalse(self.observer.is_loot_consume(screen))
        for shape in ('x', 'box', 'line'):
            with self.subTest(shape=shape):
                screen = self.image()
                region = screen[528:583, 868:923]
                region[:] = 0
                if shape == 'x':
                    cv2.line(region, (12, 13), (43, 44), (255, 255, 255), 2)
                    cv2.line(region, (12, 44), (43, 13), (255, 255, 255), 2)
                elif shape == 'box':
                    cv2.rectangle(region, (12, 13), (43, 44), (255, 255, 255), -1)
                else:
                    cv2.line(region, (12, 28), (43, 28), (255, 255, 255), 2)
                self.assertFalse(self.observer.is_loot_consume(screen))

    def test_selected_slot_remains_recognized_when_plus_disappears(self):
        screen = self.image('event_loot_consume_leaf_selected_live.png')
        self.assertFalse(self.observer.loot_consume_plus(screen))
        self.assertEqual(self.observer.classify(screen), 'event_loot_consume')
        before = self.image('event_loot_consume_leaf_live.png')
        self.assertTrue(self.observer.loot_consume_selected(screen, before[170:214, 682:726]))
        screen[510:538, 849:877] = 0
        self.assertFalse(self.observer.is_loot_consume(screen))

    def test_latest_popup_is_routed_before_hidden_event_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            bot.event_context = True
            bot._capture = Mock(return_value=self.image())
            bot._tap = Mock()
            self.assertEqual(bot._unknown_event(), 'event_loot_consume')
            bot._tap.assert_not_called()


if __name__ == '__main__':
    unittest.main()
