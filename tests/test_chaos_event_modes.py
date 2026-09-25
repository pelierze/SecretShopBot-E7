import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from src.chaos.event_policy import interpret_effect, choose_read_choice, KoreanEventReader
from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class EventPolicyTest(unittest.TestCase):
    def test_complete_effects_only_and_harm_excluded(self):
        self.assertEqual(interpret_effect('', '차원의 파편 100 소모 영웅 랭크 1단계 상승'), ('rank_up', 0, 100))
        self.assertEqual(interpret_effect('', '전투 후 차원의 파편 100 획득'), ('battle_reward', 1, 0))
        self.assertEqual(interpret_effect('', '40% 확률로 무작위 전리품 1개 획득'), ('random_loot', 4, 0))
        for text in ('영웅 이탈', '영웅 랭크 1단계 상승 생명력 30% 감소', '무언가 좋은 일이 발생한다'):
            self.assertIsNone(interpret_effect('', text))

    def test_unaffordable_rank_falls_back_to_random_reward(self):
        rows = [dict(bounds=(0,0,10,10), rule=('rank_up',0,100)),
                dict(bounds=(20,0,10,10), rule=('random_loot',4,0))]
        self.assertIs(choose_read_choice(rows,99), rows[1])
        self.assertIs(choose_read_choice(rows,100), rows[0])
        self.assertIs(choose_read_choice(rows), rows[1])

    def test_low_confidence_does_not_authorize_effect(self):
        engine = Mock(return_value=([([[0,70],[100,70],[100,90],[0,90]],'영웅 랭크 1단계 상승',.89)],None))
        reader = KoreanEventReader(ROOT,engine)
        self.assertIsNone(reader.choices(np.zeros((720,1280,3),np.uint8),[(78,556,362,131)])[0]['rule'])


class EventModesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def screen(self, name='event_magic_circle_live.png'):
        return read_image(str(RAW/name))

    def test_real_two_and_three_choice_geometry(self):
        for name,count in [('event_magic_circle_live.png',3),('event_stairs_live.png',2),
                           ('event_abandoned_pack_live.png',2)]:
            frame = self.screen(name)
            cards = self.observer.event_cards(frame)
            self.assertEqual(len(cards),count)
            self.assertEqual(len(self.observer.available_event_cards(frame,cards)),count)
        self.assertEqual(self.observer.event_cards(self.screen('boss_map_live.png')),[])

    def test_abandoned_pack_prefers_experience_without_party_damage(self):
        frame=self.screen('event_abandoned_pack_live.png')
        self.assertEqual(self.observer.known_event(frame),'abandoned_pack')
        self.assertEqual(self.observer.event_choice(frame),(648,556,362,131))

    def test_dim_and_forbidden_candidates_excluded(self):
        frame = self.screen()
        cards = self.observer.event_cards(frame)
        x,y,w,h=cards[1]
        frame[y+22:y+h-12,x+15:x+w-15]=0
        with patch.object(self.observer,'forbidden',return_value=[('ban',(90,600,10,10))]):
            self.assertEqual(self.observer.available_event_cards(frame,cards),[cards[2]])

    def test_default_capture_and_failure_do_not_save_event_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=NodeProgressionBot(Mock(capture_frame=Mock(return_value=self.screen())),ROOT,tmp,self.observer)
            bot._capture()
            bot._start_report(bot.last_screen,{})
            bot._record('failed')
            self.assertEqual(list(Path(tmp).rglob('*.png')),[])
            self.assertEqual(list(Path(tmp).rglob('*.json')),[])

    def test_opt_in_report_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,save_unknown_events=True)
            bot._start_report(self.screen(),{'mode':'ocr'})
            for _ in range(20): bot._report('result',self.screen())
            self.assertEqual(len(list(Path(tmp).rglob('*.png'))),12)
            self.assertEqual(len(list(Path(tmp).rglob('*.json'))),12)

    def test_report_preserves_unrecognized_event_entry_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,save_unknown_events=True)
            bot.event_context=True
            bot.last_screen=self.screen()
            bot._record('failed')
            self.assertTrue(list(Path(tmp).rglob('*choices.png')))

    def test_unknown_geometry_requires_event_entry_context(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer)
            self.assertIsNone(bot._classify(self.screen()))
            bot.event_context=True
            self.assertEqual(bot._classify(self.screen()),'unknown_event')

    def test_random_does_not_use_ocr_and_waits_for_changed_screen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,event_mode='random')
            bot.event_context=True
            bot._capture=Mock(return_value=self.screen())
            bot._wait=lambda phase,predicate: predicate(bot._capture())
            bot._tap=Mock()
            bot._event_transition=Mock(return_value='map')
            bot.event_reader=Mock()
            bot._unknown_event()
            bot._tap.assert_called_once()
            bot.event_reader.choices.assert_not_called()
            bot._event_transition.assert_called_once_with(bot._event_signature(self.screen()))

    def test_registered_event_bypasses_random_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,event_mode='random')
            bot._capture=Mock(return_value=self.screen())
            bot._wait=lambda phase,predicate: predicate(bot._capture())
            bot._tap=Mock()
            bot._event_transition=Mock(return_value='map')
            bot._unknown_event=Mock()
            bot._event()
            bot._tap.assert_called_once_with((78,556,362,131))
            bot._unknown_event.assert_not_called()

    def test_screen_changed_during_second_ocr_blocks_click(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer)
            bot.event_context=True
            original=self.screen()
            changed=original.copy()
            changed[580:640,100:300]=255
            bot._capture=Mock(side_effect=[original,original,changed])
            cards=tuple(self.observer.event_cards(original))
            bot._wait=Mock(return_value=(cards,bot._event_signature(original)))
            row=dict(bounds=cards[0],title='전투',effect='전투 후 차원의 파편 100 획득',rule=('battle_reward',1,0))
            bot.event_reader=Mock(choices=Mock(return_value=[row]))
            bot._tap=Mock()
            with self.assertRaisesRegex(RuntimeError,'재확인 중 화면 변경'):
                bot._unknown_event()
            bot._tap.assert_not_called()

    def test_unregistered_two_choice_result_returns_to_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            observer=NodeObserver(ROOT)
            observer.config['events']=[]
            observer.config['event_result_markers']=[]
            observer.config['poll_seconds']=0
            bot=NodeProgressionBot(Mock(),ROOT,tmp,observer,event_mode='random')
            bot.event_context=True
            frames=[self.screen('event_stairs_live.png'),self.screen('event_stairs_result_live.png'),self.screen('boss_map_live.png')]
            current=[0]
            bot._capture=lambda:frames[current[0]]
            bot._tap=lambda bounds:current.__setitem__(0,current[0]+1)
            bot._unknown_event()
            self.assertEqual(current[0],1)
            self.assertEqual(bot._classify(bot._capture()),'unknown_event_result')
            bot._event_result()
            self.assertEqual(current[0],2)
            self.assertEqual(bot.stats['nodes'],1)


if __name__ == '__main__':
    unittest.main()
