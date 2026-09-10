import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile

from src.secret_shop_bot import SecretShopBot


class DummyADB:
    def __init__(self, result=True):
        self.result = result
        self.calls = []
        self.taps = []

    def screenshot(self, *args, **kwargs):
        return True

    def tap(self, *args, **kwargs):
        self.taps.append((args, kwargs))
        return True

    def get_screen_size(self):
        return (1280, 720)

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
    @patch("src.secret_shop_bot.time.sleep")
    def test_natural_refresh_scans_every_fifteen_minutes_without_paid_refresh(self, sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SecretShopBot(DummyADB(), runtime_dir=temp_dir)
            now = [0.0]
            def advance(seconds):
                now[0] += seconds
                if now[0] >= 902:
                    bot.set_user_action("stop")
            sleep.side_effect = advance
            scans = []
            def scan(page_num):
                scans.append((page_num, now[0]))
                return {"mystic_medal": (1, 2, 3, 4)}
            bot._scan_shop_page = scan
            bot._purchase_item = Mock(return_value=True)
            bot._refresh_shop = Mock()
            bot._refresh_shop_with_recovery = Mock()
            with patch("src.secret_shop_bot.time.monotonic", side_effect=lambda: now[0]):
                stats = bot.run_natural_refresh(3)
            self.assertEqual([page for page, _ in scans], [1, 2, 1, 2])
            self.assertAlmostEqual(scans[2][1] - scans[0][1], 900)
            self.assertEqual(bot._purchase_item.call_count, 4)
            self.assertEqual(stats["completed_runs"], 2)
            self.assertEqual(stats["successful_refreshes"], 0)
            self.assertEqual(stats["total_refreshes"], 0)
            bot._refresh_shop.assert_not_called()
            bot._refresh_shop_with_recovery.assert_not_called()
            self.assertEqual(len(bot.adb.calls), 4)

    @patch("src.secret_shop_bot.time.sleep")
    def test_natural_refresh_pause_waits_and_stop_interrupts(self, sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SecretShopBot(DummyADB(), runtime_dir=temp_dir)
            bot.set_user_action("pause")
            sleep.side_effect = lambda _: bot.set_user_action("stop")
            stats = bot.run_natural_refresh(3)
            self.assertEqual(stats["completed_runs"], 0)
            self.assertEqual(bot.adb.calls, [])

    @patch("src.secret_shop_bot.time.sleep", return_value=None)
    def test_natural_refresh_stops_on_purchase_failure(self, sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SecretShopBot(DummyADB(), runtime_dir=temp_dir)
            bot._wait_natural_refresh = Mock(return_value=True)
            bot._scan_shop_page = Mock(return_value={"mystic_medal": (1, 2, 3, 4)})
            bot._purchase_item = Mock(return_value=False)
            stats = bot.run_natural_refresh(3)
            self.assertEqual(stats["completed_runs"], 0)
            bot._scan_shop_page.assert_called_once_with(page_num=1)

    def test_runtime_dir_uses_session_specific_screenshot_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SecretShopBot(DummyADB(), runtime_dir=temp_dir, automation_settings={})
            self.assertEqual(bot.screenshot_path, Path(temp_dir) / "current_screen.png")

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

    def test_scroll_up_calls_single_swipe_once(self):
        bot = object.__new__(SecretShopBot)
        bot.adb = DummyADB()
        bot.swipe_x = 960
        bot.swipe_start_y = 540
        bot.swipe_end_y = 180
        bot.swipe_duration = 1000

        bot._scroll_up()

        self.assertEqual(len(bot.adb.calls), 1)
        args, kwargs = bot.adb.calls[0]
        self.assertEqual(args, (960, 180, 960, 540))
        self.assertEqual(kwargs, {"duration": 1000, "delay": 0.5})

    @patch("src.secret_shop_bot.time.sleep", return_value=None)
    def test_refresh_shop_with_recovery_scrolls_up_before_retry(self, _sleep):
        bot = object.__new__(SecretShopBot)
        bot.user_action = None
        bot.refresh_recovery_attempts = 1
        bot.timings = {"refresh_retry": 2.0}
        bot._timing = SecretShopBot._timing.__get__(bot, SecretShopBot)

        attempts = []
        bot._refresh_shop = lambda: attempts.append("refresh") or len(attempts) >= 2
        bot._scroll_up = lambda: attempts.append("scroll_up")

        result = bot._refresh_shop_with_recovery()

        self.assertTrue(result)
        self.assertEqual(attempts, ["refresh", "scroll_up", "refresh"])

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


    def test_default_enabled_items_excludes_friendship_point(self):
        bot = SecretShopBot(DummyADB(), automation_settings={})

        self.assertEqual(bot.enabled_items, ["mystic_medal", "covenant_bookmark"])
        self.assertIn("friendship_point", bot.item_definitions)

    def test_enabled_items_can_include_friendship_point(self):
        bot = SecretShopBot(
            DummyADB(),
            automation_settings={
                "macro": {
                    "enabled_items": [
                        "mystic_medal",
                        "covenant_bookmark",
                        "friendship_point",
                    ]
                }
            },
        )

        self.assertEqual(
            bot.enabled_items,
            ["mystic_medal", "covenant_bookmark", "friendship_point"],
        )
        self.assertEqual(
            bot.item_definitions["friendship_point"]["stat_key"],
            "friendship_point_bought",
        )


if __name__ == "__main__":
    unittest.main()
