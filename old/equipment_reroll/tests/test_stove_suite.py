"""
Stove Backend Unit Test Suite for SecretShopBot-E7.
Verifies Display Normalizer, Coordinate Mapper, Game Area Detector, Win32 Backend, and UnifiedDevice.
"""
import unittest
import sys
import os
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.display.coordinate_mapper import CoordinateMapper, Anchor
from src.display.game_area import GameArea, GameAreaDetector
from src.display.normalizer import ResolutionNormalizer
from src.finder.window_finder import WindowFinder
from src.backend.capture.win32 import Win32CaptureBackend, BITMAPINFOHEADER
from src.backend.input.win32 import Win32InputBackend, _make_lparam
from src.backend.capture.base import CaptureBackend
from src.backend.input.base import InputBackend
from src.core.device import UnifiedDevice


class TestCoordinateMapper(unittest.TestCase):
    def test_identity_1280x720(self):
        mapper = CoordinateMapper(0, 0, 1280, 720, 1280, 720)
        self.assertEqual(mapper.logical_to_physical(100, 200), (100, 200))
        self.assertEqual(mapper.logical_to_physical(1050, 620), (1050, 620))

    def test_16_9_scaling_1920x1080(self):
        mapper = CoordinateMapper(0, 0, 1920, 1080, 1920, 1080)
        self.assertEqual(mapper.logical_to_physical(1000, 600), (1500, 900))

    def test_pillarbox_ultrawide_2560x1080(self):
        mapper = CoordinateMapper(game_offset_x=320, game_offset_y=0, game_width=1920, game_height=1080, client_width=2560, client_height=1080)
        self.assertEqual(mapper.logical_to_physical(0, 0), (320, 0))
        self.assertEqual(mapper.logical_to_physical(1280, 720), (2240, 1079))


class TestGameAreaDetector(unittest.TestCase):
    def test_exact_16_9_frames(self):
        frame_1080p = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame_1080p[:] = (100, 100, 100)
        area = GameAreaDetector.detect(frame_1080p)
        self.assertEqual(area.rect, (0, 0, 1920, 1080))


class TestResolutionNormalizer(unittest.TestCase):
    def test_normalize_1920x1080(self):
        mapper = CoordinateMapper()
        norm = ResolutionNormalizer(mapper)
        frame_1080p = np.full((1080, 1920, 3), 128, dtype=np.uint8)
        result, area = norm.normalize(frame_1080p)
        self.assertEqual(result.shape, (720, 1280, 3))
        self.assertEqual(area.rect, (0, 0, 1920, 1080))


class TestWin32Backend(unittest.TestCase):
    def test_lparam_packing(self):
        lp = _make_lparam(1050, 620)
        self.assertEqual(lp & 0xFFFF, 1050)
        self.assertEqual((lp >> 16) & 0xFFFF, 620)

    def test_disconnected_backend_graceful_handling(self):
        cap = Win32CaptureBackend(hwnd=0, auto_rebind=False)
        self.assertFalse(cap.is_connected())
        self.assertIsNone(cap.capture())
        inp = Win32InputBackend(hwnd=0, auto_rebind=False)
        self.assertFalse(inp.is_connected())
        self.assertFalse(inp.click(100, 100))


