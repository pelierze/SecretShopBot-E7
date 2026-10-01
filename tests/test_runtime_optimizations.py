import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.image_matcher import ImageMatcher
from src.display.game_area import GameAreaDetector
from src.backend.capture import win32
from src.gui import SessionView
from build_support.release_assets import RUNTIME_FILES, collect_runtime_files, validate_package


class RuntimeOptimizationsTest(unittest.TestCase):
    def test_template_cache_refresh_and_memory_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'template.png'
            frame = np.random.default_rng(8).integers(0, 256, (40, 50, 3), dtype=np.uint8)
            template = frame[10:20, 15:25].copy()
            cv2.imencode('.png', template)[1].tofile(str(path))
            matcher = ImageMatcher()
            self.assertEqual(matcher.find_image(frame, path)[:2], (15, 10))
            first = matcher._read_template(path)
            self.assertIs(matcher._read_template(path), first)
            cv2.imencode('.png', np.zeros((12, 12, 3), dtype=np.uint8))[1].tofile(str(path))
            self.assertEqual(matcher._read_template(path).shape, (12, 12, 3))
            self.assertEqual(len(matcher._templates), 1)
            path.unlink()
            self.assertIsNone(matcher._read_template(path))

    def test_black_bar_detection_keeps_offsets(self):
        for color in (False, True):
            frame = np.zeros((900, 1280, 3) if color else (900, 1280), dtype=np.uint8)
            frame[90:810] = 80
            self.assertEqual(GameAreaDetector.detect(frame).rect, (0, 90, 1280, 720))
            frame = np.zeros((720, 1600, 3) if color else (720, 1600), dtype=np.uint8)
            frame[:, 160:1440] = 80
            self.assertEqual(GameAreaDetector.detect(frame).rect, (160, 0, 1280, 720))

    def test_capture_reuses_resources_preserves_frames_and_handles_resize(self):
        user = Mock()
        user.IsWindow.return_value = True
        user.IsIconic.return_value = False
        user.GetDC.return_value = 100
        user.PrintWindow.return_value = True
        gdi = Mock()
        gdi.CreateCompatibleDC.return_value = 101
        gdi.CreateCompatibleBitmap.return_value = 102
        gdi.SelectObject.return_value = 103
        pixel = [20]
        def read_bits(dc, bitmap, start, height, buffer, info, colors):
            header = info._obj.bmiHeader
            ctypes.memset(buffer, pixel[0], header.biWidth * height * 4)
            return height
        gdi.GetDIBits.side_effect = read_bits
        with patch.object(win32, 'user32', user), patch.object(win32, 'gdi32', gdi), \
                patch.object(win32.WindowFinder, 'get_rects', return_value=((0, 0, 10, 10), (0, 0, 10, 10), (10, 10))) as rects:
            backend = win32.Win32CaptureBackend(hwnd=1, auto_rebind=False)
            first = backend.capture()
            pixel[0] = 30
            second = backend.capture()
            self.assertTrue(np.all(first == 20))
            self.assertTrue(np.all(second == 30))
            self.assertEqual(gdi.CreateCompatibleBitmap.call_count, 1)
            rects.return_value = ((0, 0, 12, 10), (0, 0, 12, 10), (12, 10))
            self.assertEqual(backend.capture().shape, (10, 12, 3))
            self.assertEqual(gdi.CreateCompatibleBitmap.call_count, 2)
            backend.close()
            backend.close()
            self.assertEqual(gdi.DeleteDC.call_count, 2)
            self.assertEqual(gdi.DeleteObject.call_count, 2)
            self.assertEqual(user.ReleaseDC.call_count, 3)

    def test_failed_gdi_allocation_releases_partial_resources(self):
        backend = win32.Win32CaptureBackend(hwnd=1, auto_rebind=False)
        gdi = Mock()
        gdi.CreateCompatibleDC.return_value = 101
        gdi.CreateCompatibleBitmap.return_value = 0
        with patch.object(win32, 'gdi32', gdi):
            with self.assertRaises(OSError):
                backend._prepare_resources(100, 10, 10)
            gdi.DeleteDC.assert_called_once_with(101)
            self.assertIsNone(backend._resource_key)

    def test_stale_stove_completion_closes_device_without_ui_changes(self):
        view = object.__new__(SessionView)
        view._stove_request_id = 2
        view.backend_type_var = Mock(get=Mock(return_value='stove'))
        view.app = Mock(is_closing=False)
        view.connection_status = Mock()
        device = Mock()
        view._stove_connection_finished(1, device, None)
        device.close.assert_called_once()
        view.connection_status.config.assert_not_called()

    def test_package_allowlist_rejects_future_developer_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe'):
                (root / name).touch()
            internal = root / '_internal'
            for name in RUNTIME_FILES:
                p = internal / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            validate_package(root)
            self.assertEqual(len(collect_runtime_files(internal)), len(RUNTIME_FILES))
            unwanted = internal / 'tools/new-debug.ps1'
            unwanted.touch()
            with self.assertRaises(ValueError):
                validate_package(root)
            unwanted.unlink()
            (root / 'DEPLOY.md').touch()
            with self.assertRaises(ValueError):
                validate_package(root)

    def test_stove_connection_checks_only_run_inside_worker(self):
        view = object.__new__(SessionView)
        view.name = 'test'
        view.stove_combo = Mock(current=Mock(return_value=-1))
        view.connect_btn = Mock()
        view.connection_status = Mock()
        view.root = Mock()
        device = Mock()
        device.capture_backend.hwnd = 1
        device.test_connection.return_value = (True, 'ok')
        with patch('src.gui.threading.Thread') as thread, \
                patch('src.gui.BackendFactory.create_win32_device', return_value=device) as factory, \
                patch('ctypes.windll.user32.IsIconic', return_value=False), \
                patch('ctypes.windll.user32.IsWindowVisible', return_value=True):
            view._connect_stove()
            factory.assert_not_called()
            device.test_connection.assert_not_called()
            view.connection_status.reset_mock()
            thread.call_args.kwargs['target']()
            device.test_connection.assert_called_once()
            view.connection_status.config.assert_not_called()
            view.root.after.assert_called_once()
