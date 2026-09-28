import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.chaos.exploration import NodeProgressionBot, ExplorationBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'images/chaos/node_progression/raw'


class ClearRepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)
        cls.observer.config['poll_seconds'] = 0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def image(self, name):
        return read_image(str(RAW/name))

    def test_final_boss_direct_summary_exits_battle_and_finishes(self):
        bot = NodeProgressionBot(Mock(),ROOT,self.tmp.name,self.observer)
        frames = [self.image('expedition_clear_summary_live.png'), self.image('entry_after_defeat_live.png')]
        current = [0]
        bot._capture = lambda: frames[current[0]]
        bot._tap = lambda bounds: current.__setitem__(0,1)
        bot._battle()
        self.assertEqual(bot.stats['outcome'],'victory')
        self.assertEqual(bot.run()['status'],'round_cleared')
        self.assertEqual(current[0],1)

    def test_resume_success_summary_without_previous_battle_memory(self):
        bot = NodeProgressionBot(Mock(),ROOT,self.tmp.name,self.observer)
        frames = [self.image('expedition_clear_summary_live.png'), self.image('entry_after_defeat_live.png')]
        current = [0]
        bot._capture = lambda: frames[current[0]]
        bot._tap = lambda bounds: current.__setitem__(0,1)
        self.assertEqual(bot.run()['status'],'round_cleared')

    def test_defeat_summary_is_not_clear_marker(self):
        self.assertEqual(self.observer.summary_boss_count(self.image('expedition_summary_live.png')), 2)

    def test_clear_count_does_not_depend_on_animated_background(self):
        screen = self.image('expedition_clear_summary_live.png').copy()
        screen[214:236,46:291] = 0
        self.assertEqual(self.observer.summary_boss_count(screen), 3)

    def test_uncertain_count_keeps_summary_open(self):
        from src.chaos.bot import RecognitionTimeout
        bot = NodeProgressionBot(Mock(),ROOT,self.tmp.name,self.observer)
        bot._capture = Mock(return_value=self.image('expedition_clear_summary_live.png'))
        bot._tap = Mock()
        def wait(phase, predicate):
            self.assertIsNone(predicate(bot._capture()))
            raise RecognitionTimeout('횟수 미확인')
        bot._wait = wait
        with patch.object(self.observer, 'summary_boss_count', return_value=None):
            with self.assertRaises(RecognitionTimeout): bot._finish_results()
        bot._tap.assert_not_called()

    def test_summary_count_requires_exact_high_confidence_digit(self):
        frame = self.image('expedition_clear_summary_live.png')
        for text, confidence in [('13', .99), ('3pt', .99), ('3', .8), ('', .99)]:
            with self.subTest(text=text, confidence=confidence), patch.object(
                self.observer, 'ocr', Mock(return_value=([[text, confidence]], None))
            ):
                self.assertIsNone(self.observer.summary_boss_count(frame))

    def test_defeat_memory_overrides_three_boss_count(self):
        bot = NodeProgressionBot(Mock(),ROOT,self.tmp.name,self.observer)
        bot.stats['outcome'] = 'defeat'
        bot._capture = Mock(return_value=self.image('expedition_clear_summary_live.png'))
        bot._guarded_tap = Mock()
        bot._state = Mock(return_value='exploration_entry')
        bot._finish_results()
        self.assertEqual(bot.stats['status'], 'round_failed')

    def test_real_summary_to_entry_counts_and_restarts_until_target(self):
        bot = ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2)
        attempts = []
        def run_round():
            attempts.append(bot.attempt)
            nodes = bot.nodes
            bot.active = nodes
            nodes.observer = self.observer
            frames = [self.image('expedition_clear_summary_live.png'), self.image('entry_after_defeat_live.png')]
            current = [0]
            nodes._capture = lambda: frames[current[0]]
            nodes._tap = lambda bounds: current.__setitem__(0,1)
            return nodes.run()
        bot._run_stages = run_round
        result = bot.run()
        self.assertEqual(attempts, [1,2])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['cleared_rounds'], 2)

    def test_two_clears_start_second_round_and_keep_options_and_stop(self):
        bot = ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2,event_mode='random',rank_priority=['jenua','wukong'])
        stop = bot.nodes.stop_event
        seen = []
        def round_finished():
            seen.append((bot.attempt,bot.cleared_rounds,bot.nodes))
            return {'status':'round_cleared','reason':'초기 화면 복귀'}
        bot._run_stages = round_finished
        result = bot.run()
        self.assertEqual([(a,c) for a,c,_ in seen],[(1,0),(2,1)])
        self.assertIsNot(seen[0][2],seen[1][2])
        self.assertIs(seen[1][2].stop_event,stop)
        self.assertEqual(seen[1][2].event_mode,'random')
        self.assertEqual(seen[1][2].rank_priority,['jenua','wukong'])
        self.assertEqual(result['cleared_rounds'],2)
        self.assertEqual(result['reason'],'목표 완주 2회 달성')

    def test_node_test_limit_does_not_count_as_clear(self):
        bot = ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2,max_nodes=1)
        bot._run_stages = Mock(return_value={'status':'completed','reason':'지정한 노드 검증 완료'})
        result = bot.run()
        self.assertEqual(result['cleared_rounds'],0)
        bot._run_stages.assert_called_once()

    def test_clear_then_defeat_then_clear_counts_only_two_successes(self):
        bot = ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2,save_unknown_events=True)
        statuses = iter(['round_cleared','round_failed','round_cleared'])
        seen=[]
        stop=bot.nodes.stop_event
        def run_round():
            seen.append((bot.attempt,bot.cleared_rounds,bot.failed_rounds))
            self.assertIs(bot.nodes.stop_event,stop)
            self.assertTrue(bot.nodes.save_unknown_events)
            return {'status':next(statuses)}
        bot._run_stages=run_round
        result=bot.run()
        self.assertEqual(seen,[(1,0,0),(2,1,0),(3,1,1)])
        self.assertEqual(result['cleared_rounds'],2)
        self.assertEqual(result['failed_rounds'],1)

    def test_retry_disabled_stops_after_defeat_without_losing_first_clear(self):
        bot=ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2,repeat_on_failure=False)
        bot._run_stages=Mock(side_effect=[{'status':'round_cleared'},{'status':'round_failed'}])
        result=bot.run()
        self.assertEqual(result['status'],'stopped')
        self.assertEqual((result['cleared_rounds'],result['failed_rounds']),(1,1))
        self.assertEqual(bot._run_stages.call_count,2)

    def test_stop_after_first_clear_does_not_start_second_round(self):
        bot=ExplorationBot(Mock(),ROOT,self.tmp.name,target_clears=2)
        def first_clear():
            bot.nodes.stop_event.set()
            return {'status':'round_cleared'}
        bot._run_stages=Mock(side_effect=first_clear)
        result=bot.run()
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['cleared_rounds'],1)
        bot._run_stages.assert_called_once()

    def test_old_battle_victory_does_not_turn_defeat_summary_into_clear(self):
        bot=NodeProgressionBot(Mock(),ROOT,self.tmp.name,self.observer)
        bot.stats['outcome']='victory'
        frames=[self.image('expedition_summary_live.png'),self.image('entry_after_defeat_live.png')]
        current=[0]
        bot._capture=lambda:frames[current[0]]
        bot._tap=lambda bounds:current.__setitem__(0,1)
        self.assertEqual(bot.run()['status'],'stopped')
