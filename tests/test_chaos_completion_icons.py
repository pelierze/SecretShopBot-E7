import unittest
from pathlib import Path

from build_support.release_assets import used_images
from src.chaos.observer import RecruitmentObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/hero_selection/raw'


class CompletionIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = RecruitmentObserver(ROOT)

    def frame(self, name):
        return read_image(str(RAW / name))

    def test_latest_report_recognizes_knight_completion_without_text(self):
        screen = self.frame('knight_local_recruited.png')
        knight = self.observer.heroes[0]
        self.assertIsNone(self.observer.find(screen, 'completed'))
        self.assertIsNone(self.observer.find(screen, 'completed_rose'))
        self.assertTrue(self.observer.hero_completed(screen, knight))
        screen[418:505, 100:340] = 0
        self.assertTrue(self.observer.hero_completed(screen, knight))
        self.assertFalse(self.observer.completed(screen))

    def test_every_class_works_without_completion_label_or_name(self):
        screen = self.frame('thief_jenua_recruited_live.png')
        for hero in self.observer.heroes:
            slot = self.observer.config['classes'][hero['class']]['slot']
            screen[418:505, 100 + slot*280:340 + slot*280] = 0
        self.assertTrue(self.observer.completed(screen))

    def test_wrong_class_icon_or_missing_icon_cannot_complete_a_slot(self):
        original = self.frame('thief_jenua_recruited_live.png')
        for index, hero in enumerate(self.observer.heroes):
            with self.subTest(role=hero['class']):
                screen = original.copy()
                x = 300 + index*280
                other = 300 + ((index+1) % 4)*280
                screen[505:533, x:x+28] = original[505:533, other:other+28]
                self.assertFalse(self.observer.hero_completed(screen, hero))
                self.assertFalse(self.observer.completed(screen))
                screen[498:543, x-8:x+37] = 0
                self.assertFalse(self.observer.hero_completed(screen, hero))

    def test_tickets_and_list_icons_do_not_count_as_completed_cards(self):
        for filename in ('Screenshot_2026.09.24_10.44.15.754.png',
                         'knight_local_gold_selected.png', 'warrier_wukong_full_selected.png',
                         'soul_weaver_destina_full_selected.png', 'thief_jenua_full_selected.png'):
            with self.subTest(filename=filename):
                screen = self.frame(filename)
                self.assertFalse(any(self.observer.hero_completed(screen, hero)
                                     for hero in self.observer.heroes))

    def test_completed_class_is_shared_by_all_heroes_of_that_class(self):
        screen = self.frame('thief_jenua_recruited_live.png')
        for hero in self.observer.config['heroes'].values():
            self.assertTrue(self.observer.hero_completed(screen, hero))

    def test_class_icon_sources_are_in_release_but_report_fixture_is_not(self):
        images = set(used_images(ROOT))
        for role in self.observer.config['classes'].values():
            marker = self.observer.config['markers'][role['completed_icon']]
            self.assertIn('images/chaos/hero_selection/' + marker['file'], images)
        self.assertNotIn('images/chaos/hero_selection/raw/knight_local_recruited.png', images)


if __name__ == '__main__':
    unittest.main()
