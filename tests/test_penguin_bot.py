import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.penguin_bot import PenguinBot


class DummyADB:
    def __init__(self):
        self.taps = []

    def screenshot(self, *_args, **_kwargs):
        return True

    def tap(self, x, y, delay=0.3):
        self.taps.append((x, y, delay))
        return True

    def get_screen_size(self):
        return (1280, 720)


class PenguinBotTest(unittest.TestCase):
    def _make_bot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = PenguinBot(DummyADB(), cycle_count=1, runtime_dir=temp_dir)
        return bot

    def test_runtime_dir_uses_session_specific_screenshot_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = PenguinBot(DummyADB(), cycle_count=3, runtime_dir=temp_dir)

            self.assertEqual(bot.screenshot_path, Path(temp_dir) / "penguin_screen.png")

    def test_find_egg_match_uses_only_matches_within_vertical_range(self):
        bot = object.__new__(PenguinBot)
        bot.EGG_MIN_X = PenguinBot.EGG_MIN_X
        bot.EGG_MAX_X = PenguinBot.EGG_MAX_X
        bot.EGG_IMAGE = PenguinBot.EGG_IMAGE
        bot.thresholds = {"egg": 0.9}
        bot.EGG_MATCH_SCALES = (1.0,)

        bot._find_all_matches = lambda *_args, **_kwargs: [
            (0, 100, 20, 20),
            (100, 100, 20, 20),
            (360, 100, 20, 20),
        ]
        bot._match_score_for_box = lambda *_args, **_kwargs: 0.95

        match = PenguinBot._find_egg_match(bot, np.zeros((720, 1280, 3), dtype=np.uint8))

        self.assertEqual(match, (100, 100, 20, 20))

    def test_find_buy_button_for_egg_picks_button_in_same_column_below_egg(self):
        bot = object.__new__(PenguinBot)
        bot.thresholds = {"buy_button": 0.9}
        bot.BUY_BUTTON_IMAGE = PenguinBot.BUY_BUTTON_IMAGE
        bot._find_all_matches = lambda *_args, **_kwargs: [
            (220, 220, 50, 18),
            (145, 300, 50, 18),
            (320, 310, 50, 18),
        ]

        screen = np.zeros((400, 500, 3), dtype=np.uint8)
        match = PenguinBot._find_buy_button_for_egg(bot, screen, (100, 120, 20, 24))

        self.assertEqual(match, (145, 300, 50, 18))

    @patch("src.penguin_bot.time.sleep", return_value=None)
    def test_single_cycle_clicks_max_when_not_fifty_fifty(self, _sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = PenguinBot(DummyADB(), cycle_count=1, runtime_dir=temp_dir)

        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        states = [screen, screen, screen, screen]
        bot._capture_screen = lambda _context: True
        bot._find_egg_match = lambda _screen: (80, 100, 30, 30)
        bot._find_buy_button_for_egg = lambda _screen, _egg: (500, 100, 60, 24)
        bot._has_popup_fifty_check = lambda _screen: False
        bot._find_popup_max_button = lambda _screen: (520, 420, 70, 24)
        bot._find_popup_final_buy_button = lambda _screen: (530, 430, 70, 24)
        bot._find_best_match = lambda _screen, image_name, _threshold: (
            (600, 500, 30, 20) if image_name == PenguinBot.CLOSE_IMAGE else None
        )

        with patch("src.penguin_bot.read_image", side_effect=states):
            success = bot._run_single_cycle()

        self.assertTrue(success)
        self.assertEqual(len(bot.adb.taps), 4)
        self.assertEqual(bot.stats["purchase_attempts"], 1)
        self.assertEqual(bot.stats["penguins_bought"], 1)


if __name__ == "__main__":
    unittest.main()