class TestUnifiedDevice(unittest.TestCase):
    class MockCapture(CaptureBackend):
        def is_connected(self) -> bool: return True
        def get_raw_size(self): return (1920, 1080)
        def capture(self): return np.full((1080, 1920, 3), 50, dtype=np.uint8)
        def close(self): pass

    class MockInput(InputBackend):
        def __init__(self):
            self.last_click = None
            self.last_swipe = None
        def is_connected(self) -> bool: return True
        def click(self, x, y, delay=0.5):
            self.last_click = (x, y)
            return True
        def swipe(self, x1, y1, x2, y2, duration_ms=300, delay=0.5):
            self.last_swipe = (x1, y1, x2, y2, duration_ms)
            return True
        def close(self): pass

    def test_device_logical_to_physical_tap(self):
        mock_cap = self.MockCapture()
        mock_inp = self.MockInput()
        dev = UnifiedDevice(mock_cap, mock_inp, backend_name="win32")
        frame = dev.capture_frame()
        self.assertEqual(frame.shape, (720, 1280, 3))
        dev.tap(1000, 600)
        self.assertEqual(mock_inp.last_click, (1500, 900))
        self.assertEqual(dev.get_screen_size(), (1280, 720))

    def test_device_screenshot_unicode_and_nested_path(self):
        import tempfile
        import shutil
        temp_dir = Path(tempfile.mkdtemp(suffix="_테스트"))
        try:
            mock_cap = self.MockCapture()
            mock_inp = self.MockInput()
            dev = UnifiedDevice(mock_cap, mock_inp, backend_name="win32")
            nested_file = temp_dir / "하위폴더" / "screen.png"
            success = dev.screenshot(str(nested_file))
            self.assertTrue(success)
            self.assertTrue(nested_file.exists())
            import cv2
            img = cv2.imdecode(np.fromfile(str(nested_file), dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(img.shape, (720, 1280, 3))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestStoveBotCompatibility(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp(suffix="_bot_compat"))
        self.mock_cap = TestUnifiedDevice.MockCapture()
        self.mock_inp = TestUnifiedDevice.MockInput()
        self.dev = UnifiedDevice(self.mock_cap, self.mock_inp, backend_name="win32")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_equipment_reroll_bot_compatibility(self):
        from src.equipment_reroll_bot import EquipmentRerollBot
        bot = EquipmentRerollBot(
            adb_controller=self.dev,
            target_specs=[{"option": "speed", "value": 4, "is_percent": False}],
            target_mode="exact",
            required_match_count=1,
            max_rerolls=5,
            delay_before_reroll=0.1,
            runtime_dir=self.temp_dir,
        )
        screen = bot._capture_screen()
        self.assertIsNotNone(screen)
        self.assertEqual(screen.shape, (720, 1280, 3))
        bot.set_user_action("stop")
        self.assertEqual(bot.user_action, "stop")

    def test_penguin_bot_compatibility(self):
        from src.penguin_bot import PenguinBot
        bot = PenguinBot(
            adb_controller=self.dev,
            cycle_count=1,
            runtime_dir=self.temp_dir,
        )
        captured = bot._capture_screen("test")
        self.assertTrue(captured)
        screen = bot._capture_screen_image("test")
        self.assertIsNotNone(screen)
        self.assertEqual(screen.shape, (720, 1280, 3))
        # Test tap box
        tapped = bot._tap_box((100, 100, 50, 50), "test_box")
        self.assertTrue(tapped)
        # 100 + 25 = 125, 100 + 25 = 125 logical -> scaled by 1.5: round(187.5) = 188
        self.assertEqual(self.mock_inp.last_click, (188, 188))

    def test_chaos_exploration_bot_compatibility(self):
        from src.chaos.exploration import ExplorationBot
        from src.chaos.node_observer import NodeObserver
        obs = NodeObserver(PROJECT_ROOT)
        bot = ExplorationBot(
            adb=self.dev,
            root=PROJECT_ROOT,
            runtime_dir=self.temp_dir,
            hero_ids=None,
        )
        # Verify device is set on sub-bots
        self.assertEqual(bot.nodes.adb.get_screen_size(), (1280, 720))
        self.assertEqual(bot.recruitment.adb.get_screen_size(), (1280, 720))
        # Test node ProgressionBot tap with logical bounds passes 1280x720 validation
        bot.nodes._tap((640, 360, 20, 20))
        self.assertEqual(self.mock_inp.last_click, (int(round(650 * 1.5)), int(round(370 * 1.5))))

    def test_summer_event_bot_compatibility(self):
        from src.event.registry import load_event_module
        event_module = load_event_module("2026_summer_event")
        SummerEventExecutor = event_module.SummerEventExecutor
        SummerEventObserver = event_module.SummerEventObserver

        layout_path = PROJECT_ROOT / "src" / "event" / "events" / "2026_summer_event" / "screen_layout.json"
        layout = event_module.load_screen_layout(layout_path)

        observer = SummerEventObserver(
            adb=self.dev,
            layout=layout,
            screenshot_path=self.temp_dir / "event_screen.png",
            template_dir=PROJECT_ROOT / "images" / "2026_summer_event",
            screen_size=self.dev.get_screen_size(),
        )
        executor = SummerEventExecutor(
            adb=self.dev,
            layout=layout,
            screen_size=self.dev.get_screen_size(),
        )
        # Executor tap sends basic tap
        executor._tap("basic", delay=0.1)
        # Basic tap is (640, 655) logical -> scaled by 1.5 -> (960, 982) physical
        self.assertEqual(self.mock_inp.last_click, (960, 982))


class TestProcessGuard(unittest.TestCase):
    def test_process_info_query(self):
        from src.core.process_guard import get_process_name, get_process_cmdline, kill_previous_instances
        pid = os.getpid()
        proc_name = get_process_name(pid)
        self.assertTrue("python" in proc_name.lower())
        cmd = get_process_cmdline(pid)
        self.assertTrue(len(cmd) > 0)
        # Running kill_previous_instances should execute cleanly without killing current process
        killed = kill_previous_instances()
        self.assertIsInstance(killed, int)


if __name__ == "__main__":
    unittest.main()
