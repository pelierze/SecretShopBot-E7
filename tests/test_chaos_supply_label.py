import unittest
from pathlib import Path

from build_support.release_assets import used_images
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class SupplyLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_original_and_latest_supply_screens_match(self):
        for filename in ('supply_menu_live.png', 'supply_menu_local_live.png'):
            with self.subTest(filename=filename):
                screen = read_image(str(RAW / filename))
                self.assertIsNotNone(self.observer.find(screen, 'supply_loot'))
                self.assertEqual(self.observer.classify(screen), 'supply')

    def test_collected_option_is_rejected_by_color(self):
        screen = read_image(str(RAW / 'supply_done_live.png'))
        self.assertIsNone(self.observer.find(screen, 'supply_loot'))
        self.assertIsNotNone(self.observer.find(screen, 'supply_done'))
        self.assertEqual(self.observer.classify(screen), 'supply')

    def test_other_words_do_not_replace_missing_loot_label(self):
        screen = read_image(str(RAW / 'supply_menu_local_live.png'))
        screen[402:430, 930:985] = 0
        self.assertIsNone(self.observer.find(screen, 'supply_loot'))

    def test_other_screens_do_not_match_label(self):
        for filename in ('rest_menu_live.png', 'supply_detail_live.png', 'map_after_rest_live.png'):
            with self.subTest(filename=filename):
                self.assertIsNone(self.observer.find(read_image(str(RAW / filename)), 'supply_loot'))

    def test_label_source_is_packaged(self):
        self.assertEqual(self.observer.templates['supply_loot'].shape[:2], (28, 55))
        self.assertIn('images/chaos/node_progression/raw/supply_menu_local_live.png', used_images(ROOT))


if __name__ == '__main__':
    unittest.main()
