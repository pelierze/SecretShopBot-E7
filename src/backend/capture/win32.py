"""
Win32 Capture Backend using pure ctypes and GDI/PrintWindow.
Captures windows in the background without requiring foreground activation.
"""
import ctypes
from ctypes import wintypes
import time
from typing import Optional, Tuple
import logging
import numpy as np

try:
    from .base import CaptureBackend
except ImportError:
    from backend.capture.base import CaptureBackend

try:
    from ...finder.window_finder import WindowFinder
except (ImportError, ValueError):
    try:
        from finder.window_finder import WindowFinder
    except (ImportError, ValueError):
        from test.finder.window_finder import WindowFinder

logger = logging.getLogger(__name__)

# Win32 API Functions and Constants
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_DEFAULT = 0x00000000
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

DIB_RGB_COLORS = 0
BI_RGB = 0
SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class Win32CaptureBackend(CaptureBackend):
    """
    Win32 implementation of CaptureBackend.
    Captures window frames using PrintWindow / GDI.
    """

    def __init__(self, hwnd: Optional[int] = None, use_client_area: bool = True, auto_rebind: bool = True):
        """
        Args:
            hwnd: Window handle. If None, can be set later or resolved via WindowFinder.
            use_client_area: If True, captures client area only.
            auto_rebind: If True, automatically searches for target window when hwnd is invalid.
        """
        self.hwnd = hwnd
        self.use_client_area = use_client_area
        self.auto_rebind = auto_rebind
        self._last_size: Tuple[int, int] = (0, 0)
        self._print_window_flag = PW_RENDERFULLCONTENT

    def set_hwnd(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def is_connected(self) -> bool:
        if self.hwnd and user32.IsWindow(self.hwnd):
            return True
        if not self.auto_rebind:
            return False
        # Attempt auto-rebind
        win = WindowFinder.find_target_window()
        if win:
            self.hwnd = win.hwnd
            logger.info("Auto-rebound HWND to 0x%X", self.hwnd)
            return True
        return False

    def get_raw_size(self) -> Tuple[int, int]:
        if not self.is_connected():
            return 0, 0
        _, _, c_size = WindowFinder.get_rects(self.hwnd)
        return c_size

    def capture(self) -> Optional[np.ndarray]:
        """
        Captures the window and returns a BGR numpy array.
        """
        WindowFinder.ensure_default_desktop()
        if not self.is_connected():
            logger.error("Capture failed: Invalid or missing window handle (HWND).")
            return None

        if user32.IsIconic(self.hwnd):
            logger.warning("Capture warning: Target window is minimized.")
            return None

        w_rect, c_rect, c_size = WindowFinder.get_rects(self.hwnd)
        if self.use_client_area:
            width, height = c_size
        else:
            width = w_rect[2] - w_rect[0]
            height = w_rect[3] - w_rect[1]

        if width <= 0 or height <= 0:
            logger.error(f"Capture failed: Invalid window dimensions ({width}x{height}).")
            return None

        self._last_size = (width, height)

        # Get DCs
        hdc_window = user32.GetWindowDC(self.hwnd) if not self.use_client_area else user32.GetDC(self.hwnd)
        if not hdc_window:
            logger.error("Capture failed: Could not get Window DC.")
            return None

        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        h_old = gdi32.SelectObject(hdc_mem, hbmp)

        try:
            # First attempt: PrintWindow with PW_RENDERFULLCONTENT (supports hardware acceleration on Win 8.1+)
            flag = self._print_window_flag | (PW_CLIENTONLY if self.use_client_area else 0)
            res = user32.PrintWindow(self.hwnd, hdc_mem, flag)
            
            # If PrintWindow with full content fails, try standard PW_CLIENTONLY or PW_DEFAULT
            if not res and self._print_window_flag == PW_RENDERFULLCONTENT:
                self._print_window_flag = PW_DEFAULT
                flag = self._print_window_flag | (PW_CLIENTONLY if self.use_client_area else 0)
                res = user32.PrintWindow(self.hwnd, hdc_mem, flag)

            if not res:
                # Fallback to BitBlt
                gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY)

            # Setup Bitmap header for top-down 32bpp BGRA
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # negative means top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            bmi.bmiHeader.biSizeImage = width * height * 4

            buffer = (ctypes.c_char * (width * height * 4))()
            scan_lines = gdi32.GetDIBits(
                hdc_mem,
                hbmp,
                0,
                height,
                ctypes.byref(buffer),
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
            )

            if scan_lines != height:
                logger.error(f"GetDIBits failed: read {scan_lines}/{height} lines.")
                return None

            # Convert to numpy array (BGRA)
            img_bgra = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4))
            
            # Extract BGR (discard alpha)
            img_bgr = np.ascontiguousarray(img_bgra[:, :, :3])
            return img_bgr

        except Exception as e:
            logger.error(f"Exception during Win32 capture: {e}")
            return None

        finally:
            gdi32.SelectObject(hdc_mem, h_old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            if self.use_client_area:
                user32.ReleaseDC(self.hwnd, hdc_window)
            else:
                user32.ReleaseDC(self.hwnd, hdc_window)
