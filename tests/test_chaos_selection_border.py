import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.chaos.bot import PartyRecruitmentBot
from src.chaos.observer import RecruitmentObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/hero_selection/raw'


class SelectionBorderTests(unittest.TestCase):
    def frame(self, name):
        return read_image(str(RAW / name))

    def test_every_supported_hero_uses_the_same_border_detector(self):
        cases = [('shadow_rose', 'knight_hero_selected_menu.png', None),
                 ('wukong', 'warrier_wukong_full_selected.png', 'warrier_wukong_full.png'),
                 ('destina', 'soul_weaver_destina_full_selected.png', 'soul_weaver_destina_full.png'),
                 ('lisette', 'soul_weaver_Lisette_selected.png', 'soul_weaver_light_full.png'),
                 ('savior_adin', 'thief_Savior_Adin_selected.png', 'thief_light_full.png'),
                 ('jenua', 'thief_jenua_full_selected.png', 'thief_jenua_full.png'),
                 ('rhianna_luciella', 'thief_Rhianna and Luciella_selected.png', 'thief_dark_full.png'),
                 ('ras', 'knight_ras_selected.png', 'knight_ras_full.png'),
                 ('arowell', 'knight_Arowell_selected.png', 'knight_Arowell_full_2.png')]
        for hero_id, selected, plain in cases:
            with self.subTest(hero=hero_id):
                observer = RecruitmentObserver(ROOT, [hero_id])
                marker = observer.heroes[0]['portrait']
                for name, expected in [(selected, True)] + ([(plain, False)] if plain else []):
                    screen = self.frame(name)
                    portrait = observer.find(screen, marker)
                    self.assertIsNotNone(portrait)
                    self.assertEqual(observer.hero_selected(screen, portrait), expected)

    def bot(self, hero_id):
        bot = object.__new__(PartyRecruitmentBot)
        bot.observer = RecruitmentObserver(ROOT, [hero_id])
        bot.active_hero = bot.observer.heroes[0]
        bot._tap = Mock()
        return bot

    def test_latest_report_recruits_despite_unmatched_detail_name(self):
        screen = self.frame('knight_local_gold_selected.png')
        bot = self.bot('shadow_rose')
        self.assertIsNone(bot.observer.find(screen, 'rose_selected'))
        bot._select_hero(bot._target_portrait(screen))
        self.assertIsNotNone(bot._recruit(screen))
        # The hero detail panel is no longer needed to authorize recruitment.
        screen[65:605, :325] = 0
        self.assertIsNotNone(bot._recruit(screen))

    def test_selected_duplicate_does_not_authorize_another_clicked_copy(self):
        screen = self.frame('knight_ras_selected.png')
        bot = self.bot('ras')
        bot._select_hero((499, 504, 135, 47))
        self.assertIsNone(bot._recruit(screen))
        bot._select_hero((499, 84, 135, 47))
        self.assertIsNotNone(bot._recruit(screen))

    def test_missing_edge_or_disabled_button_blocks_recruitment(self):
        screen = self.frame('knight_local_gold_selected.png')
        bot = self.bot('shadow_rose')
        bot._select_hero(bot._target_portrait(screen))
        missing_edge = screen.copy()
        missing_edge[366:388, 365:615] = 0
        self.assertIsNone(bot._recruit(missing_edge))
        screen[615:705, 930:1250] = 0
        self.assertIsNotNone(bot._selected_portrait(screen))
        self.assertIsNone(bot._recruit(screen))

    def test_border_and_button_must_remain_visible_across_frames(self):
        selected = self.frame('knight_local_gold_selected.png')
        unselected = selected.copy()
        unselected[366:388, 365:615] = 0
        bot = self.bot('shadow_rose')
        bot._select_hero(bot._target_portrait(selected))
        bot.observer.config.update(poll_seconds=0, timeout_seconds=1, stable_frames=2)
        bot.stats = {}
        bot.hero_name = bot.active_hero['name']
        bot.stop_event = threading.Event()
        bot._capture = Mock(side_effect=[selected, unselected, selected, selected])
        self.assertEqual(bot._wait_recruit_action()[0], 'active')
        self.assertEqual(bot._capture.call_count, 4)


if __name__ == '__main__':
    unittest.main()
