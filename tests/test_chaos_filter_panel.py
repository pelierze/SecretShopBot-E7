import unittest
from pathlib import Path

from build_support.release_assets import used_images
from src.chaos.bot import PartyRecruitmentBot
from src.chaos.observer import RecruitmentObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/hero_selection/raw'


class FilterPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = RecruitmentObserver(ROOT)

    def frame(self, filename):
        return read_image(str(RAW / filename))

    def bot(self, hero_name):
        bot = object.__new__(PartyRecruitmentBot)
        bot.observer = self.observer
        bot.active_hero = next(hero for hero in self.observer.config['heroes'].values()
                               if hero['name'] == hero_name)
        return bot

    def test_reported_and_local_menus_reach_correct_element(self):
        for filename, hero_name, element in (
                ('knight_issue15_filter_open.png', '모험가 라스', 'fire_1'),
                ('knight_local_filter_open_live.png', '그림자 로제', 'dark_1')):
            with self.subTest(filename=filename):
                frame = self.frame(filename)
                bot = self.bot(hero_name)
                self.assertEqual(self.observer.find(frame, 'filter_panel'), (433, 87, 30, 18))
                self.assertIsNone(bot._filter_button(frame))
                self.assertEqual(bot._element_state(frame),
                                 ('unselected', *self.observer.find(frame, element)))

    def test_legacy_menu_uses_existing_template_fallback(self):
        for filename in ('knight_filter_menu.png', 'knight_dark_filter_selected_live.png'):
            with self.subTest(filename=filename):
                frame = self.frame(filename)
                self.assertIsNone(self.observer.find(frame, 'filter_element_label'))
                self.assertIsNotNone(self.observer.find(frame, 'filter_panel'))
                self.assertIsNotNone(self.bot('그림자 로제')._element_state(frame))

    def test_closed_menus_are_not_mistaken_for_open_menus(self):
        filenames = [p.name for p in RAW.glob('*full*.png')]
        filenames += ['knight_issue14_live.png', 'knight_dark_filter.png']
        for filename in filenames:
            with self.subTest(filename=filename):
                self.assertIsNone(self.observer.find(self.frame(filename), 'filter_panel'))

    def test_element_icon_without_either_menu_label_does_not_authorize_input(self):
        frame = self.frame('knight_local_filter_open_live.png')
        frame[75:125, 415:505] = 0
        frame[65:130, 65:340] = 0
        self.assertIsNotNone(self.observer.find(frame, 'dark_1'))
        self.assertIsNone(self.observer.find(frame, 'filter_panel'))
        self.assertIsNone(self.bot('그림자 로제')._element_state(frame))

    def test_correct_role_is_still_required_for_element_input(self):
        frame = self.frame('knight_issue15_filter_open.png')
        hero = next(h for h in self.observer.heroes if h['class'] == 'warrior')
        bot = object.__new__(PartyRecruitmentBot)
        bot.observer = self.observer
        bot.active_hero = hero
        self.assertIsNone(bot._element_state(frame))

    def test_label_is_packaged_but_failure_captures_are_not(self):
        assets = set(used_images(ROOT))
        self.assertIn('images/chaos/hero_selection/raw/filter_element_label.png', assets)
        for filename in ('knight_issue15_filter_open.png', 'knight_local_filter_open_live.png'):
            self.assertNotIn('images/chaos/hero_selection/raw/' + filename, assets)


if __name__ == '__main__':
    unittest.main()
