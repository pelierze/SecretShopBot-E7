"""
ADB Capture Backend implementation.
Wraps screencap or existing ADBController.
"""
import subprocess
import os
from typing import Optional, Tuple
import logging
import cv2
import numpy as np

try:
    from .base import CaptureBackend
except ImportError:
    from backend.capture.base import CaptureBackend

logger = logging.getLogger(__name__)


class AdbCaptureBackend(CaptureBackend):
    """Capture backend that fetches frames from an Android device/emulator via ADB."""

    def __init__(
        self,
        adb_path: str = "adb",
        device_id: Optional[str] = None,
        adb_controller: Optional[object] = None,
    ):
        self.adb_path = adb_path
        self.device_id = device_id
        self.adb_controller = adb_controller
        self._raw_size: Tuple[int, int] = (1280, 720)

    def is_connected(self) -> bool:
        if self.adb_controller is not None:
            if hasattr(self.adb_controller, "device_id"):
                return bool(self.adb_controller.device_id)
            return True
        return bool(self.device_id)

    def get_raw_size(self) -> Tuple[int, int]:
        return self._raw_size

    def _run_adb(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.extend(args)

        kwargs = {"capture_output": True}
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        return subprocess.run(cmd, **kwargs)

    def capture(self) -> Optional[np.ndarray]:
        # Delegate to ADBController if present
        if self.adb_controller is not None and hasattr(self.adb_controller, "capture_frame"):
            frame = self.adb_controller.capture_frame()
            if frame is not None:
                h, w = frame.shape[:2]
                self._raw_size = (w, h)
                return frame

        # Standalone screencap
        try:
            res = self._run_adb(["exec-out", "screencap", "-p"])
            if res.returncode != 0 or not res.stdout:
                logger.error("ADB screencap command failed.")
                return None

            img = cv2.imdecode(np.frombuffer(res.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                h, w = img.shape[:2]
                self._raw_size = (w, h)
            return img
        except Exception as e:
            logger.error(f"Error during ADB capture: {e}")
            return None
