"""
ADB Input Backend implementation.
Wraps tap/swipe commands or existing ADBController.
"""
import subprocess
import os
import time
from typing import Optional
import logging

try:
    from .base import InputBackend
except ImportError:
    from backend.input.base import InputBackend

logger = logging.getLogger(__name__)


class AdbInputBackend(InputBackend):
    """Input backend that sends tap/swipe commands via ADB."""

    def __init__(
        self,
        adb_path: str = "adb",
        device_id: Optional[str] = None,
        adb_controller: Optional[object] = None,
    ):
        self.adb_path = adb_path
        self.device_id = device_id
        self.adb_controller = adb_controller

    def is_connected(self) -> bool:
        if self.adb_controller is not None:
            if hasattr(self.adb_controller, "device_id"):
                return bool(self.adb_controller.device_id)
            return True
        return bool(self.device_id)

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

    def click(self, x: int, y: int, delay: float = 0.5) -> bool:
        if self.adb_controller is not None and hasattr(self.adb_controller, "tap"):
            return bool(self.adb_controller.tap(x, y, delay=delay))

        try:
            res = self._run_adb(["shell", "input", "tap", str(x), str(y)])
            if res.returncode == 0:
                logger.debug(f"ADB Tap: ({x}, {y})")
                if delay > 0:
                    time.sleep(delay)
                return True
            logger.error(f"ADB tap failed with code {res.returncode}")
            return False
        except Exception as e:
            logger.error(f"Error during ADB tap: {e}")
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
        if self.adb_controller is not None and hasattr(self.adb_controller, "swipe"):
            return bool(self.adb_controller.swipe(x1, y1, x2, y2, duration=duration_ms, delay=delay))

        try:
            res = self._run_adb(
                ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
            )
            if res.returncode == 0:
                logger.debug(f"ADB Swipe: ({x1}, {y1}) -> ({x2}, {y2}), duration={duration_ms}ms")
                if delay > 0:
                    time.sleep(delay)
                return True
            logger.error(f"ADB swipe failed with code {res.returncode}")
            return False
        except Exception as e:
            logger.error(f"Error during ADB swipe: {e}")
            return False
