import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from src.chaos.event_flow import run_event_flow, EVENT_STATES
from src.chaos.bot import RecognitionTimeout
from src.chaos.node_observer import NodeObserver
from src.chaos.exploration import NodeProgressionBot
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class EventTraversalTest(unittest.TestCase):
    def test_battle_returns_to_choices_and_completes_event_once(self):
        for choice_state in ('event', 'unknown_event'):
            with self.subTest(choice_state=choice_state):
                with tempfile.TemporaryDirectory() as tmp:
                    observer = Mock()
                    observer.config = {'battle_timeout_seconds': 24,
                                       'progress_difference': 8,
                                       'initial_stall_seconds': 4,
                                       'battle_stall_seconds': 8}
                    bot = NodeProgressionBot(Mock(), ROOT, tmp, observer)
                    bot.stats['nodes'] = 4
                    bot._state = Mock(side_effect=['battle', choice_state, 'map'])
                    bot._capture = Mock(return_value=object())
                    bot._classify = Mock(side_effect=['battle', choice_state])
                    bot._event_signature = Mock(return_value='stable')
                    bot._event = Mock()
                    bot._guarded_tap = Mock()
                    observer.progress_signature.return_value = np.array([0.])
                    bot.stop_event = Mock()
                    bot.stop_event.wait.return_value = False
                    bot._check_stop = Mock()
                    clock = [0]

                    def wait(seconds):
                        clock[0] += seconds
                        return False

                    bot.stop_event.wait.side_effect = wait
                    with patch('src.chaos.exploration.time.monotonic',
                               side_effect=lambda: clock[0]):
                        self.assertEqual(run_event_flow(bot), 'map')
                    bot._event.assert_called_once_with()
                    bot._guarded_tap.assert_not_called()
                    bot.adb.tap.assert_not_called()
                    self.assertEqual(bot.stats['nodes'], 5)
                    self.assertFalse(bot.event_context)
                    self.assertEqual(clock[0], 2)

    def bot(self, states):
        bot = Mock()
        bot.stats = {'nodes': 4}
        bot.observer.config = {'event_max_steps': 100, 'event_same_page_limit': 3}
        bot.rejected_event_choices = set()
        bot._state.side_effect = list(states)
        bot._event_signature.return_value = 'stable'
        return bot

    def test_arbitrary_reward_dialogue_choice_combinations_return_once_to_map(self):
        types = ('loot','recruit_reward','rank_reward','event_loot_consume','event_loot_popup','rank_result','levelup','victory')
        for first in types:
            for second in types:
                with self.subTest(first=first, second=second):
                    steps = ['unknown_event_result', 'unknown_event_result', 'event', first,
                             'event_result', second, 'unknown_event', 'map']
                    bot = self.bot(steps)
                    self.assertEqual(run_event_flow(bot), 'map')
                    self.assertEqual(bot.stats['nodes'], 5)
                    self.assertFalse(bot.event_context)
                    self.assertEqual([call.args[0] for call in bot._dispatch_event_screen.call_args_list], steps[:-1])

    def test_same_page_loop_stops_before_another_input(self):
        bot = self.bot(['event_result'] * 10)
        with self.assertRaisesRegex(RecognitionTimeout, '동일 이벤트'):
            run_event_flow(bot)
        self.assertEqual(bot._dispatch_event_screen.call_count, 3)
        self.assertEqual(bot.stats['nodes'], 4)

    def test_different_dialogue_pages_are_not_a_loop(self):
        bot = self.bot(['event_result'] * 12 + ['map'])
        bot._event_signature.side_effect = [str(i) for i in range(12)]
        self.assertEqual(run_event_flow(bot), 'map')

    def test_failed_recognition_and_defeat_do_not_complete_node(self):
        for terminal in ('defeat', 'expedition_summary', 'exploration_entry'):
            bot = self.bot(['event', terminal])
            self.assertEqual(run_event_flow(bot), terminal)
            self.assertEqual(bot.stats['nodes'], 4)
        bot = self.bot([])
        bot._state.side_effect = RecognitionTimeout('unknown')
        with self.assertRaises(RecognitionTimeout): run_event_flow(bot)
        bot._dispatch_event_screen.assert_not_called()

    def test_skip_story_can_lead_directly_to_reward_without_confirmation(self):
        bot = object.__new__(NodeProgressionBot)
        bot.event_context = True
        bot._guarded_tap = Mock()
        bot._state = Mock(return_value='rank_reward')
        bot._wait = Mock()
        self.assertEqual(bot._story('story'), 'rank_reward')
        bot._guarded_tap.assert_called_once_with('스토리 건너뛰기', 'story', 'skip')
        bot._wait.assert_not_called()

    def test_resumed_battle_defers_reward_popup_to_common_dispatch(self):
        for reward in ('rank_result', 'event_loot_popup'):
            with self.subTest(reward=reward):
                bot = object.__new__(NodeProgressionBot)
                bot.stats = {'nodes': 0}
                bot.event_context = False
                bot.observer = Mock()
                bot.observer.find.return_value = None
                bot._capture = Mock(return_value=object())
                bot._guarded_tap = Mock()
                bot._state = Mock(return_value=reward)
                self.assertEqual(bot._victory(), reward)
                bot._guarded_tap.assert_called_once_with(
                    '계속 탐사하기', 'victory', 'continue', exiting=True)
                bot._state.assert_called_once()
                self.assertEqual(bot.stats['nodes'], 0)

    def test_rankup_accepts_battle_completion_without_popup_close(self):
        bot = object.__new__(NodeProgressionBot)
        target = ('any_hero', 2, 10, 20, 30, 40)
        button = (100, 200, 30, 40)
        bot._wait = Mock(side_effect=[target, button])
        bot._rank_target = Mock(return_value=target)
        bot._capture = Mock(return_value=object())
        bot.observer = Mock()
        bot.observer.classify.return_value = 'rank_menu'
        bot.observer.forbidden.return_value = []
        bot.observer.find.return_value = button
        bot._tap = Mock()
        bot._state = Mock(return_value='battle_rank_complete')
        bot._tap_with_verify = Mock()
        self.assertEqual(bot._rankup(), 'battle_rank_complete')
        self.assertIn('battle_rank_complete', bot._state.call_args.args[1])
        bot._tap_with_verify.assert_not_called()


class EventRewardImagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_common_reward_wins_over_retained_event_heading(self):
        for file, state in [('loot_cards_live.png','loot'),('event_rank_reward_live.png','rank_reward'),
                            ('event_recruit_reward_live.png','recruit_reward')]:
            with patch.object(self.observer, 'known_event_candidates', return_value=['old_event']):
                self.assertEqual(self.observer.classify(read_image(str(RAW/file))), state)

    def test_battle_rank_reward_is_claimed_before_continue(self):
        frame = read_image(str(RAW/'battle/victory_rank_reward_live.png'))
        self.assertEqual(self.observer.classify(frame), 'victory')
        self.assertIsNotNone(self.observer.find(frame, 'battle_rank_reward'))
        for context in (False, True):
            for following in ('victory', 'loot', 'rank_reward', 'recruit_reward',
                              'unknown_event_result', 'levelup', 'map'):
                with self.subTest(context=context, following=following):
                    with tempfile.TemporaryDirectory() as tmp:
                        bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
                        bot.event_context = context
                        bot._capture = Mock(return_value=frame)
                        bot._guarded_tap = Mock()
                        bot._rankup = Mock()
                        bot._state = Mock(side_effect=['rank_menu', following])
                        self.assertEqual(bot._victory(), following)
                        bot._rankup.assert_called_once()
                        bot._guarded_tap.assert_called_once_with(
                            '전투 보상 영웅 랭크업 열기', 'victory', 'battle_rank_reward')
                        self.assertIn(following, bot._state.call_args.args[1])
                        self.assertEqual(bot.stats['nodes'], 0)

    def test_other_battle_rewards_do_not_match_rank_reward(self):
        for name in ('battle/victory_live.png', 'battle/victory_levelup_live.png',
                     'event_rank_reward_live.png', 'event_recruit_reward_live.png'):
            self.assertIsNone(self.observer.find(read_image(str(RAW/name)), 'battle_rank_reward'))

    def test_battle_completed_rank_card_is_not_an_unused_reward(self):
        frame = read_image(str(RAW/'battle/victory_rank_complete_live.png'))
        self.assertEqual(self.observer.classify(frame), 'battle_rank_complete')
        self.assertIsNone(self.observer.find(frame, 'battle_rank_reward'))
        # Hero art and name may change; only common completion UI is used.
        frame[170:460,525:750] = 0
        frame[505:536,525:750] = 0
        self.assertEqual(self.observer.classify(frame), 'battle_rank_complete')
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            bot._capture = Mock(return_value=frame)
            bot._guarded_tap = Mock()
            bot._state = Mock(return_value='unknown_event_result')
            bot._rankup = Mock()
            self.assertEqual(bot._dispatch_event_screen('battle_rank_complete'), 'unknown_event_result')
            bot._rankup.assert_not_called()
            bot._guarded_tap.assert_called_once_with(
                '전투 랭크업 완료 후 계속 탐사', 'battle_rank_complete', 'continue', exiting=True)

    def test_consume_prefers_blocked_thumbnail_else_first_item(self):
        frame = read_image(str(RAW/'event_loot_consume_live.png'))
        items = self.observer.loot_consume_choices(frame)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], (704,192))
        with patch.object(self.observer, 'forbidden', return_value=[]):
            self.assertEqual(self.observer.loot_consume_target(frame), items[0])
        x,y = items[-1]
        with patch.object(self.observer, 'forbidden', return_value=[('ban',(x-10,y-10,20,20))]):
            self.assertEqual(self.observer.loot_consume_target(frame), items[-1])

    def test_selected_slot_requires_same_icon_and_one_of_one(self):
        frame = read_image(str(RAW/'event_loot_consume_live.png'))
        icon = frame[170:214,682:726].copy()
        with patch.object(self.observer, 'ocr', Mock(return_value=([('선택 (1/1)', .99)], None))):
            self.assertFalse(self.observer.loot_consume_selected(frame,icon))
            frame[535:579,875:919] = icon
            self.assertTrue(self.observer.loot_consume_selected(frame,icon))
        with patch.object(self.observer, 'ocr', Mock(return_value=([('선택 (0/1)', .99)], None))):
            self.assertFalse(self.observer.loot_consume_selected(frame,icon))

    def test_live_consume_slot_and_counter_without_ocr_mock(self):
        observer = NodeObserver(ROOT)
        before = read_image(str(RAW/'event_loot_consume_leaf_live.png'))
        selected = read_image(str(RAW/'event_loot_consume_leaf_selected_live.png'))
        self.assertEqual(observer.classify(before), 'event_loot_consume')
        self.assertEqual(observer.classify(selected), 'event_loot_consume')
        self.assertEqual(observer.loot_consume_target(before), (704, 192))
        icon = before[170:214,682:726].copy()
        self.assertFalse(observer.loot_consume_selected(before, icon))
        self.assertTrue(observer.loot_consume_selected(selected, icon))
        wrong_icon = before[170:214,778:822].copy()
        self.assertFalse(observer.loot_consume_selected(selected, wrong_icon))

    def test_consume_selection_failure_never_confirms(self):
        observer = NodeObserver(ROOT)
        frame = read_image(str(RAW/'event_loot_consume_live.png'))
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(),ROOT,tmp,observer)
            bot._capture = Mock(return_value=frame)
            bot._tap = Mock()
            bot._wait = Mock(side_effect=[(704,192), RecognitionTimeout('selection')])
            with patch.object(observer,'loot_consume_selected',return_value=False):
                with self.assertRaises(RecognitionTimeout): bot._handle_loot_consume()
            bot._tap.assert_called_once_with((704,192,0,0))

    def test_real_images_multipage_choice_loot_hero_rank_chain(self):
        names = ['event_mushroom_result_live.png','event_mushroom_end_live.png',
                 'event_magic_circle_live.png','loot_cards_live.png','loot_selected_live.png',
                 'event_loot_popup_live.png','event_recruit_reward_live.png',
                 'rank_result_event_live.png','event_rank_reward_live.png','map_after_rest_live.png']
        frames = [read_image(str(RAW/name)) for name in names]
        observer = NodeObserver(ROOT)
        observer.config['poll_seconds'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(),ROOT,tmp,observer,max_nodes=1,event_mode='random')
            index = [0]
            taps = []
            bot._capture = lambda: frames[index[0]]
            def tap(bounds):
                taps.append(bounds)
                index[0] += 1
            bot._tap = tap
            with patch('src.chaos.exploration.random.choice') as random_choice:
                result = bot.run()
                random_choice.assert_not_called()
            self.assertEqual(result['status'], 'completed', result)
            self.assertEqual(result['nodes'], 1)
            self.assertEqual(len(taps), len(frames)-1)


if __name__ == '__main__': unittest.main()
