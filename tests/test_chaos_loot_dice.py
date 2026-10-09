import unittest
from pathlib import Path

from src.chaos.errors import RecognitionPending
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'images/chaos/node_progression/raw'


class LootDiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_three_dice_recognize_latest_and_existing_loot_lists(self):
        for filename in ('elite_loot_cards_local_live.png', 'loot_cards_live.png',
                         'elite_loot_cards_live.png', 'boss_loot_cards_live.png',
                         'loot_supply_selected_report_20261005.png'):
            with self.subTest(filename=filename):
                screen = read_image(str(RAW / filename))
                self.assertEqual(len(self.observer.all(screen, 'loot_reroll')), 3)
                self.assertEqual(self.observer.classify(screen), 'loot')
                self.observer.loot_choices(screen)

    def test_reroll_text_and_price_number_are_not_required(self):
        screen = read_image(str(RAW / 'elite_loot_cards_local_live.png'))
        for x in (231, 551, 871):
            screen[536:575, x:x+211] = 0
        self.assertEqual(len(self.observer.all(screen, 'loot_reroll')), 3)
        self.assertEqual(self.observer.classify(screen), 'loot')

    def test_missing_die_does_not_authorize_card_selection(self):
        screen = read_image(str(RAW / 'elite_loot_cards_local_live.png'))
        screen[539:571, 203:231] = 0
        self.assertNotEqual(self.observer.classify(screen), 'loot')
        with self.assertRaises(RecognitionPending):
            self.observer.loot_choices(screen)

    def test_three_dice_in_wrong_positions_do_not_authorize_cards(self):
        screen = read_image(str(RAW / 'elite_loot_cards_local_live.png'))
        die = self.observer.templates['loot_reroll']
        screen[539:571, 203:231] = 0
        screen[539:571, 440:468] = die
        self.assertEqual(len(self.observer.all(screen, 'loot_reroll')), 3)
        with self.assertRaises(RecognitionPending):
            self.observer.loot_choices(screen)

    def test_top_right_currency_icon_cannot_replace_reroll_dice(self):
        screen = read_image(str(RAW / 'elite_loot_cards_local_live.png'))
        screen[530:585, 180:1110] = 0
        self.assertEqual(self.observer.all(screen, 'loot_reroll'), [])


if __name__ == '__main__':
    unittest.main()
