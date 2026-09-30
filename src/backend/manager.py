"""
Backend Factory and Selection Manager.
Supports explicit selection (ADB or Win32) and auto-detection.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
import logging

try:
    from backend.capture.win32 import Win32CaptureBackend
    from backend.input.win32 import Win32InputBackend
    from backend.capture.adb import AdbCaptureBackend
    from backend.input.adb import AdbInputBackend
    from finder.window_finder import WindowFinder, WindowInfo
    from core.device import UnifiedDevice
except ImportError:
    from .capture.win32 import Win32CaptureBackend
    from .input.win32 import Win32InputBackend
    from .capture.adb import AdbCaptureBackend
    from .input.adb import AdbInputBackend
    from ..finder.window_finder import WindowFinder, WindowInfo
    from ..core.device import UnifiedDevice

logger = logging.getLogger(__name__)


class BackendType(Enum):
    ADB = "adb"
    WIN32 = "win32"


class BackendFactory:
    """Creates and configures UnifiedDevice instances for ADB or Win32."""

    @staticmethod
    def create_win32_device(
        hwnd: Optional[int] = None,
        title_keywords: Optional[List[str]] = None,
    ) -> Optional[UnifiedDevice]:
        """
        Creates a UnifiedDevice configured for STOVE PC client via Win32.
        """
        if hwnd is None:
            win_info = WindowFinder.find_target_window(title_keywords=title_keywords)
            if not win_info:
                logger.error("STOVE Epic Seven window not found.")
                return None
            hwnd = win_info.hwnd

        capture_backend = Win32CaptureBackend(hwnd=hwnd, use_client_area=True)
        input_backend = Win32InputBackend(hwnd=hwnd)

        return UnifiedDevice(
            capture_backend=capture_backend,
            input_backend=input_backend,
            backend_name="Win32 (STOVE)",
        )

    @staticmethod
    def create_adb_device(
        device_id: Optional[str] = None,
        adb_path: str = "adb",
        adb_controller: Optional[object] = None,
    ) -> UnifiedDevice:
        """
        Creates a UnifiedDevice configured for Android App Player via ADB.
        """
        capture_backend = AdbCaptureBackend(
            adb_path=adb_path,
            device_id=device_id,
            adb_controller=adb_controller,
        )
        input_backend = AdbInputBackend(
            adb_path=adb_path,
            device_id=device_id,
            adb_controller=adb_controller,
        )

        return UnifiedDevice(
            capture_backend=capture_backend,
            input_backend=input_backend,
            backend_name="ADB (Emulator)",
        )

    @classmethod
    def list_available_targets(cls) -> Dict[str, Any]:
        """Lists running game windows and connected ADB targets."""
        found_windows = WindowFinder.find_all_windows()
        stove_candidates = [
            w for w in found_windows
            if any(t in w.title.lower() for t in ["epic", "seven", "에픽세븐", "stove"])
        ]
        return {
            "stove_windows": stove_candidates,
            "all_windows_count": len(found_windows),
        }
