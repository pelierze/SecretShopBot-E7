"""
Game Area Detector: Distinguishes Client Area from Game Rendering Area,
detecting and trimming Letterbox / Pillarbox.
"""
from dataclasses import dataclass
from typing import Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class GameArea:
    """Bounding box of the actual game rendering area within the raw frame."""
    x: int
    y: int
    width: int
    height: int

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    @property
    def aspect_ratio(self) -> float:
        return self.width / max(1, self.height)


class GameAreaDetector:
    """Detects active game rendering region, stripping letterbox/pillarbox bars."""

    BLACK_BAR_THRESHOLD = 15  # Max average intensity to consider black bar
    EPSILON = 0.01

    @classmethod
    def detect(cls, frame: np.ndarray, auto_detect_black_bars: bool = True) -> GameArea:
        """
        Determines the GameArea for the given frame.

        Args:
            frame: Raw BGR frame
            auto_detect_black_bars: Whether to scan for black borders if non-16:9

        Returns:
            GameArea: (x, y, width, height) of the active game area.
        """
        if frame is None or frame.size == 0:
            return GameArea(0, 0, 1280, 720)

        h, w = frame.shape[:2]
        target_ratio = 16.0 / 9.0
        current_ratio = w / max(1, h)

        # If already exactly or nearly 16:9 (within 1% tolerance)
        if abs(current_ratio - target_ratio) < cls.EPSILON:
            return GameArea(0, 0, w, h)

        if not auto_detect_black_bars:
            # Simple centered 16:9 crop
            return cls._calculate_centered_16_9(w, h)

        # Dynamic detection: Pillarbox (wider than 16:9) or Letterbox (taller than 16:9)
        if current_ratio > target_ratio:
            # Pillarbox: black bars on left/right
            area = cls._detect_pillarbox(frame)
        else:
            # Letterbox: black bars on top/bottom
            area = cls._detect_letterbox(frame)

        return area

    @classmethod
    def _calculate_centered_16_9(cls, w: int, h: int) -> GameArea:
        target_ratio = 16.0 / 9.0
        current_ratio = w / h

        if current_ratio > target_ratio:
            # Pillarbox (cut sides)
            game_w = int(h * target_ratio)
            game_h = h
            offset_x = (w - game_w) // 2
            offset_y = 0
        else:
            # Letterbox (cut top/bottom)
            game_w = w
            game_h = int(w / target_ratio)
            offset_x = 0
            offset_y = (h - game_h) // 2

        return GameArea(offset_x, offset_y, game_w, game_h)

    @classmethod
    def _detect_pillarbox(cls, frame: np.ndarray) -> GameArea:
        """Detect left and right black bars."""
        h, w = frame.shape[:2]

        # Average along vertical axis -> 1D profile of width
        col_mean = np.mean(frame, axis=0 if frame.ndim == 2 else (0, 2))

        left = 0
        while left < w // 3 and col_mean[left] < cls.BLACK_BAR_THRESHOLD:
            left += 1

        right = w - 1
        while right > (2 * w) // 3 and col_mean[right] < cls.BLACK_BAR_THRESHOLD:
            right -= 1

        detected_w = right - left + 1
        # Validate detected width
        if detected_w > w // 2:
            return GameArea(left, 0, detected_w, h)
        return cls._calculate_centered_16_9(w, h)

    @classmethod
    def _detect_letterbox(cls, frame: np.ndarray) -> GameArea:
        """Detect top and bottom black bars."""
        h, w = frame.shape[:2]

        row_mean = np.mean(frame, axis=1 if frame.ndim == 2 else (1, 2))

        top = 0
        while top < h // 3 and row_mean[top] < cls.BLACK_BAR_THRESHOLD:
            top += 1

        bottom = h - 1
        while bottom > (2 * h) // 3 and row_mean[bottom] < cls.BLACK_BAR_THRESHOLD:
            bottom -= 1

        detected_h = bottom - top + 1
        if detected_h > h // 2:
            return GameArea(0, top, w, detected_h)
        return cls._calculate_centered_16_9(w, h)
