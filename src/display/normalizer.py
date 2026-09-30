"""
Resolution Normalizer: Crops game area and resizes frames to standard 1280x720.
"""
from typing import Tuple, Optional
import cv2
import numpy as np
import logging

from .game_area import GameArea, GameAreaDetector
from .coordinate_mapper import CoordinateMapper

logger = logging.getLogger(__name__)


class ResolutionNormalizer:
    """Normalizes any capture frame to the logical standard resolution of 1280x720."""

    TARGET_WIDTH = 1280
    TARGET_HEIGHT = 720

    def __init__(self, coordinate_mapper: Optional[CoordinateMapper] = None):
        self.coordinate_mapper = coordinate_mapper
        self.last_game_area: Optional[GameArea] = None

    def normalize(
        self,
        raw_frame: np.ndarray,
        auto_detect_bars: bool = True,
    ) -> Tuple[np.ndarray, GameArea]:
        """
        Takes raw captured frame, trims letterbox/pillarbox if present,
        and rescales to standard 1280x720.

        Args:
            raw_frame: Raw captured BGR image
            auto_detect_bars: Whether to scan for black bars

        Returns:
            Tuple[np.ndarray, GameArea]: (normalized 1280x720 image, detected GameArea)
        """
        if raw_frame is None or raw_frame.size == 0:
            raise ValueError("Input frame is empty or None")

        raw_h, raw_w = raw_frame.shape[:2]

        # Detect game render area
        game_area = GameAreaDetector.detect(raw_frame, auto_detect_black_bars=auto_detect_bars)
        self.last_game_area = game_area

        # Update CoordinateMapper if bound
        if self.coordinate_mapper is not None:
            self.coordinate_mapper.update_layout(
                offset_x=game_area.x,
                offset_y=game_area.y,
                game_width=game_area.width,
                game_height=game_area.height,
                client_width=raw_w,
                client_height=raw_h,
            )

        # Crop if needed
        if game_area.x != 0 or game_area.y != 0 or game_area.width != raw_w or game_area.height != raw_h:
            cropped = raw_frame[
                game_area.y : game_area.y + game_area.height,
                game_area.x : game_area.x + game_area.width,
            ]
        else:
            cropped = raw_frame

        # Resize to standard 1280x720
        curr_h, curr_w = cropped.shape[:2]
        if curr_w == self.TARGET_WIDTH and curr_h == self.TARGET_HEIGHT:
            return cropped, game_area

        # Choose optimal interpolation
        interpolation = cv2.INTER_AREA if (curr_w > self.TARGET_WIDTH or curr_h > self.TARGET_HEIGHT) else cv2.INTER_LINEAR
        normalized = cv2.resize(cropped, (self.TARGET_WIDTH, self.TARGET_HEIGHT), interpolation=interpolation)

        return normalized, game_area
