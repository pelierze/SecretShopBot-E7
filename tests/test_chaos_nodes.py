import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import cv2

from src.chaos.exploration import ExplorationBot, NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class NodeImagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def screen(self, file):
        return read_image(str(RAW / file))

    def test_reachable_nodes_exclude_completed_and_unconnected_nodes(self):
        for file, expected in [('map_first_battle_live.png',['battle']),
                               ('map_after_battle_live.png',['rest','rest','event']),
                               ('map_after_rest_live.png',['battle']),
                               ('map_after_second_battle_live.png',['rest','event']),
                               ('boss_map_live.png',['boss'])]:
            with self.subTest(file=file):
                s=self.screen(file)
                self.assertEqual(self.observer.classify(s),'map')
                self.assertEqual([v[0] for v in self.observer.candidates(s)],expected)
                self.assertEqual(self.observer.choose_node(s)[0],expected[0])

    def test_top_row_battle_is_not_lost_and_beats_elite(self):
        screen=self.screen('map_battle_elite_top_live.png')
        self.assertEqual([kind for kind,_ in self.observer.candidates(screen)], ['battle','elite'])
        self.assertEqual(self.observer.choose_node(screen), ('battle',(898,100,83,79)))

    def test_shop_recognition_survives_npc_animation(self):
        screen=self.screen('shop_animated_npc_live.png')
        self.assertIsNone(self.observer.find(screen,'shop_npc'))
        self.assertEqual(self.observer.classify(screen),'shop')
        self.assertIsNotNone(self.observer.find(screen,'shop_exit'))

    def test_overlay_priority_blocks_background_buttons(self):
        for file, state in [('battle/victory_levelup_live.png','levelup'),
                            ('rest_wukong_rankup_live.png','rank_result'),
                            ('story/Screenshot_2026.09.24_13.49.26.082.png','story_confirm'),
                            ('story/Screenshot_2026.09.24_13.49.37.999.png','story_confirm')]:
            self.assertEqual(self.observer.classify(self.screen(file)),state)

    def test_event_requires_reviewed_party_preserving_outcome(self):
        screen = self.screen('event_magic_circle_live.png')
        self.assertEqual(self.observer.classify(screen), 'event')
        self.assertEqual(self.observer.event_choice(screen), (78,556,362,131))
        with patch.dict(self.observer.config['events'][0]['choices'][0], effect='hero_removal'):
            self.assertIsNone(self.observer.event_choice(screen))
        changed = screen.copy()
        changed[582:685,128:399] = 0
        self.assertIsNone(self.observer.event_choice(changed))
        self.assertIsNone(self.observer.event_choice(np.zeros_like(screen)))

    def test_event_forbidden_image_prevents_selection(self):
        screen = self.screen('event_magic_circle_live.png')
        with patch.object(self.observer, 'forbidden', return_value=[('blocked',(100,570,100,90))]):
            with self.assertRaisesRegex(RuntimeError, '금지'):
                self.observer.event_choice(screen)

    def test_event_result_is_not_another_choice(self):
        screen = self.screen('event_magic_result_live.png')
        self.assertEqual(self.observer.classify(screen), 'event_result')
        self.assertIsNone(self.observer.event_choice(screen))

    def test_stairs_uses_no_loss_bypass(self):
        self.assertEqual(self.observer.event_choice(self.screen('event_stairs_live.png')), (646,556,363,131))
        self.assertEqual(self.observer.classify(self.screen('event_stairs_result_live.png')), 'event_result')

    def test_mushroom_prefers_rankup_and_falls_back_to_random_loot(self):
        screen = self.screen('event_mushroom_live.png')
        self.assertEqual(self.observer.event_choice(screen), (78,556,362,131))
        event = next(e for e in self.observer.config['events'] if e['id'] == 'mushroom')
        with patch.dict(event['choices'][0], effect='hero_removal'):
            self.assertEqual(self.observer.event_choice(screen), (840,556,359,131))
        disabled=screen.copy()
        disabled[584:682,112:406] = (disabled[584:682,112:406]*.4).astype(np.uint8)
        self.assertEqual(self.observer.event_choice(disabled), (840,556,359,131))
        with patch.object(self.observer,'forbidden',return_value=[('blocked',(100,570,100,90))]):
            self.assertEqual(self.observer.event_choice(screen), (840,556,359,131))
        for name in ('event_mushroom_result_live.png','event_mushroom_end_live.png'):
            self.assertEqual(self.observer.classify(self.screen(name)), 'event_result')

    def test_known_screens_and_unknown(self):
        for file, state in [('rest_menu_live.png','rest'),('rest_completed_live.png','rest'),('rest_detail_live.png','rest_detail'),
                            ('battle_detail_live.png','battle_detail'),('battle_setup_live.png','battle_setup'),
                            ('rest_rank_menu_live.png','rank_menu'),('battle/victory_live.png','victory'),
                            ('battle/auto_off_live.png','battle'),
                            ('story/Screenshot_2026.09.24_13.49.22.466.png','story')]:
            self.assertEqual(self.observer.classify(self.screen(file)),state)
        self.assertIsNone(self.observer.classify(np.zeros((720,1280,3),dtype=np.uint8)))

    def test_both_blocked_templates_and_multiple_occurrences_are_detected(self):
        s=np.zeros((720,1280,3),dtype=np.uint8)
        for (name,t),(x,y) in zip(self.observer.blocked,[(100,100),(450,100)]):
            h,w=t.shape[:2];s[y:y+h,x:x+w]=t
        t=self.observer.blocked[0][1];h,w=t.shape[:2];s[400:400+h,100:100+w]=t
        self.assertEqual(len(self.observer.forbidden(s)),3)

    def test_forbidden_is_checked_before_node_policy(self):
        s=self.screen('map_after_battle_live.png').copy()
        t=self.observer.blocked[0][1];h,w=t.shape[:2];s[450:450+h,100:100+w]=t
        with self.assertRaisesRegex(RuntimeError,'금지'):self.observer.choose_node(s)

    def test_rank_and_selected_hero(self):
        s=self.screen('rest_rank_menu_live.png')
        self.assertEqual(self.observer.rank(s,'wukong'),1)
        self.assertEqual(self.observer.rank(s,'jenua'),1)
        self.assertIsNotNone(self.observer.find(self.screen('rest_wukong_selected_live.png'),'wukong_selected'))
        self.assertEqual(self.observer.read_rank_digit(self.screen('rest_wukong_rankup_live.png')[540:568,365:384]),2)

    def test_supply_loot_and_shop_screens(self):
        for file,state in [('supply_menu_live.png','supply'),('supply_detail_live.png','supply_detail'),
                           ('elite_detail_live.png','elite_detail'),('boss_detail_live.png','boss_detail'),
                           ('loot_cards_live.png','loot'),('loot_selected_live.png','loot')]:
            self.assertEqual(self.observer.classify(self.screen(file)),state)
        shop=read_image(str(ROOT/'images/chaos/raw/Screenshot_2026.09.24_10.22.54.004.png'))
        self.assertEqual(self.observer.classify(shop),'shop')
        self.assertEqual(self.observer.selected_loot(self.screen('loot_selected_live.png')),(195,96,250,425))

    def test_loot_excludes_only_blocked_card_and_all_blocked_returns_empty(self):
        s=self.screen('loot_cards_live.png').copy()
        t=self.observer.blocked[0][1];h,w=t.shape[:2]
        s[130:130+h,210:210+w]=t
        self.assertEqual(len(self.observer.loot_choices(s)),2)
        self.assertEqual(self.observer.loot_choices(s)[0][0],515)
        for x in (530,850):s[130:130+h,x:x+w]=t
        self.assertEqual(self.observer.loot_choices(s),[])

    def test_scaled_forbidden_loot_is_excluded(self):
        s=self.screen('loot_cards_live.png').copy()
        t=cv2.resize(self.observer.blocked[1][1],None,fx=.85,fy=.85);h,w=t.shape[:2]
        s[130:130+h,530:530+w]=t
        self.assertEqual([b[0] for b in self.observer.loot_choices(s)],[195,835])


class NodeFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.observer=Mock()
        self.observer.config=dict(timeout_seconds=.01,poll_seconds=0,stable_frames=2,
                                  initial_stall_seconds=4,battle_stall_seconds=8,
                                  battle_timeout_seconds=24,progress_difference=8,
                                  supported_nodes=['rest','battle'])
        self.bot=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=self.observer)

    def test_rank_fallback_only_when_wukong_is_five(self):
        self.observer.classify.return_value='rank_menu';self.observer.forbidden.return_value=[]
        self.observer.find.return_value=(1,2,3,4)
        self.observer.rank.side_effect=[5,2]
        self.assertEqual(self.bot._rank_target(None),('jenua',2,1,2,3,4))
        self.observer.rank.side_effect=[None]
        with self.assertRaisesRegex(RuntimeError,'오공'):self.bot._rank_target(None)
        self.observer.rank.side_effect=[5,5]
        with self.assertRaisesRegex(RuntimeError,'제뉴아'):self.bot._rank_target(None)

    def test_dynamic_rank_priority_order(self):
        self.observer.classify.return_value = 'rank_menu'
        self.observer.forbidden.return_value = []
        self.observer.find.return_value = (10, 20, 30, 40)
        self.bot.rank_priority = ['jenua', 'shadow_rose']
        self.observer.rank.side_effect = [3]
        self.assertEqual(self.bot._rank_target(None), ('jenua', 3, 10, 20, 30, 40))

    def test_rank_priority_skips_maxed_heroes(self):
        self.observer.classify.return_value = 'rank_menu'
        self.observer.forbidden.return_value = []
        self.observer.find.return_value = (10, 20, 30, 40)
        self.bot.rank_priority = ['wukong', 'jenua', 'shadow_rose']
        self.observer.rank.side_effect = [5, 5, 2]
        self.assertEqual(self.bot._rank_target(None), ('shadow_rose', 2, 10, 20, 30, 40))

    def test_rank_priority_deduction_when_first_hero_is_none(self):
        self.observer.classify.return_value = 'rank_menu'
        self.observer.forbidden.return_value = []
        self.observer.find.return_value = (10, 20, 30, 40)
        self.bot.rank_priority = ['wukong', 'jenua']
        self.observer.rank.side_effect = [None, 2, 2]
        self.assertEqual(self.bot._rank_target(None), ('jenua', 2, 10, 20, 30, 40))

    def test_new_frame_change_prevents_click(self):
        self.bot._wait=Mock(return_value=(1,2,3,4));self.bot._capture=Mock(return_value=None)
        self.observer.classify.return_value='story_confirm';self.observer.forbidden.return_value=[]
        self.observer.find.return_value=(8,9,3,4)
        with self.assertRaisesRegex(RuntimeError,'변경'):self.bot._guarded_tap('test','story_confirm','story_confirm')
        self.bot.adb.tap.assert_not_called()

    def test_unsupported_node_stops_before_entering(self):
        self.bot._wait=Mock(return_value=('supply',10,20,30,40))
        self.assertFalse(self.bot._select_node())
        self.assertEqual(self.bot.stats['status'],'stopped')
        self.bot.adb.tap.assert_not_called()

    def battle_clock(self, progress=False):
        clock=[0]
        def capture():clock[0]+=2;return clock[0]
        self.bot._capture=Mock(side_effect=capture)
        self.observer.classify.side_effect=lambda s:'victory' if progress and s>=16 else 'battle'
        self.observer.progress_signature.side_effect=lambda s:np.array([s*20 if progress else 0.])
        self.observer.find.return_value=None
        self.bot._guarded_tap=Mock();self.bot._record=Mock()
        self.bot.stop_event=Mock();self.bot.stop_event.wait.return_value=False
        return clock

    def test_stall_toggles_once_then_stops_without_retry(self):
        clock=self.battle_clock()
        with patch('src.chaos.exploration.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(RuntimeError,'다시 누르지'):self.bot._battle()
        self.bot._guarded_tap.assert_called_once()

    def test_running_battle_never_toggles(self):
        clock=self.battle_clock(progress=True)
        with patch('src.chaos.exploration.time.monotonic',side_effect=lambda:clock[0]):self.bot._battle()
        self.bot._guarded_tap.assert_not_called()
        self.assertTrue(self.bot.auto_verified)

    def test_previously_verified_auto_is_not_toggled_on_stall(self):
        clock=self.battle_clock();self.bot.auto_verified=True
        with patch('src.chaos.exploration.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(RuntimeError):self.bot._battle()
        self.bot._guarded_tap.assert_not_called()

    def test_stop_before_input(self):
        self.bot.set_user_action('stop')
        self.assertEqual(self.bot.run()['status'],'stopped')
        self.bot.adb.tap.assert_not_called()

    def test_shop_only_exits_even_when_forbidden_goods_are_displayed(self):
        self.bot._guarded_tap=Mock();self.bot._state=Mock(return_value='map')
        self.bot._shop()
        self.bot._guarded_tap.assert_called_once_with('상점 구매 없이 나가기','shop','shop_exit',exiting=True)
        self.assertEqual(self.bot.stats['nodes'],1)

    def test_shop_real_screen_replay_returns_to_map_with_one_exit_input(self):
        n=NodeObserver(ROOT);n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n,max_nodes=1)
        frames=[read_image(str(ROOT/'images/chaos/raw/Screenshot_2026.09.24_10.22.54.004.png')),
                read_image(str(RAW/'map_after_rest_live.png'))]
        index=[0];taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):taps.append(bounds);index[0]+=1
        b._tap=tap
        self.assertEqual(b.run()['status'],'completed')
        self.assertEqual(taps,[(1057,646,60,27)])

    def test_defeat_closes_results_and_returns_without_recruiting_here(self):
        n=NodeObserver(ROOT);n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n)
        frames=[read_image(str(RAW/name)) for name in ['battle_defeat_live.png',
                'expedition_summary_live.png','entry_after_defeat_live.png']]
        index=[0];taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):taps.append(bounds);index[0]+=1
        b._tap=tap
        result=b.run()
        self.assertEqual(result['status'],'round_failed',result)
        self.assertEqual(result['outcome'],'defeat')
        self.assertEqual(result['nodes'],0)
        self.assertEqual(len(taps),2)

    def test_shop_confirmation_only_leaves_without_purchase(self):
        n=NodeObserver(ROOT); n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n,max_nodes=1)
        frames=[read_image(str(RAW/name)) for name in ['shop_animated_npc_live.png',
                'shop_exit_confirm_live.png','map_after_rest_live.png']]
        index=[0]; taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):
            taps.append(bounds); index[0]+=1
        b._tap=tap
        self.assertEqual(b.run()['status'],'completed')
        self.assertEqual(len(taps),2)
        self.assertEqual(taps[0],(1057,646,60,27))
        self.assertEqual(taps[1],n.find(frames[1],'story_confirm'))

    def test_failure_restart_preserves_party_and_stop_event(self):
        with patch('src.chaos.exploration.PartyRecruitmentBot') as recruit, patch('src.chaos.exploration.NodeProgressionBot') as nodes:
            r1,r2,n1,n2=Mock(),Mock(),Mock(),Mock()
            r1.stop_event=threading.Event()
            recruit.side_effect=[r1,r2];nodes.side_effect=[n1,n2]
            party=['rose','wukong','destina','jenua']
            b=ExplorationBot(Mock(),ROOT,self.temp.name,hero_ids=party)
            b._run_stages=Mock(side_effect=[{'status':'round_failed'},{'status':'completed'}])
            result=b.run()
            self.assertEqual(result['failed_rounds'],1)
            self.assertEqual(result['attempt'],2)
            self.assertIs(n2.stop_event,r1.stop_event)
            self.assertIs(r2.stop_event,r1.stop_event)
            self.assertEqual(recruit.call_args.kwargs['hero_ids'],party)

    def test_victory_closes_results_and_returns_round_cleared(self):
        n=NodeObserver(ROOT);n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n)
        b.stats['outcome'] = 'victory'
        frames=[read_image(str(RAW/name)) for name in ['expedition_summary_live.png','entry_after_defeat_live.png']]
        index=[0];taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):taps.append(bounds);index[0]+=1
        b._tap=tap
        result=b.run()
        self.assertEqual(result['status'],'round_cleared',result)
        self.assertEqual(result['outcome'],'victory')
        self.assertEqual(len(taps),1)

    def test_repeat_until_target_clears_reached_with_failures(self):
        b = ExplorationBot(Mock(), ROOT, self.temp.name, target_clears=5)
        stages_results = [
            {'status': 'round_cleared'},
            {'status': 'round_cleared'},
            {'status': 'round_cleared'},
            {'status': 'round_failed'},
            {'status': 'round_cleared'},
            {'status': 'round_cleared'},
        ]
        b._run_stages = Mock(side_effect=stages_results)
        result = b.run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['cleared_rounds'], 5)
        self.assertEqual(result['failed_rounds'], 1)
        self.assertEqual(result['attempt'], 6)
        self.assertEqual(result['reason'], '목표 완주 5회 달성')
        self.assertEqual(b._run_stages.call_count, 6)

    def test_stop_after_defeat_prevents_new_attempt(self):
        b=ExplorationBot(Mock(),ROOT,self.temp.name)
        def failed():
            b.set_user_action('stop')
            return {'status':'round_failed'}
        b._run_stages=Mock(side_effect=failed)
        result=b.run()
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['attempt'],1)
        b._run_stages.assert_called_once()

    def test_supply_acquires_loot_and_leaves_to_map(self):
        n = NodeObserver(ROOT); n.config['poll_seconds'] = 0
        b = NodeProgressionBot(Mock(), ROOT, self.temp.name, observer=n)
        dummy = np.zeros((720, 1280, 3), dtype=np.uint8)
        b._capture = Mock(return_value=dummy)
        b._tap = Mock()
        b._loot = Mock()
        b._classify = Mock(side_effect=['supply', 'loot', 'supply', 'map'])
        b._wait = Mock(side_effect=[
            ('btn', 930, 400, 160, 31),
            (930, 620, 320, 80),
            ('map',)
        ])
        b._supply()
        self.assertEqual(b.stats['nodes'], 1)
        b._loot.assert_called_once()
        b._tap.assert_any_call((930, 400, 160, 31))
        b._tap.assert_any_call((930, 620, 320, 80))

    def test_supply_unclaimed_loot_popup_confirmed_and_returns_to_map(self):
        n = NodeObserver(ROOT); n.config['poll_seconds'] = 0
        b = NodeProgressionBot(Mock(), ROOT, self.temp.name, observer=n)
        b._capture = Mock(return_value=None)
        b._tap = Mock()
        b._tap_with_verify = Mock()
        b._loot = Mock()
        b._wait = Mock(side_effect=[
            ('already_done',),
            (930, 620, 320, 80),
            ('unclaimed_reward',),
            (700, 425, 110, 75)
        ])
        b._state = Mock(return_value='map')
        b._supply()
        self.assertEqual(b.stats['nodes'], 1)
        b._loot.assert_not_called()
        b._tap.assert_any_call((930, 620, 320, 80))
        b._tap_with_verify.assert_called_once()
        self.assertEqual(b._tap_with_verify.call_args[0][0], (700, 425, 110, 75))

    def test_event_battle_victory_and_result_return_count_one_node(self):
        n=NodeObserver(ROOT);n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n,max_nodes=1)
        names=['event_magic_circle_live.png','battle_setup_live.png','battle/auto_off_live.png',
               'battle/victory_live.png','event_magic_result_live.png','map_after_rest_live.png']
        frames=[read_image(str(RAW/name)) for name in names]
        index=[0];taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):taps.append(bounds);index[0]+=1
        b._tap=tap
        b._battle=lambda:index.__setitem__(0,3)
        result=b.run()
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['nodes'],1)
        self.assertEqual(len(taps),4)

    def test_event_result_pages_return_without_reselecting_rewards(self):
        n=NodeObserver(ROOT);n.config['poll_seconds']=0
        b=NodeProgressionBot(Mock(),ROOT,self.temp.name,observer=n,max_nodes=1)
        frames=[read_image(str(RAW/name)) for name in ['event_mushroom_result_live.png',
                'event_mushroom_end_live.png','map_after_rest_live.png']]
        index=[0];taps=[]
        b._capture=lambda:frames[index[0]]
        def tap(bounds):taps.append(bounds);index[0]+=1
        b._tap=tap
        result=b.run()
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['nodes'],1)
        self.assertEqual(len(taps),2)

    def test_elite_and_boss_use_battle_entry(self):
        for kind in ('elite','boss'):
            self.observer.config['supported_nodes']=['elite','boss']
            target=(kind,20,30,40,50)
            self.bot._wait=Mock(return_value=target)
            self.bot._capture=Mock(return_value=None)
            self.observer.classify.return_value='map'
            self.observer.choose_node.return_value=(kind,(20,30,40,50))
            self.bot._tap=Mock();self.bot._guarded_tap=Mock()
            self.bot._state=Mock(side_effect=[kind+'_detail','battle_setup'])
            self.assertTrue(self.bot._select_node())
            self.assertIn('battle_setup',self.bot._state.call_args.args[1])

    def test_loot_confirmation_allows_forbidden_other_card_but_not_selected_card(self):
        target=(195,96,250,425)
        self.observer.classify.return_value='loot'
        self.observer.loot_choices.return_value=[target]
        self.observer.selected_loot.return_value=target
        self.observer.find.return_value=(592,646,102,29)
        self.bot._capture=Mock(return_value=None)
        self.bot._wait=Mock(side_effect=lambda phase,predicate:predicate(None))
        self.bot._tap=Mock();self.bot._state=Mock(return_value='supply')
        self.bot._loot();self.bot._tap.assert_called_once_with((592,646,102,29))
        self.observer.loot_choices.side_effect=[[target],[target],[]]
        self.bot._tap.reset_mock()
        with self.assertRaisesRegex(RuntimeError,'금지'):self.bot._loot()
        self.bot._tap.assert_not_called()

    def test_real_first_battle_replay_taps_auto_once_and_reaches_victory(self):
        observer=NodeObserver(ROOT)
        self.bot.observer=observer
        frames=[read_image(str(RAW / p)) for p in ('battle/auto_off_live.png',
                'battle/auto_started_live.png','battle/auto_next_turn_live.png','battle/victory_levelup_live.png')]
        clock=[0];index=[0]
        def capture():
            clock[0]+=2
            frame=frames[index[0]]
            if index[0] in (1,2):index[0]+=1
            return frame
        self.bot._capture=Mock(side_effect=capture)
        self.bot._guarded_tap=Mock(side_effect=lambda *args:index.__setitem__(0,1))
        self.bot._record=Mock();self.bot.stop_event=Mock();self.bot.stop_event.wait.return_value=False
        with patch('src.chaos.exploration.time.monotonic',side_effect=lambda:clock[0]):self.bot._battle()
        self.bot._guarded_tap.assert_called_once()
        self.assertTrue(self.bot.auto_verified)

    def test_facade_shares_stop_and_runs_recruitment_before_entry(self):
        with patch('src.chaos.exploration.PartyRecruitmentBot') as recruit, patch('src.chaos.exploration.NodeProgressionBot') as nodes:
            r,n=recruit.return_value,nodes.return_value
            n.observer.classify.return_value=None
            r.run.return_value={'status':'completed'}
            r.observer.completed.return_value=True
            n.observer.find.return_value=(10,20,30,40)
            n.run.return_value={'status':'stopped','reason':'unsupported'}
            b=ExplorationBot(Mock(),ROOT,self.temp.name)
            self.assertIs(n.stop_event,r.stop_event)
            self.assertEqual(b.run()['reason'],'unsupported')
            r.run.assert_called_once();n._tap.assert_called_once_with((10,20,30,40))
            n.run.assert_called_once();self.assertIs(b.active,n)

    def test_facade_does_not_enter_after_recruitment_failure(self):
        with patch('src.chaos.exploration.PartyRecruitmentBot') as recruit, patch('src.chaos.exploration.NodeProgressionBot') as nodes:
            nodes.return_value.observer.classify.return_value=None
            recruit.return_value.run.return_value={'status':'failed','reason':'missing hero'}
            b=ExplorationBot(Mock(),ROOT,self.temp.name)
            self.assertEqual(b.run()['status'],'failed')
            nodes.return_value._tap.assert_not_called();nodes.return_value.run.assert_not_called()


if __name__ == '__main__':unittest.main()
