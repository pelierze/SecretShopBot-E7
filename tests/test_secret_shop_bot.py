import unittest
from unittest.mock import patch
from pathlib import Path

from src.secret_shop_bot import SecretShopBot


class DummyADB:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def screenshot(self, *args, **kwargs):
        return True

    def swipe(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class DummyMatcher:
    def __init__(self, result=None, similarity=0.94):
        self.result = result
        self.similarity = similarity

    def find_image(self, *args, **kwargs):
        return self.result

    def get_similarity_at_location(self, *args, **kwargs):
        return self.similarity


class SecretShopBotScrollTest(unittest.TestCase):
    def test_scroll_down_calls_single_swipe_once(self):
        bot = object.__new__(SecretShopBot)
        bot.adb = DummyADB()
        bot.swipe_x = 960
        bot.swipe_start_y = 540
        bot.swipe_end_y = 180
        bot.swipe_duration = 1000

        bot._scroll_down()

        self.assertEqual(len(bot.adb.calls), 1)
        args, kwargs = bot.adb.calls[0]
        self.assertEqual(args, (960, 540, 960, 180))
        self.assertEqual(kwargs, {"duration": 1000, "delay": 0.5})

    @patch("src.secret_shop_bot.time.sleep", return_value=None)
    def test_refresh_shop_retries_confirm_button_before_failing(self, _sleep):
        bot = object.__new__(SecretShopBot)
        bot.user_action = None
        bot.debug_mode = False
        bot.timings = {
            "refresh_confirm_delay": 0.5,
            "refresh_confirm_attempts": 4,
            "refresh_confirm_retry_interval": 0.3,
            "after_refresh": 0.8,
        }
        bot._timing = SecretShopBot._timing.__get__(bot, SecretShopBot)

        calls = []

        def fake_click(button_type):
            calls.append(button_type)
            if button_type == "refresh":
                return True
            return len([name for name in calls if name == "refresh_confirm"]) >= 3

        bot._click_button = fake_click

        result = bot._refresh_shop()

        self.assertTrue(result)
        self.assertEqual(calls[0], "refresh")
        self.assertEqual(calls.count("refresh_confirm"), 3)

    @patch("src.secret_shop_bot.logger.info")
    @patch("src.secret_shop_bot.time.sleep", return_value=None)
    def test_scan_shop_page_logs_item_match_percentage(self, _sleep, mock_info):
        bot = object.__new__(SecretShopBot)
        bot.user_action = None
        bot.adb = DummyADB()
        bot.matcher = DummyMatcher(result=(10, 20, 30, 40), similarity=0.94)
        bot.screenshot_path = "dummy_screen.png"
        bot.enabled_items = ["mystic_medal"]
        bot.item_definitions = {"mystic_medal": {"label": "신비의 메달", "image": "mystic_medal.png"}}
        bot.resource_dir = Path(".")
        bot.ITEMS_DIR = "images/items"
        bot.thresholds = {"mystic_medal": 0.92}
        bot._timing = SecretShopBot._timing.__get__(bot, SecretShopBot)
        bot.timings = {}
        bot._item_label = SecretShopBot._item_label.__get__(bot, SecretShopBot)
        bot._find_image_file = lambda directory, base_name: "mystic_medal.png"

        found_items = bot._scan_shop_page(page_num=1)

        self.assertEqual(found_items, {"mystic_medal": (10, 20, 30, 40)})
        self.assertTrue(
            any("매칭률: 94.0%" in call.args[0] for call in mock_info.call_args_list),
            mock_info.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
