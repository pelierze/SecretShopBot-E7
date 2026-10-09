import unittest
from pathlib import Path

from build_support.release_assets import used_images
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class LootCloseIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_local_and_original_loot_popups_match_cross(self):
        for filename in ('event_loot_popup_local_live.png', 'event_loot_popup_live.png'):
            with self.subTest(filename=filename):
                screen = read_image(str(RAW / filename))
                self.assertEqual(self.observer.classify(screen), 'event_loot_popup')
                self.assertIsNotNone(self.observer.find(screen, 'event_loot_close'))

    def test_instruction_and_loot_name_are_not_required(self):
        screen = read_image(str(RAW / 'event_loot_popup_local_live.png'))
        screen[680:715, 605:730] = 0
        screen[290:340, 510:770] = 0
        self.assertEqual(self.observer.classify(screen), 'event_loot_popup')

    def test_missing_cross_does_not_authorize_close(self):
        screen = read_image(str(RAW / 'event_loot_popup_local_live.png'))
        screen[684:704, 584:604] = 0
        self.assertIsNone(self.observer.find(screen, 'event_loot_close'))

    def test_other_screens_do_not_match_cross(self):
        for filename in ('map_after_rest_live.png', 'rest_menu_live.png',
                         'loot_cards_live.png', 'event_rank_reward_live.png',
                         'event_recruit_reward_live.png', 'battle/victory_levelup_arrow_live.png'):
            with self.subTest(filename=filename):
                screen = read_image(str(RAW / filename))
                self.assertIsNone(self.observer.find(screen, 'event_loot_close'))

    def test_cross_source_is_packaged(self):
        self.assertEqual(self.observer.templates['event_loot_close'].shape[:2], (20, 20))
        self.assertIn('images/chaos/node_progression/raw/event_loot_popup_local_live.png', used_images(ROOT))


if __name__ == '__main__':
    unittest.main()
