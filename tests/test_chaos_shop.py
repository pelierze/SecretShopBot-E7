import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.chaos.exploration import NodeProgressionBot, ExplorationBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'images/chaos/node_progression/raw'


class ShopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)
        cls.observer.config['poll_seconds'] = 0

    def image(self, name):
        return read_image(str(RAW/'shop'/f'{name}.png'))

    def test_available_sold_out_and_other_blocked_product(self):
        for name,balance in [('shop_full',464),('future_investment_available',223)]:
            frame = self.image(name)
            self.assertEqual(self.observer.shop_investment_offer(frame)[:3],('buy',50,balance))
        self.assertEqual(self.observer.shop_investment_offer(self.image('future_investment_purchased')),('skip',))

    def test_insufficient_currency_and_blocked_target_skip(self):
        frame = self.image('future_investment_available')
        with patch.object(self.observer,'shop_number',side_effect=[50,49]):
            self.assertEqual(self.observer.shop_investment_offer(frame),('skip',))
        with patch.object(self.observer,'forbidden',return_value=[('blocked',(425,160,50,50))]):
            self.assertEqual(self.observer.shop_investment_offer(frame),('skip',))

    def test_real_red_price_and_notice_skip_without_ocr(self):
        for name in ('shop_not_enough','shop_not_enough_message'):
            with self.subTest(name=name), patch.object(self.observer,'shop_number') as number:
                self.assertEqual(self.observer.shop_investment_offer(self.image(name)),('skip',))
                number.assert_not_called()

    def test_other_products_red_prices_do_not_block_target(self):
        frame = self.image('shop_not_enough')
        available = self.image('future_investment_available')
        frame[90:342,390:577] = available[90:342,390:577]
        frame[18:50,922:978] = available[18:50,922:978]
        self.assertEqual(self.observer.shop_investment_offer(frame)[:3],('buy',50,223))

    def test_insufficient_notice_after_input_never_retries_purchase(self):
        for after_confirm in (False,True):
            with self.subTest(after_confirm=after_confirm), tempfile.TemporaryDirectory() as tmp:
                bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,buy_future_investment=True)
                frames=[self.image('future_investment_available')]
                if after_confirm: frames.append(self.image('future_investment_confirm'))
                frames.append(self.image('shop_not_enough_message'))
                current=[0]
                bot._capture=lambda:frames[current[0]]
                bot._tap=lambda bounds:current.__setitem__(0,current[0]+1)
                bot._purchase_future_investment()
                self.assertEqual(current[0],2 if after_confirm else 1)
                self.assertEqual(bot.stats.get('shop_purchases',0),0)
    def test_full_purchase_and_exit_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(),ROOT,tmp,self.observer,buy_future_investment=True)
            frames = [self.image(n) for n in ('future_investment_available','future_investment_confirm','future_investment_purchased')]
            frames += [read_image(str(RAW/'shop_exit_confirm_live.png')),read_image(str(RAW/'boss_map_live.png'))]
            current=[0];taps=[]
            bot._capture=lambda:frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds));current[0]+=1
            bot._tap=tap
            bot._shop()
            self.assertEqual(current[0],4)
            self.assertEqual(len(taps),4)
            self.assertEqual(bot.stats['shop_purchases'],1)
            self.assertEqual(bot.stats['nodes'],1)

    def test_wrong_item_confirmation_is_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer,buy_future_investment=True)
            confirm=self.image('future_investment_confirm');confirm[310:395,500:755]=0
            frames=[self.image('future_investment_available'),confirm,self.image('future_investment_available')]
            current=[0];taps=[]
            bot._capture=lambda:frames[current[0]]
            def tap(bounds):taps.append(tuple(bounds));current[0]+=1
            bot._tap=tap
            bot._purchase_future_investment()
            self.assertEqual(taps[-1],self.observer.find(confirm,'shop_purchase_cancel'))
            self.assertEqual(bot.stats.get('shop_purchases',0),0)

    def test_purchase_reward_popup_is_closed_before_verifying_and_exiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, buy_future_investment=True)
            frames = [self.image('future_investment_available'), self.image('future_investment_confirm'),
                      read_image(str(RAW/'event_loot_popup_live.png')), self.image('future_investment_purchased'),
                      read_image(str(RAW/'shop_exit_confirm_live.png')), read_image(str(RAW/'boss_map_live.png'))]
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                current[0] += 1
            bot._tap = tap
            bot._shop()
            self.assertEqual(len(taps), 5)
            self.assertEqual(taps[2], self.observer.find(frames[2], 'event_loot_close'))
            self.assertEqual(taps.count(self.observer.find(frames[1], 'shop_purchase_button')), 1)
            self.assertEqual(bot.stats['shop_purchases'], 1)
            self.assertEqual(bot.stats['nodes'], 1)

    def test_popup_close_does_not_replace_purchase_verification(self):
        from src.chaos.bot import RecognitionTimeout
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, buy_future_investment=True)
            frames = [self.image('future_investment_available'), self.image('future_investment_confirm'),
                      read_image(str(RAW/'event_loot_popup_live.png')), self.image('future_investment_purchased')]
            frames[-1][290:319, 445:525] = 0  # Remove the purchased acknowledgement.
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                current[0] += 1
            bot._tap = tap
            wait = bot._wait
            def fail_missing_acknowledgement(phase, predicate):
                if current[0] == 3 and phase == '미래 투자 구매 완료·파편 차감 확인':
                    self.assertIsNone(predicate(frames[3]))
                    raise RecognitionTimeout('구매 완료 미확인')
                return wait(phase, predicate)
            bot._wait = fail_missing_acknowledgement
            with self.assertRaises(RecognitionTimeout):
                bot._purchase_future_investment()
            self.assertEqual(len(taps), 3)
            self.assertEqual(bot.stats.get('shop_purchases', 0), 0)

    def test_exit_confirmation_recovers_a_dropped_close(self):
        import itertools
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            frames = [read_image(str(RAW/'shop_exit_confirm_live.png')), read_image(str(RAW/'boss_map_live.png'))]
            current = [0]
            taps = []
            bot._capture = lambda: frames[current[0]]
            def tap(bounds):
                taps.append(tuple(bounds))
                if len(taps) == 2:
                    current[0] = 1
            bot._tap = tap
            ticks = itertools.count()
            with patch('src.chaos.exploration.time.monotonic', side_effect=lambda: next(ticks)):
                bot._shop_confirm()
            self.assertEqual(len(taps), 2)
            self.assertEqual(bot.stats['nodes'], 1)

    def test_option_default_off_and_repeat_preserves_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=NodeProgressionBot(Mock(),ROOT,tmp,self.observer)
            bot._capture=Mock(return_value=self.image('future_investment_available'))
            bot._purchase_future_investment=Mock();bot._guarded_tap=Mock();bot._state=Mock(return_value='map')
            bot._shop();bot._purchase_future_investment.assert_not_called()
            facade=ExplorationBot(Mock(),ROOT,tmp,target_clears=2,buy_future_investment=True)
            def run_round():
                self.assertTrue(facade.nodes.buy_future_investment)
                return {'status':'round_cleared'}
            facade._run_stages=run_round
            self.assertEqual(facade.run()['cleared_rounds'],2)
