import unittest
from unittest.mock import Mock, patch
from src.finder.window_resizer import WindowResizer
from src.gui import SessionView


class WindowResizeTests(unittest.TestCase):
    def setUp(self):
        self.resizer = object.__new__(WindowResizer)
        self.api = self.resizer.api = Mock()
        self.api.IsWindow.return_value = True
        self.api.IsIconic.return_value = False
        self.api.IsZoomed.return_value = False
        self.api.GetWindowLongW.return_value = 0x00C00000
        self.api.SetWindowPos.return_value = True
        self.size = (1600, 900)

        def client(hwnd, ptr):
            ptr._obj.right, ptr._obj.bottom = self.size
            return True

        def outer(hwnd, ptr):
            ptr._obj.left, ptr._obj.top = 100, 200
            ptr._obj.right, ptr._obj.bottom = 1716, 1139
            return True

        self.api.GetClientRect.side_effect = client
        self.api.GetWindowRect.side_effect = outer

    def test_physical_frame_margins_and_background_flags(self):
        self.resizer.request(123)
        self.api.SetWindowPos.assert_called_once_with(123, None, 0, 0, 1296, 759, self.resizer.FLAGS)
        self.assertTrue(self.resizer.FLAGS & 0x0010)  # NOACTIVATE
        self.assertTrue(self.resizer.FLAGS & 0x0002)  # NOMOVE
        self.assertTrue(self.resizer.FLAGS & 0x0004)  # NOZORDER
        self.assertTrue(self.resizer.FLAGS & 0x4000)  # ASYNCWINDOWPOS
        self.api.SetCursorPos.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()

    def test_already_matching_size_sends_no_resize(self):
        self.size = (1280, 720)
        self.resizer.request(123)
        self.api.SetWindowPos.assert_not_called()

    def test_closed_minimized_maximized_and_borderless_are_rejected(self):
        cases = [('IsWindow', False), ('IsIconic', True),
                 ('IsZoomed', True), ('GetWindowLongW', 0)]
        for name, value in cases:
            function = getattr(self.api, name)
            old = function.return_value
            function.return_value = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.resizer.request(123)
            function.return_value = old
        self.api.SetWindowPos.assert_not_called()

    def test_failed_rect_and_resize_are_reported(self):
        self.api.GetWindowRect.side_effect = None
        self.api.GetWindowRect.return_value = False
        with self.assertRaises(OSError):
            self.resizer.request(123)
        self.api.GetWindowRect.return_value = True
        # Valid margins for the separate failed SetWindowPos case.
        def outer(hwnd, ptr):
            ptr._obj.right, ptr._obj.bottom = 1616, 939
            return True
        self.api.GetWindowRect.side_effect = outer
        self.api.SetWindowPos.return_value = False
        with self.assertRaises(OSError):
            self.resizer.request(123)


class WindowResizeGuiTests(unittest.TestCase):
    def view(self):
        view = object.__new__(SessionView)
        view.name = 'test'
        view.is_running = False
        view.bot_thread = None
        view.backend_type_var = Mock(get=Mock(return_value='stove'))
        view.stove_combo = Mock(current=Mock(return_value=0))
        view.scanned_stove_windows = [Mock(hwnd=123)]
        view.stove_resize_btn = Mock()
        view.stove_resize_status = Mock()
        view.root = Mock()
        view.adb_controller = Mock(capture_backend=Mock(hwnd=123))
        view.app = Mock(sessions=[view])
        return view

    @patch('src.gui.WindowResizer')
    @patch('src.gui.WindowFinder.get_window_info')
    def test_running_session_blocks_resize(self, info, resizer):
        view = self.view()
        view.is_running = True
        view._resize_stove_window()
        resizer.assert_not_called()
        info.assert_not_called()

    @patch('src.gui.WindowResizer')
    @patch('src.gui.WindowFinder.get_window_info')
    def test_shared_window_is_blocked_and_verified_asynchronously(self, info, factory):
        view = self.view()
        info.return_value = Mock(class_name='GLFW30', process_name='EpicSeven.exe')
        other = self.view()
        view.app.sessions.append(other)
        other.is_running = True
        view._resize_stove_window()
        factory.assert_not_called()
        other.is_running = False
        factory.return_value.TARGET_SIZE = (1280, 720)
        factory.return_value.client_size.return_value = (1280, 720)
        view._resize_stove_window()
        factory.return_value.request.assert_called_once_with(123)
        self.assertTrue(view._stove_resize_pending)
        self.assertTrue(other._stove_resize_pending)
        view.root.after.call_args.args[1]()
        self.assertFalse(view._stove_resize_pending)
        self.assertFalse(other._stove_resize_pending)
        self.assertIn('1280×720 확인', view.stove_resize_status.config.call_args.kwargs['text'])

    def test_mismatch_has_bounded_verification_and_releases_controls(self):
        view = self.view()
        view._stove_resize_sessions = [view]
        view._stove_resize_pending = True
        resizer = Mock(TARGET_SIZE=(1280, 720))
        resizer.client_size.return_value = (1400, 800)
        view._verify_stove_size(resizer, 123, 7)
        view.root.after.assert_not_called()
        self.assertFalse(view._stove_resize_pending)
        self.assertIn('적용되지', view.stove_resize_status.config.call_args.kwargs['text'])

    def test_resize_pending_blocks_all_macro_starts(self):
        for method in ('_start_bot', '_start_reroll_bot', '_start_penguin_bot',
                       '_start_chaos_bot', '_start_event_bot'):
            with self.subTest(method=method):
                view = self.view()
                view._stove_resize_pending = True
                getattr(view, method)()
                self.assertFalse(view.is_running)

    def test_window_closed_during_verification_releases_controls(self):
        view = self.view()
        view._stove_resize_pending = True
        view._stove_resize_sessions = [view]
        resizer = Mock()
        resizer.client_size.side_effect = ValueError('게임 창이 닫혔습니다.')
        view._verify_stove_size(resizer, 123, 0)
        self.assertFalse(view._stove_resize_pending)
        view.root.after.assert_not_called()
