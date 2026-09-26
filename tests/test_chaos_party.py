import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.chaos.bot import PartyRecruitmentBot
from src.chaos.observer import RecruitmentObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]


class PartyObserverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = RecruitmentObserver(ROOT)

    def screen(self, name):
        image = read_image(str(ROOT / 'images/chaos/hero_selection/raw' / name))
        self.assertIsNotNone(image)
        return image

    def test_all_candidates_match_before_and_after_selection(self):
        for hero, raw in zip(self.observer.heroes[1:], ('warrier_wukong', 'soul_weaver_destina', 'thief_jenua')):
            with self.subTest(hero=hero['id']):
                for suffix in ('_full.png', '_full_selected.png'):
                    screen = self.screen(raw + suffix)
                    self.assertIsNotNone(self.observer.find(screen, hero['portrait']))
                    self.assertIsNotNone(self.observer.header(screen, hero))
                    for other in self.observer.heroes:
                        if other['id'] != hero['id']:
                            self.assertIsNone(self.observer.header(screen, other))
                self.assertIsNone(self.observer.find(self.screen(raw + '_full.png'), hero['selected']))
                self.assertIsNotNone(self.observer.find(self.screen(raw + '_full_selected.png'), hero['selected']))

    def test_completion_requires_all_four_names_in_their_own_slots(self):
        for count, filename in enumerate(('knight_select_finish.png', 'warrior_wukong_recruited_live.png', 'soul_weaver_destina_recruited_live.png', 'thief_jenua_recruited_live.png'), 1):
            with self.subTest(count=count):
                screen = self.screen(filename)
                found = [self.observer.hero_completed(screen, hero) for hero in self.observer.heroes]
                self.assertEqual(found, [True] * count + [False] * (4 - count))
                self.assertEqual(self.observer.completed(screen), count == 4)

    def test_each_symbol_finds_only_its_own_recruit_button(self):
        screen = self.screen('Screenshot_2026.09.24_10.44.15.754.png')
        for i, hero in enumerate(self.observer.heroes):
            self.assertEqual(self.observer.class_button(screen, hero), (112 + 280*i, 490, 216, 48))

    def test_invalid_and_duplicate_class_selection_fail_before_run(self):
        for ids in ([], ['unknown'], ['shadow_rose', 'shadow_rose']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                RecruitmentObserver(ROOT, ids)

    def test_thief_savior_adin_selection_and_matching(self):
        obs = RecruitmentObserver(ROOT, ['shadow_rose', 'wukong', 'destina', 'savior_adin'])
        thief = obs.heroes[3]
        self.assertEqual(thief['id'], 'savior_adin')
        self.assertEqual(thief['element'], 'light')
        screen_full = self.screen('thief_light_full.png')
        screen_sel = self.screen('thief_Savior_Adin_selected.png')
        self.assertIsNotNone(obs.find(screen_full, thief['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, thief['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, thief['selected']))

    def test_thief_rhianna_luciella_selection_and_matching(self):
        obs = RecruitmentObserver(ROOT, ['shadow_rose', 'wukong', 'destina', 'rhianna_luciella'])
        thief = obs.heroes[3]
        self.assertEqual(thief['id'], 'rhianna_luciella')
        self.assertEqual(thief['element'], 'dark')
        screen_full = self.screen('thief_dark_full.png')
        screen_sel = self.screen('thief_Rhianna and Luciella_selected.png')
        self.assertIsNotNone(obs.find(screen_full, thief['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, thief['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, thief['selected']))

    def test_soul_weaver_lisette_selection_and_matching(self):
        obs = RecruitmentObserver(ROOT, ['shadow_rose', 'wukong', 'lisette', 'jenua'])
        weaver = obs.heroes[2]
        self.assertEqual(weaver['id'], 'lisette')
        self.assertEqual(weaver['element'], 'light')
        self.assertEqual(weaver['class'], 'soul_weaver')
        screen_full = self.screen('soul_weaver_light_full.png')
        screen_sel = self.screen('soul_weaver_Lisette_selected.png')
        self.assertIsNotNone(obs.find(screen_full, weaver['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, weaver['portrait']))
        self.assertIsNotNone(obs.find(screen_sel, weaver['selected']))
        self.assertIsNotNone(obs.header(screen_full, weaver))
        self.assertIsNotNone(obs.header(screen_sel, weaver))


class ReplayObserver:
    config = {'timeout_seconds': .06, 'poll_seconds': 0, 'stable_frames': 2,
              'popup_dismiss_point': (640, 590), 'filter_dismiss_point': (960, 590)}

    def __init__(self):
        self.heroes = [dict(id=key, name=key, **{'class':key}, element=element,
                            portrait=key+'_portrait', selected=key+'_selected')
                       for key, element in (('knight','dark'), ('warrior','forest'), ('soul_weaver','forest'), ('thief','fire'))]
        self.theme = SimpleNamespace(observe=lambda s: SimpleNamespace(state=s.get('theme', 'unknown'), bounds=(100,140,120,145) if 'theme' in s else None))

    def find(self, screen, name):
        return screen.get(name)

    def class_button(self, screen, hero):
        return screen.get(hero['id']+'_card')

    def header(self, screen, hero):
        return screen.get(hero['id']+'_header')

    def hero_completed(self, screen, hero):
        return hero['id'] in screen.get('done', [])

    def completed(self, screen):
        return all(self.hero_completed(screen, h) for h in self.heroes)


class PartyFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.observer = ReplayObserver()
        self.adb = Mock()
        self.bot = PartyRecruitmentBot(self.adb, ROOT, self.temp.name, observer=self.observer)
        b=(100,100,40,30)
        self.frames=[{'start':b}, {'theme':'unselected'}, {'theme':'selected','confirm_theme':b}]
        done=[]
        for hero in self.observer.heroes:
            key=hero['id'];e=hero['element'];header={key+'_header':b}
            self.frames.extend([
                {key+'_card':b,'done':list(done)},
                {**header,'filter':b},
                {**header,'filter_panel':b,e+'_1':b},
                {**header,'filter_panel':b,e+'_2':b},
                {**header,key+'_portrait':b},
                {**header,key+'_portrait':b,key+'_selected':b,'recruit_active':b},
            ])
            done.append(key)
        self.frames.append({'done':done})
        self.index=0
        def tap(*args, **kwargs):
            self.index+=1
            return True
        self.adb.tap.side_effect=tap
        def capture():
            self.bot._check_stop()
            return self.frames[self.index]
        self.bot._capture=capture

    def test_four_classes_use_their_own_attributes_and_stop_before_entry(self):
        result=self.bot.run()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['recruited'],4)
        self.assertEqual(self.adb.tap.call_count,27)
        self.assertEqual(self.index,len(self.frames)-1)

    def test_resume_skips_verified_completed_knight(self):
        self.index=9
        self.assertEqual(self.bot.run()['status'],'completed')
        self.assertEqual(self.adb.tap.call_count,18)

    def test_all_completed_causes_no_input(self):
        self.index=len(self.frames)-1
        result=self.bot.run()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['recruited'],4)
        self.adb.tap.assert_not_called()

    def test_missing_warrior_stops_before_other_classes(self):
        self.frames[13].pop('warrior_portrait')
        with self.assertLogs('src.chaos.bot', level='ERROR'):
            result=self.bot.run()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['recruited'],1)
        self.assertEqual(self.adb.tap.call_count,13)

    def test_wrong_hero_in_occupied_slot_is_not_replaced(self):
        self.index=9
        self.frames[9]['done']=[]
        with self.assertLogs('src.chaos.bot', level='ERROR'):
            self.assertEqual(self.bot.run()['status'],'failed')
        self.adb.tap.assert_not_called()
