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
    def _scan_black_edge(cls, frame, *, columns, reverse, limit):
        """Scan 32-pixel strips, preserving the original two-stage average.

        The center of the frame is never inspected by the legacy edge scan.
        Stop at its first non-black strip pixel without a full-frame float array.
        """
        length = frame.shape[1 if columns else 0]
        scanned = 0
        while scanned < limit:
            count = min(32, limit - scanned)
            start = length - scanned - count if reverse else scanned
            strip = frame[:, start:start + count] if columns else frame[start:start + count]
            gray = strip if strip.ndim == 2 else np.mean(strip, axis=2)
            means = np.mean(gray, axis=0 if columns else 1)
            if reverse:
                means = means[::-1]
            non_black = np.flatnonzero(~(means < cls.BLACK_BAR_THRESHOLD))
            if non_black.size:
                return scanned + int(non_black[0])
            scanned += count
        return scanned

    @classmethod
    def _detect_pillarbox(cls, frame: np.ndarray) -> GameArea:
        """Detect left and right black bars."""
        h, w = frame.shape[:2]
        left = cls._scan_black_edge(frame, columns=True, reverse=False, limit=w // 3)
        right = w - 1 - cls._scan_black_edge(
            frame, columns=True, reverse=True, limit=w - 1 - (2 * w) // 3)

        detected_w = right - left + 1
        # Validate detected width
        if detected_w > w // 2:
            return GameArea(left, 0, detected_w, h)
        return cls._calculate_centered_16_9(w, h)

    @classmethod
    def _detect_letterbox(cls, frame: np.ndarray) -> GameArea:
        """Detect top and bottom black bars."""
        h, w = frame.shape[:2]
        top = cls._scan_black_edge(frame, columns=False, reverse=False, limit=h // 3)
        bottom = h - 1 - cls._scan_black_edge(
            frame, columns=False, reverse=True, limit=h - 1 - (2 * h) // 3)

        detected_h = bottom - top + 1
        if detected_h > h // 2:
            return GameArea(0, top, w, detected_h)
        return cls._calculate_centered_16_9(w, h)
