"""
Win32 Input Backend using PostMessageW.
Sends background clicks and swipes to target window without moving the user's cursor
or stealing foreground focus.
"""
import ctypes
from ctypes import wintypes
import time
from typing import Optional
import logging

try:
    from .base import InputBackend
except ImportError:
    from backend.input.base import InputBackend

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# Window Messages
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

MK_LBUTTON = 0x0001


def _make_lparam(x: int, y: int) -> int:
    """Pack x and y into a 32-bit LPARAM."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class Win32InputBackend(InputBackend):
    """
    Win32 input backend using PostMessageW.
    """

    def __init__(self, hwnd: Optional[int] = None, auto_rebind: bool = True):
        self.hwnd = hwnd
        self.auto_rebind = auto_rebind

    def set_hwnd(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def is_connected(self) -> bool:
        if self.hwnd and user32.IsWindow(self.hwnd):
            return True
        if not self.auto_rebind:
            return False
        try:
            from finder.window_finder import WindowFinder
            win = WindowFinder.find_target_window()
            if win:
                self.hwnd = win.hwnd
                return True
        except Exception:
            pass
        return False

    def click(self, x: int, y: int, delay: float = 0.5) -> bool:
        """
        Sends background left click at physical coordinates (x, y) relative to client area.
        """
        if not self.is_connected():
            logger.error("Click failed: Target window HWND is invalid.")
            return False

        try:
            l_param = _make_lparam(x, y)
            
            # Post mouse move
            user32.PostMessageW(self.hwnd, WM_MOUSEMOVE, 0, l_param)
            time.sleep(0.01)

            # Button down
            user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, l_param)
            
            # Hold button briefly (30-50ms) to ensure game engine processes the touch
            time.sleep(0.04)

            # Button up
            user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, l_param)

            logger.debug(f"Win32 Click: ({x}, {y}) on hwnd=0x{self.hwnd:X}")
            if delay > 0:
                time.sleep(delay)
            return True

        except Exception as e:
            logger.error(f"Error during Win32 click: {e}")
            return False

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        delay: float = 0.5,
    ) -> bool:
        """
        Sends background drag/swipe from (x1, y1) to (x2, y2).
        """
        if not self.is_connected():
            logger.error("Swipe failed: Target window HWND is invalid.")
            return False

        try:
            duration_sec = max(0.05, duration_ms / 1000.0)
            steps = max(10, int(duration_sec * 60))  # approx 60Hz interpolation
            step_sleep = duration_sec / steps

            l_start = _make_lparam(x1, y1)
            user32.PostMessageW(self.hwnd, WM_MOUSEMOVE, 0, l_start)
            time.sleep(0.01)
            user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, l_start)
            time.sleep(0.02)

            for i in range(1, steps + 1):
                t = i / steps
                # Optional smooth step interpolation
                curr_x = int(x1 + (x2 - x1) * t)
                curr_y = int(y1 + (y2 - y1) * t)
                l_param = _make_lparam(curr_x, curr_y)
                user32.PostMessageW(self.hwnd, WM_MOUSEMOVE, MK_LBUTTON, l_param)
                time.sleep(step_sleep)

            l_end = _make_lparam(x2, y2)
            user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, l_end)

            logger.debug(
                f"Win32 Swipe: ({x1}, {y1}) -> ({x2}, {y2}), duration={duration_ms}ms"
            )
            if delay > 0:
                time.sleep(delay)
            return True

        except Exception as e:
            logger.error(f"Error during Win32 swipe: {e}")
            return False

    def press_key(self, key_code: int) -> bool:
        """
        Sends WM_KEYDOWN and WM_KEYUP for given virtual key code.
        """
        if not self.is_connected():
            return False

        try:
            user32.PostMessageW(self.hwnd, WM_KEYDOWN, key_code, 0)
            time.sleep(0.03)
            user32.PostMessageW(self.hwnd, WM_KEYUP, key_code, 0)
            return True
        except Exception as e:
            logger.error(f"Error sending key: {e}")
            return False
