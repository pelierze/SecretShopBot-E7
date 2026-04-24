import unittest

from src.secret_shop_bot import SecretShopBot


class DummyADB:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def swipe(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


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


if __name__ == "__main__":
    unittest.main()
