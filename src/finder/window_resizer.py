"""Resize the client area without moving the cursor or activating the window."""
import ctypes
from ctypes import wintypes


class WindowResizer:
    TARGET_SIZE = (1280, 720)
    # Keep position, stacking order and focus; queue work on the target thread.
    FLAGS = 0x0002 | 0x0004 | 0x0010 | 0x0200 | 0x4000

    def __init__(self):
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        for name in ('IsWindow', 'IsIconic', 'IsZoomed'):
            function = getattr(self.api, name)
            function.argtypes = [wintypes.HWND]
            function.restype = wintypes.BOOL
        for name in ('GetClientRect', 'GetWindowRect'):
            function = getattr(self.api, name)
            function.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            function.restype = wintypes.BOOL
        self.api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.api.GetWindowLongW.restype = wintypes.LONG
        self.api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, wintypes.UINT]
        self.api.SetWindowPos.restype = wintypes.BOOL

    def client_size(self, hwnd):
        if not self.api.IsWindow(hwnd):
            raise ValueError('게임 창이 닫혔습니다. 창을 다시 검색하세요.')
        rect = wintypes.RECT()
        if not self.api.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return rect.right - rect.left, rect.bottom - rect.top

    def request(self, hwnd):
        width, height = self.client_size(hwnd)
        if self.api.IsIconic(hwnd) or self.api.IsZoomed(hwnd):
            raise ValueError('게임 창의 최소화·최대화를 해제한 뒤 사용하세요.')
        if self.api.GetWindowLongW(hwnd, -16) & 0x00C00000 != 0x00C00000:
            raise ValueError('게임을 일반 창 모드로 전환한 뒤 사용하세요.')
        if width <= 0 or height <= 0:
            raise ValueError('게임 화면 크기를 확인할 수 없습니다.')
        if (width, height) == self.TARGET_SIZE:
            return
        outer = wintypes.RECT()
        if not self.api.GetWindowRect(hwnd, ctypes.byref(outer)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Measured physical-pixel frame margins account for the current DPI and
        # the game's own decorations without changing its window style.
        target_w = 1280 + (outer.right - outer.left - width)
        target_h = 720 + (outer.bottom - outer.top - height)
        if target_w < 1280 or target_h < 720:
            raise ValueError('게임 창 테두리 크기를 확인할 수 없습니다.')
        if not self.api.SetWindowPos(hwnd, None, 0, 0, target_w, target_h, self.FLAGS):
            raise ctypes.WinError(ctypes.get_last_error())
