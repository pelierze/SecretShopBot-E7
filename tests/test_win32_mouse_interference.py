"""Regression coverage for real mouse movement during a background click."""

import unittest
from unittest.mock import Mock, patch

from src.backend.input import win32


class MouseInterferenceTest(unittest.TestCase):
    def test_mouse_move_during_hold_does_not_leave_release_at_user_position(self):
        cursor = [0, 0]
        button_positions = []

        def dispatch(hwnd, message, flags, coordinates):
            if message == win32.WM_MOUSEMOVE:
                cursor[:] = [coordinates & 0xFFFF, (coordinates >> 16) & 0xFFFF]
            elif message in (win32.WM_LBUTTONDOWN, win32.WM_LBUTTONUP):
                button_positions.append(tuple(cursor))
            return 1

        def user_movement_during_hold(seconds):
            cursor[:] = [750, 350]

        api = Mock()
        api.IsWindow.return_value = 1
        api.PostMessageW.side_effect = dispatch
        backend = win32.Win32InputBackend(hwnd=123, auto_rebind=False)
        with patch.object(win32, 'user32', api), patch.object(
            win32.time, 'sleep', side_effect=user_movement_during_hold
        ) as sleep:
            self.assertTrue(backend.click(220, 514, delay=0))

        self.assertEqual(button_positions, [(220, 514), (220, 514)])
        sleep.assert_called_once_with(0.04)
        api.SetCursorPos.assert_not_called()
        api.SetForegroundWindow.assert_not_called()
        api.SendInput.assert_not_called()

    def test_coordinate_refresh_preserves_held_button_state_and_target_window(self):
        api = Mock()
        api.IsWindow.return_value = 1
        backend = win32.Win32InputBackend(hwnd=123, auto_rebind=False)
        with patch.object(win32, 'user32', api), patch.object(win32.time, 'sleep'):
            self.assertTrue(backend.click(1085, 659, delay=0))

        coordinates = win32._make_lparam(1085, 659)
        self.assertEqual(api.PostMessageW.call_args_list, [
            unittest.mock.call(123, win32.WM_MOUSEMOVE, 0, coordinates),
            unittest.mock.call(123, win32.WM_LBUTTONDOWN, win32.MK_LBUTTON, coordinates),
            unittest.mock.call(123, win32.WM_MOUSEMOVE, win32.MK_LBUTTON, coordinates),
            unittest.mock.call(123, win32.WM_LBUTTONUP, 0, coordinates),
        ])


if __name__ == '__main__':
    unittest.main()
