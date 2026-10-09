import unittest
from pathlib import Path

import numpy as np

from build_support.release_assets import used_images
from src.chaos.bot import PartyRecruitmentBot
from src.chaos.observer import RecruitmentObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/hero_selection/raw'


class RoleIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = RecruitmentObserver(ROOT)

    def test_issue14_reaches_filter_button_without_title_color_check(self):
        frame = read_image(str(RAW / 'knight_issue14_live.png'))
        bot = object.__new__(PartyRecruitmentBot)
        bot.observer = self.observer
        for hero_id, hero in self.observer.config['heroes'].items():
            if hero['class'] != 'knight':
                continue
            with self.subTest(hero_id=hero_id):
                bot.active_hero = hero
                self.assertEqual(bot._filter_button(frame), self.observer.find(frame, 'filter'))
                self.assertIsNotNone(bot._filter_button(frame))

    def test_role_icons_distinguish_all_classes_before_and_after_selection(self):
        cases = {'knight': ['knight_full.png', 'knight_ras_full.png', 'knight_Arowell_full_1.png',
                            'knight_Arowell_full_2.png', 'knight_hero_selected_menu.png', 'knight_issue14_live.png'],
                 'warrior': ['warrier_wukong_full.png', 'warrier_wukong_full_selected.png'],
                 'soul_weaver': ['soul_weaver_destina_full.png', 'soul_weaver_destina_full_selected.png',
                                 'soul_weaver_light_full.png', 'soul_weaver_Lisette_selected.png'],
                 'thief': ['thief_jenua_full.png', 'thief_jenua_full_selected.png', 'thief_light_full.png',
                           'thief_dark_full.png', 'thief_Savior_Adin_selected.png',
                           'thief_Rhianna and Luciella_selected.png']}
        for expected, filenames in cases.items():
            for filename in filenames:
                frame = read_image(str(RAW / filename))
                with self.subTest(filename=filename):
                    for hero in self.observer.heroes:
                        matched = self.observer.header(frame, hero)
                        self.assertEqual(matched is not None, hero['class'] == expected)

    def test_repeated_icons_are_presence_evidence_and_ignore_title_region(self):
        frame = read_image(str(RAW / 'knight_issue14_live.png'))
        frame[0:65, 55:210] = 0
        self.assertIsNotNone(self.observer.find(frame, 'knight_header'))

    def test_filter_without_role_icon_never_authorizes_input(self):
        frame = read_image(str(RAW / 'knight_issue14_live.png'))
        frame[80:595, 345:1280] = 0
        bot = object.__new__(PartyRecruitmentBot)
        bot.observer = self.observer
        bot.active_hero = self.observer.heroes[0]
        self.assertIsNotNone(self.observer.find(frame, 'filter'))
        self.assertIsNone(bot._filter_button(frame))

    def test_no_icons_in_blank_or_recruitment_card_screen(self):
        for frame in (np.zeros((720, 1280, 3), np.uint8),
                      read_image(str(RAW / 'Screenshot_2026.09.24_10.44.15.754.png'))):
            for hero in self.observer.heroes:
                self.assertIsNone(self.observer.header(frame, hero))

    def test_packaging_includes_icons_and_excludes_reported_capture(self):
        assets = set(used_images(ROOT))
        for role in ('knight', 'warrior', 'soul_weaver', 'thief'):
            self.assertIn(f'images/chaos/hero_selection/templates/classes/{role}_list_icon.png', assets)
        self.assertNotIn('images/chaos/hero_selection/raw/knight_issue14_live.png', assets)


if __name__ == '__main__':
    unittest.main()
