import unittest
from pathlib import Path

from build_support.release_assets import used_images
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class RestRankLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_local_and_original_active_options_match(self):
        for filename in ('rest_menu_local_live.png', 'rest_menu_live.png'):
            with self.subTest(filename=filename):
                screen = read_image(str(RAW / filename))
                self.assertEqual(self.observer.classify(screen), 'rest')
                self.assertIsNotNone(self.observer.find(screen, 'detail_rest'))

    def test_disabled_rankup_is_not_clicked(self):
        screen = read_image(str(RAW / 'rest_completed_live.png'))
        self.assertEqual(self.observer.classify(screen), 'rest')
        self.assertIsNone(self.observer.find(screen, 'detail_rest'))
        self.assertIsNotNone(self.observer.find(screen, 'rest_done'))

    def test_other_text_on_rest_screen_does_not_authorize_rankup(self):
        screen = read_image(str(RAW / 'rest_menu_local_live.png'))
        screen[184:210, 987:1024] = 0
        self.assertEqual(self.observer.classify(screen), 'rest')
        self.assertIsNone(self.observer.find(screen, 'detail_rest'))

    def test_detail_screen_does_not_look_like_rankup_option(self):
        screen = read_image(str(RAW / 'rest_detail_live.png'))
        self.assertIsNone(self.observer.find(screen, 'detail_rest'))

    def test_label_crop_and_source_are_packaged(self):
        self.assertEqual(self.observer.templates['detail_rest'].shape[:2], (26, 37))
        self.assertIn('images/chaos/node_progression/raw/rest_menu_local_live.png', used_images(ROOT))


if __name__ == '__main__':
    unittest.main()
