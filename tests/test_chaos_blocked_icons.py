import unittest
from pathlib import Path

import numpy as np

from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = ROOT / 'images/chaos/node_progression/templates/blocked_choices'


class BlockedIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_each_icon_is_detected_without_name_or_description(self):
        for name, template in self.observer.blocked:
            with self.subTest(item=name):
                screen = np.zeros((720, 1280, 3), dtype=np.uint8)
                h, w = template.shape[:2]
                screen[150:150+h, 250:250+w] = template
                found = self.observer.forbidden(screen)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0][0], name)

    def test_name_and_description_without_icon_are_not_forbidden(self):
        for name, _ in self.observer.blocked:
            with self.subTest(item=name):
                source = read_image(str(BLOCKED / (name + '.png')))
                x, y, w, h = self.observer.config['blocked_choice_crops'][name + '.png']
                source[y:y+h, x:x+w] = 0
                screen = np.zeros((720, 1280, 3), dtype=np.uint8)
                sh, sw = source.shape[:2]
                screen[100:100+sh, 200:200+sw] = source
                self.assertEqual(self.observer.forbidden(screen), [])

    def test_latest_loot_screen_is_not_blocked_by_unrelated_text(self):
        screen = read_image(str(ROOT / 'images/chaos/node_progression/raw/elite_loot_cards_local_live.png'))
        self.assertEqual(self.observer.forbidden(screen), [])
        self.assertEqual(len(self.observer.loot_choices(screen)), 3)


if __name__ == '__main__':
    unittest.main()
