"""
Unified Device abstraction:
Bridges Automation Core with underlying Backends (ADB or Win32).
All capture outputs and input coordinates are strictly in 1280x720 logical space.
"""
from typing import Optional, Tuple
from pathlib import Path
import logging
import cv2
import numpy as np

try:
    from backend.capture.base import CaptureBackend
    from backend.input.base import InputBackend
    from display.coordinate_mapper import CoordinateMapper, Anchor
    from display.normalizer import ResolutionNormalizer
    from display.game_area import GameArea
except ImportError:
    from ..backend.capture.base import CaptureBackend
    from ..backend.input.base import InputBackend
    from ..display.coordinate_mapper import CoordinateMapper, Anchor
    from ..display.normalizer import ResolutionNormalizer
    from ..display.game_area import GameArea

logger = logging.getLogger(__name__)


class UnifiedDevice:
    """
    Drop-in unified device interface for automation logic.
    Provides identical API to ADBController (tap, swipe, capture_frame)
    while transparently handling resolution normalization and coordinate mapping
    for Win32 and ADB backends.
    """

    def __init__(
        self,
        capture_backend: CaptureBackend,
        input_backend: InputBackend,
        backend_name: str = "win32",
    ):
        self.capture_backend = capture_backend
        self.input_backend = input_backend
        self.backend_name = backend_name

        raw_size = getattr(self.capture_backend, "get_raw_size", lambda: None)()
        if raw_size and raw_size[0] > 0 and raw_size[1] > 0:
            self.coordinate_mapper = CoordinateMapper(
                game_offset_x=0,
                game_offset_y=0,
                game_width=raw_size[0],
                game_height=raw_size[1],
                client_width=raw_size[0],
                client_height=raw_size[1],
            )
        else:
            self.coordinate_mapper = CoordinateMapper()
        self.normalizer = ResolutionNormalizer(self.coordinate_mapper)

        self._last_raw_frame: Optional[np.ndarray] = None
        self._last_normalized_frame: Optional[np.ndarray] = None
        self._last_game_area: Optional[GameArea] = None
        self.device_id = f"stove_{self.backend_name}"
        self.input_profile = "win32"

    def get_screen_size(self) -> Tuple[int, int]:
        """Returns standard 1280x720 logical screen size."""
        return (1280, 720)

    def is_connected(self) -> bool:
        return self.capture_backend.is_connected() and self.input_backend.is_connected()

    def connect(self, *args, **kwargs) -> bool:
        """Compatibility method for ADBController."""
        return self.is_connected()

    def connect_device(self, *args, **kwargs) -> bool:
        """Compatibility method for ADBController."""
        return self.is_connected()

    def test_connection(self) -> Tuple[bool, str]:
        if not self.is_connected():
            return False, f"[{self.backend_name}] 백엔드에 연결되어 있지 않습니다."
        frame = self.capture_backend.capture()
        if frame is None or frame.size == 0:
            return False, f"[{self.backend_name}] 화면 캡처 실패."
        return True, f"[{self.backend_name}] 연결 및 캡처 성공."

    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Captures a frame and normalizes it to exactly 1280x720 logical resolution.
        Updates internal CoordinateMapper with current scaling and letterbox offsets.

        Returns:
            np.ndarray: 1280x720 BGR image, or None on failure.
        """
        raw_frame = self.capture_backend.capture()
        if raw_frame is None or raw_frame.size == 0:
            return None

        self._last_raw_frame = raw_frame
        normalized, game_area = self.normalizer.normalize(raw_frame)
        self._last_normalized_frame = normalized
        self._last_game_area = game_area
        return normalized

    def capture(self) -> Optional[np.ndarray]:
        """Alias for capture_frame()."""
        return self.capture_frame()

    def screenshot(self, save_path: str) -> bool:
        """Saves current normalized 1280x720 frame to disk safely across OS platforms."""
        frame = self.capture_frame()
        if frame is None or frame.size == 0:
            return False
        try:
            target_path = Path(save_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            ext = target_path.suffix or ".png"
            success, encoded = cv2.imencode(ext, frame)
            if not success:
                logger.error(f"Failed to encode screenshot to {ext} for {save_path}")
                return False
            target_path.write_bytes(encoded.tobytes())
            return True
        except Exception as e:
            logger.error(f"Failed to save screenshot to {save_path}: {e}")
            return False

    def tap(self, logical_x: int, logical_y: int, delay: float = 0.5) -> bool:
        """
        Sends click/tap at 1280x720 logical coordinates.
        Automatically converts to physical coordinates using CoordinateMapper.
        """
        phys_x, phys_y = self.coordinate_mapper.logical_to_physical(logical_x, logical_y)
        logger.debug(
            f"[{self.backend_name}] Tap logical({logical_x}, {logical_y}) -> physical({phys_x}, {phys_y})"
        )
        return self.input_backend.click(phys_x, phys_y, delay=delay)

    def click(self, logical_x: int, logical_y: int, delay: float = 0.5) -> bool:
        """Alias for tap()."""
        return self.tap(logical_x, logical_y, delay=delay)

    def tap_anchor(self, anchor: Anchor, delta_x: int, delta_y: int, delay: float = 0.5) -> bool:
        """
        Tap relative to a screen anchor. Useful for UI elements in ultra-wide modes.
        """
        phys_x, phys_y = self.coordinate_mapper.anchor_to_physical(anchor, delta_x, delta_y)
        return self.input_backend.click(phys_x, phys_y, delay=delay)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int = 300,
        delay: float = 0.5,
    ) -> bool:
        """
        Sends swipe from logical (x1, y1) to logical (x2, y2).
        Automatically converts endpoints to physical coordinates.
        """
        px1, py1 = self.coordinate_mapper.logical_to_physical(x1, y1)
        px2, py2 = self.coordinate_mapper.logical_to_physical(x2, y2)
        logger.debug(
            f"[{self.backend_name}] Swipe logical({x1}, {y1})->({x2}, {y2}) -> physical({px1}, {py1})->({px2}, {py2})"
        )
        return self.input_backend.swipe(px1, py1, px2, py2, duration_ms=duration, delay=delay)

    def close(self) -> None:
        self.capture_backend.close()
        self.input_backend.close()

    def disconnect(self) -> None:
        """Alias for close() to maintain full ADBController interface compatibility."""
        self.close()

    def set_input_profile(self, profile: Optional[str] = None) -> None:
        """No-op compatibility stub for ADB input profile."""
        pass
