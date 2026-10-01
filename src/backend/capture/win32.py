"""
Win32 Capture Backend using pure ctypes and GDI/PrintWindow.
Captures windows in the background without requiring foreground activation.
"""
import ctypes
from ctypes import wintypes
import threading
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


for library, name, args, result in (
    (user32, 'GetDC', [wintypes.HWND], wintypes.HDC),
    (user32, 'GetWindowDC', [wintypes.HWND], wintypes.HDC),
    (user32, 'ReleaseDC', [wintypes.HWND, wintypes.HDC], ctypes.c_int),
    (user32, 'PrintWindow', [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
    (gdi32, 'CreateCompatibleDC', [wintypes.HDC], wintypes.HDC),
    (gdi32, 'CreateCompatibleBitmap', [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HANDLE),
    (gdi32, 'SelectObject', [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
    (gdi32, 'DeleteObject', [wintypes.HANDLE], wintypes.BOOL),
    (gdi32, 'DeleteDC', [wintypes.HDC], wintypes.BOOL),
    (gdi32, 'BitBlt', [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
    (gdi32, 'GetDIBits', [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT], ctypes.c_int),
):
    function = getattr(library, name)
    function.argtypes, function.restype = args, result


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
        self._lock = threading.RLock()
        self._resource_key = None
        self._hdc_mem = None
        self._hbmp = None
        self._h_old = None
        self._buffer = None

    def set_hwnd(self, hwnd: int) -> None:
        with self._lock:
            if hwnd != self.hwnd:
                self.close()
                self._print_window_flag = PW_RENDERFULLCONTENT
            self.hwnd = hwnd

    def close(self) -> None:
        with self._lock:
            if self._hdc_mem and self._h_old:
                gdi32.SelectObject(self._hdc_mem, self._h_old)
            if self._hbmp:
                gdi32.DeleteObject(self._hbmp)
            if self._hdc_mem:
                gdi32.DeleteDC(self._hdc_mem)
            self._resource_key = None
            self._hdc_mem = self._hbmp = self._h_old = self._buffer = None

    def _prepare_resources(self, hdc_window, width, height):
        key = (self.hwnd, self.use_client_area, width, height)
        if self._resource_key == key:
            return
        self.close()
        try:
            self._hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
            if not self._hdc_mem:
                raise OSError('CreateCompatibleDC failed')
            self._hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
            if not self._hbmp:
                raise OSError('CreateCompatibleBitmap failed')
            self._h_old = gdi32.SelectObject(self._hdc_mem, self._hbmp)
            if not self._h_old or self._h_old == ctypes.c_void_p(-1).value:
                self._h_old = None
                raise OSError('SelectObject failed')
            self._buffer = (ctypes.c_char * (width * height * 4))()
            self._resource_key = key
        except Exception:
            self.close()
            raise

    def is_connected(self) -> bool:
        if self.hwnd and user32.IsWindow(self.hwnd):
            return True
        if not self.auto_rebind:
            return False
        # Attempt auto-rebind
        win = WindowFinder.find_target_window()
        if win:
            self.set_hwnd(win.hwnd)
            logger.info("Auto-rebound HWND to 0x%X", self.hwnd)
            return True
        return False

    def get_raw_size(self) -> Tuple[int, int]:
        if not self.is_connected():
            return 0, 0
        _, _, c_size = WindowFinder.get_rects(self.hwnd)
        return c_size

    def capture(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._capture()

    def _capture(self) -> Optional[np.ndarray]:
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

        try:
            self._prepare_resources(hdc_window, width, height)
            hdc_mem, hbmp = self._hdc_mem, self._hbmp
            gdi32.SelectObject(hdc_mem, hbmp)
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
                if not gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY):
                    raise OSError('PrintWindow and BitBlt failed')

            # Setup Bitmap header for top-down 32bpp BGRA
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # negative means top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            bmi.bmiHeader.biSizeImage = width * height * 4

            buffer = self._buffer
            # GetDIBits requires the bitmap to be deselected from the DC.
            gdi32.SelectObject(hdc_mem, self._h_old)
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
            # Own the pixels even for 1x1 captures, where ascontiguousarray can
            # otherwise return a view into the next capture's reusable buffer.
            img_bgr = img_bgra[:, :, :3].copy(order='C')
            return img_bgr

        except Exception as e:
            logger.error(f"Exception during Win32 capture: {e}")
            return None

        finally:
            user32.ReleaseDC(self.hwnd, hdc_window)
