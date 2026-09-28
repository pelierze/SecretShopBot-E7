import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from src.chaos.bot import KnightRecruitmentBot, RecognitionTimeout, _Stopped
from src.chaos.errors import RecognitionPending
from src.chaos.exploration import NodeProgressionBot, EVENT_FOLLOWUPS
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'images/chaos/node_progression/raw'


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = NodeProgressionBot(Mock(), ROOT, self.tmp.name, self.observer)
        self.bot.stop_event = Mock()
        self.bot.stop_event.is_set.return_value = False
        self.bot.stop_event.wait.return_value = False

    def image(self, name):
        return read_image(str(RAW/name))

    def test_timeout_retries_without_input(self):
        with patch.object(KnightRecruitmentBot, '_wait', side_effect=[RecognitionTimeout('a'), RecognitionTimeout('b'), ('map',)]) as wait:
            self.assertEqual(self.bot._state('test', {'map'}), 'map')
            self.assertEqual(wait.call_count, 3)
        self.bot.adb.tap.assert_not_called()

    def test_timeout_limit_and_policy_errors(self):
        with patch.object(KnightRecruitmentBot, '_wait', side_effect=RecognitionTimeout('a')) as wait:
            with self.assertRaises(RecognitionTimeout): self.bot._wait('test', Mock())
            self.assertEqual(wait.call_count, 3)
        with patch.object(KnightRecruitmentBot, '_wait', side_effect=RuntimeError('금지')) as wait:
            with self.assertRaisesRegex(RuntimeError, '금지'): self.bot._wait('test', Mock())
            self.assertEqual(wait.call_count, 1)

    def test_stop_during_retry(self):
        self.bot.stop_event.wait.return_value = True
        with patch.object(KnightRecruitmentBot, '_wait', side_effect=RecognitionTimeout('a')):
            with self.assertRaises(_Stopped): self.bot._wait('test', Mock())

    def test_partial_detection_is_reobserved_until_two_stable_frames(self):
        self.bot._capture = Mock()
        predicate = Mock(side_effect=[RecognitionPending('카드 배치'), ('ready',), ('ready',)])
        self.assertEqual(self.bot._wait('test', predicate), ('ready',))
        self.assertEqual(predicate.call_count, 3)
        self.bot.adb.tap.assert_not_called()

    def test_transient_capture_failure(self):
        frame = self.image('event_rank_reward_live.png')
        self.bot.adb.capture_frame.side_effect = [None, None, frame]
        self.assertIs(self.bot._capture(), frame)
        self.bot.adb.tap.assert_not_called()

    def test_rank_reward_from_failure_log_is_recognized(self):
        frame = self.image('event_rank_reward_live.png')
        self.assertEqual(self.observer.classify(frame), 'rank_reward')
        self.assertIsNotNone(self.observer.find(frame, 'event_rank_reward_button'))
        self.assertIn('rank_reward', EVENT_FOLLOWUPS)

    def test_rank_reward_chain_returns_to_event(self):
        self.bot._guarded_tap = Mock()
        self.bot._state = Mock(side_effect=['rank_menu', 'rank_reward', 'event_result'])
        self.bot._rankup = Mock()
        self.assertEqual(self.bot._event_rank_reward(), 'event_result')
        self.bot._rankup.assert_called_once()
        self.assertEqual(self.bot._guarded_tap.call_count, 2)

    def test_event_battle_can_finish_at_rank_reward(self):
        self.bot._capture = Mock(return_value=self.image('event_rank_reward_live.png'))
        self.bot._battle()
        self.bot.adb.tap.assert_not_called()
        self.assertTrue(self.bot.auto_verified)

    def test_victory_routes_rank_reward_without_counting_event_twice(self):
        self.bot.event_context = True
        self.bot._capture = Mock(return_value=self.image('event_rank_reward_live.png'))
        self.bot._guarded_tap = Mock()
        self.bot._state = Mock(return_value='rank_reward')
        with patch.object(self.observer, 'find', return_value=None):
            self.bot._victory()
        self.assertIn('rank_reward', self.bot._state.call_args.args[1])
        self.assertEqual(self.bot.stats['nodes'], 0)

    def test_registered_choice_survives_hidden_heading(self):
        frame = self.image('event_bone_throne_live.png')
        frame[450:525,260:1015] = 0
        self.assertEqual(self.observer.known_event(frame), 'bone_throne')
        self.assertEqual(self.observer.event_choice(frame), (838,556,362,131))

    def test_registered_identity_does_not_fall_back_on_transient_loss(self):
        self.bot.pending_event_id = 'bone_throne'
        self.bot._capture = Mock(return_value=self.image('boss_map_live.png'))
        self.bot._unknown_event = Mock()
        self.bot._wait = Mock(side_effect=RecognitionTimeout('대기'))
        with patch('src.chaos.exploration.random.choice') as random_choice:
            with self.assertRaises(RecognitionTimeout): self.bot._event()
            random_choice.assert_not_called()
        self.bot._unknown_event.assert_not_called()

    def test_verification_does_not_accept_a_loading_frame_or_retap(self):
        frame = self.image('event_rank_reward_live.png')
        self.bot._capture = Mock(return_value=frame)
        self.bot._classify = Mock(side_effect=['rank_reward', None, 'map'])
        self.bot._tap = Mock()
        def wait(phase, predicate):
            self.assertIsNone(predicate(frame))
            return predicate(frame)
        self.bot._wait = wait
        self.assertEqual(self.bot._tap_with_verify((1,2,3,4),'test',lambda a,b:(True,'done')), 'done')
        self.bot._tap.assert_called_once()

    def test_same_coordinates_new_choices_are_a_transition(self):
        self.bot._capture = Mock(return_value=self.image('event_bone_throne_live.png'))
        self.bot._classify = Mock(return_value='unknown_event')
        self.bot._event_signature = Mock(return_value='new-page')
        self.bot._last_event_choice_bounds = (838,556,362,131)
        self.bot._wait = lambda phase,predicate: predicate(self.bot._capture())
        self.bot._tap = Mock()
        self.assertEqual(self.bot._event_transition('old-page'), 'unknown_event')
        self.bot._tap.assert_not_called()

    def test_result_routes_to_loot_hero_rank_or_more_choices(self):
        frame = self.image('event_abandoned_pack_result_live.png')
        for state in ('loot', 'recruit_reward', 'rank_reward', 'rank_menu', 'unknown_event'):
            with self.subTest(state=state):
                self.bot._capture = Mock(return_value=frame)
                current = ['event_result']
                self.bot._classify = lambda screen: current[0]
                self.bot._wait = lambda phase,predicate: predicate(frame)
                self.bot._tap = lambda bounds: current.__setitem__(0, state)
                self.assertEqual(self.bot._event_result(), state)
