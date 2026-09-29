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
        for text in ('영웅 이탈', '영웅 랭크 1단계 상승 생명력 30% 감소', '무언가 좋은 일이 발생한다', '전리품 1개 소모 모든 영웅 생명력 100% 회복'):
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
                           ('event_abandoned_pack_live.png',2),('event_two_paths_live.png',2)]:
            frame = self.screen(name)
            cards = self.observer.event_cards(frame)
            self.assertEqual(len(cards),count)
            self.assertEqual(len(self.observer.available_event_cards(frame,cards)),count)
        self.assertEqual(self.observer.event_cards(self.screen('boss_map_live.png')),[])

    def test_abandoned_pack_prefers_experience_without_party_damage(self):
        frame=self.screen('event_abandoned_pack_live.png')
        self.assertEqual(self.observer.known_event(frame),'abandoned_pack')
        self.assertEqual(self.observer.event_choice(frame),(648,556,362,131))

    def test_registered_events_follow_safe_priority(self):
        cases = [
            ('event_prayer_stone_live.png', 'prayer_stone', (648, 556, 362, 131)),
            ('event_ancient_mural_live.png', 'ancient_mural', (838, 556, 362, 131)),
            ('event_broken_trap_live.png', 'broken_trap', (268, 556, 362, 131)),
            ('event_broken_mask_live.png', 'broken_mask', (838, 556, 362, 131)),
            ('event_two_paths_live.png', 'two_paths', (268, 556, 362, 131)),
        ]
        for file, expected_id, expected_choice in cases:
            with self.subTest(file=file):
                frame = self.screen(file)
                self.assertEqual(self.observer.known_event(frame), expected_id)
                self.assertEqual(self.observer.event_choice(frame), expected_choice)

    def test_library_outcome_with_retained_marker_continues_once(self):
        observer = NodeObserver(ROOT)
        observer.config['poll_seconds'] = 0
        choices = self.screen('event_library_book_live.png')
        result = self.screen('event_library_book_result_live.png')
        self.assertEqual(observer.known_event(result), 'library_book')
        self.assertEqual(observer.event_cards(result), [])
        self.assertEqual(observer.classify(result), 'unknown_event_result')
        self.assertEqual(observer.classify(choices), 'event')
        self.assertEqual(observer.event_choice(choices), (268,556,362,131))
        # Exercise saved choice -> retained heading/result -> next choices, also
        # in random mode: the first selection must still use the saved rule.
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, observer, event_mode='random')
            bot.event_context = True
            frames = [choices, result, self.screen('event_stairs_live.png')]
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                current[0] += 1
            bot._tap = tap
            self.assertEqual(bot._event(), 'unknown_event_result')
            self.assertEqual(bot._event_result(), 'event')
            self.assertEqual(taps, [(268,556,362,131), tuple(observer.config['event_advance_bounds'])])

    def test_retained_marker_without_advance_does_not_authorize_result(self):
        frame = self.screen('event_library_book_result_live.png').copy()
        frame[680:720] = 0
        self.assertEqual(self.observer.classify(frame), 'event')

    def test_known_event_failure_report_requires_opt_in(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, save_unknown_events=enabled)
                bot.event_context = True
                bot.pending_event_id = 'library_book'
                bot.last_screen = self.screen('event_library_book_live.png')
                bot._record('failed')
                self.assertEqual(bool(list(Path(tmp).rglob('*.png'))), enabled)

    def test_choice_wait_routes_common_reward_screens_without_input(self):
        observer = NodeObserver(ROOT)
        observer.config['poll_seconds'] = 0
        for filename, state in (
            ('event_rank_reward_live.png', 'rank_reward'),
            ('event_recruit_reward_live.png', 'recruit_reward'),
            ('loot_cards_live.png', 'loot'),
        ):
            for handler in ('_event', '_unknown_event'):
                with self.subTest(screen=filename, handler=handler), tempfile.TemporaryDirectory() as tmp:
                    bot = NodeProgressionBot(Mock(), ROOT, tmp, observer)
                    bot.event_context = True
                    bot.pending_event_id = 'library_book'
                    bot._capture = Mock(return_value=self.screen(filename))
                    bot._tap = Mock()
                    self.assertEqual(getattr(bot, handler)(), state)
                    bot._tap.assert_not_called()

    def test_unknown_result_handler_ignores_stale_registered_identity(self):
        observer = NodeObserver(ROOT)
        observer.config['poll_seconds'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, observer)
            bot.event_context = True
            bot.pending_event_id = 'library_book'
            bot._capture = Mock(return_value=self.screen('event_library_book_result_live.png'))
            bot._event_result = Mock(return_value='loot')
            bot._event = Mock()
            self.assertEqual(bot._unknown_event(), 'loot')
            bot._event_result.assert_called_once()
            bot._event.assert_not_called()

    def test_loot_consume_popup_classified_and_choices_detected(self):
        frame = self.screen('event_loot_consume_live.png')
        self.assertEqual(self.observer.classify(frame), 'event_loot_consume')
        choices = self.observer.loot_consume_choices(frame)
        self.assertEqual(len(choices), 3)
        self.assertEqual(choices[0], (704, 192))

    def test_handle_loot_consume_taps_item_and_confirm(self):
        frame = self.screen('event_loot_consume_live.png')
        result_frame = self.screen('event_abandoned_pack_result_live.png')
        index = [0]
        adb = Mock(capture_frame=lambda: frame if index[0] < 2 else result_frame)
        def tap(*args, **kwargs):
            index[0] += 1
            return True
        adb.tap.side_effect = tap
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer, 'loot_consume_selected', side_effect=lambda *args: index[0] == 1):
            bot = NodeProgressionBot(adb, ROOT, tmp, self.observer)
            state = bot._handle_loot_consume()
            self.assertEqual(state, 'event_result')
            self.assertEqual(adb.tap.call_args_list, [unittest.mock.call(704, 192, delay=0), unittest.mock.call(640, 673, delay=0)])

    def test_recruit_reward_classified_for_skip(self):
        frame = self.screen('event_recruit_reward_live.png')
        self.assertEqual(self.observer.classify(frame), 'recruit_reward')
        self.assertIsNotNone(self.observer.find(frame, 'recruit_continue'))

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
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None), patch.object(self.observer,'known_event_candidates',return_value=[]):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,save_unknown_events=True)
            bot.event_context=True
            bot.last_screen=self.screen()
            bot._record('failed')
            self.assertTrue(list(Path(tmp).rglob('*choices.png')))

    def test_unknown_geometry_requires_event_entry_context(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None), patch.object(self.observer,'known_event_candidates',return_value=[]):
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer)
            self.assertIsNone(bot._classify(self.screen()))
            bot.event_context=True
            self.assertEqual(bot._classify(self.screen()),'unknown_event')

    def test_random_does_not_use_ocr_and_waits_for_changed_screen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None), patch.object(self.observer,'known_event_candidates',return_value=[]):
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
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.observer,'classify',return_value=None), patch.object(self.observer,'known_event_candidates',return_value=[]):
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

    def test_warning_cancel_returns_to_common_policy_without_random_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, event_mode='random')
            bot._capture = Mock(return_value=self.screen())
            bot._classify = Mock(return_value='event_warning')
            bot._wait = Mock(return_value=(500,430,100,60))
            bot._state = Mock(return_value='event')
            bot._tap = Mock()
            with patch.object(self.observer, 'find', return_value=(500,430,100,60)), patch('src.chaos.exploration.random.choice') as random_choice:
                self.assertEqual(bot._handle_event_confirm((78,556,362,131)), 'event')
                random_choice.assert_not_called()
            bot._tap.assert_called_once_with((500,430,100,60))
            self.assertIn((78,556,362,131), bot.rejected_event_choices)

    def test_unknown_confirm_without_cancel_is_not_accepted(self):
        from src.chaos.bot import RecognitionTimeout
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            bot._wait = Mock(side_effect=RecognitionTimeout('확인창 의미 미확인'))
            bot._tap = Mock()
            with self.assertRaises(RecognitionTimeout): bot._handle_event_confirm()
            bot._tap.assert_not_called()

    def test_wall_torch_known_event_chooses_exp_card(self):
        observer = NodeObserver(ROOT)
        torch_screen = read_image(str(ROOT / 'images/chaos/node_progression/raw/event_wall_torch_live.png'))
        self.assertEqual(observer.known_event(torch_screen), 'wall_torch')
        self.assertEqual(observer.event_choice(torch_screen), (648, 556, 362, 131))

        res_screen = read_image(str(ROOT / 'images/chaos/node_progression/raw/event_wall_torch_result_live.png'))
        self.assertEqual(observer.event_result_marker(res_screen), 'event_wall_torch_result')
        self.assertEqual(observer.classify(res_screen), 'event_result')


if __name__ == '__main__':
    unittest.main()
