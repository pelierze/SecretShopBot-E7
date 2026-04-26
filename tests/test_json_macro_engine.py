import sys
import threading
import time
import types
import unittest
import tempfile
from pathlib import Path


def _install_fake_dependencies():
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.IMREAD_COLOR = 1
    fake_cv2.TM_CCOEFF_NORMED = 5
    fake_cv2.imdecode = lambda data, flags: None
    fake_cv2.matchTemplate = lambda screen, template, method: None
    fake_cv2.minMaxLoc = lambda result: (0.0, 0.0, (0, 0), (0, 0))
    sys.modules.setdefault("cv2", fake_cv2)

    fake_numpy = types.ModuleType("numpy")
    fake_numpy.uint8 = int
    fake_numpy.fromfile = lambda *args, **kwargs: []
    fake_numpy.array = lambda value: value
    fake_numpy.argsort = lambda value: []
    fake_numpy.maximum = max
    fake_numpy.minimum = min
    fake_numpy.where = lambda value: ([], [])
    fake_numpy.concatenate = lambda values: []
    fake_numpy.delete = lambda values, indexes: []
    sys.modules.setdefault("numpy", fake_numpy)


_install_fake_dependencies()

from src.json_macro_engine import JsonMacroEngine


class FakeADB:
    def __init__(self, screenshot_ok=True, swipe_ok=True):
        self.screenshot_ok = screenshot_ok
        self.swipe_ok = swipe_ok
        self.screenshot_calls = 0
        self.swipe_calls = 0

    def get_screen_size(self):
        return (1280, 720)

    def screenshot(self, save_path):
        self.screenshot_calls += 1
        return self.screenshot_ok

    def swipe(self, x1, y1, x2, y2, duration=300, delay=0.5):
        self.swipe_calls += 1
        return self.swipe_ok

    def tap(self, x, y, delay=0.5):
        return True


class JsonMacroEngineTest(unittest.TestCase):
    def test_runtime_dir_uses_session_specific_screenshot_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = JsonMacroEngine(
                FakeADB(),
                macro_definition={"id": "steps", "steps": []},
                automation_settings={},
                runtime_dir=temp_dir,
            )

            self.assertEqual(engine.screenshot_path, Path(temp_dir) / "current_screen.png")

    def test_wait_step_honors_stop_while_sleeping(self):
        engine = JsonMacroEngine(
            FakeADB(),
            macro_definition={"id": "steps", "steps": []},
            automation_settings={},
        )

        result_holder = {}

        def run_sleep():
            result_holder["result"] = engine._sleep_with_stop(2.0)

        thread = threading.Thread(target=run_sleep)
        start = time.time()
        thread.start()
        time.sleep(0.2)
        engine.set_user_action("stop")
        thread.join(timeout=1.0)
        elapsed = time.time() - start

        self.assertFalse(thread.is_alive(), "stop 요청 후 wait가 빠르게 끝나야 합니다.")
        self.assertFalse(result_holder["result"])
        self.assertLess(elapsed, 1.5)

    def test_screenshot_failure_stops_macro_run(self):
        engine = JsonMacroEngine(
            FakeADB(screenshot_ok=False),
            macro_definition={"id": "steps", "steps": [{"action": "screenshot"}]},
            automation_settings={},
        )

        stats = engine.run(1, 1)

        self.assertEqual(stats["completed_runs"], 1)
        self.assertEqual(stats["successful_refreshes"], 0)
        self.assertEqual(engine.adb.screenshot_calls, 1)

    def test_swipe_failure_stops_macro_run(self):
        engine = JsonMacroEngine(
            FakeADB(swipe_ok=False),
            macro_definition={"id": "steps", "steps": [{"action": "swipe"}]},
            automation_settings={"swipe": {"x_ratio": 0.5}},
        )

        stats = engine.run(1, 1)

        self.assertEqual(stats["completed_runs"], 1)
        self.assertEqual(stats["successful_refreshes"], 0)
        self.assertEqual(engine.adb.swipe_calls, 1)


if __name__ == "__main__":
    unittest.main()
