"""
Coordinate Mapper: Bidirectional mapping between Logical (1280x720) and Physical coordinates,
accounting for letterboxing, window scaling, and anchors.
"""
from enum import Enum
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class Anchor(Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"


class CoordinateMapper:
    """
    Handles translation between 1280x720 logical coordinates and physical coordinates.
    """

    LOGICAL_WIDTH = 1280
    LOGICAL_HEIGHT = 720

    def __init__(
        self,
        game_offset_x: int = 0,
        game_offset_y: int = 0,
        game_width: int = 1280,
        game_height: int = 720,
        client_width: Optional[int] = None,
        client_height: Optional[int] = None,
    ):
        """
        Args:
            game_offset_x: Left offset of the game render area within the client window
            game_offset_y: Top offset of the game render area within the client window
            game_width: Rendered width of the game area
            game_height: Rendered height of the game area
            client_width: Total client window width (for clamping)
            client_height: Total client window height (for clamping)
        """
        self.game_offset_x = game_offset_x
        self.game_offset_y = game_offset_y
        self.game_width = max(1, game_width)
        self.game_height = max(1, game_height)
        self.client_width = client_width if client_width is not None else (game_offset_x + game_width)
        self.client_height = client_height if client_height is not None else (game_offset_y + game_height)

        self._update_scales()

    def _update_scales(self) -> None:
        self.scale_x = self.game_width / self.LOGICAL_WIDTH
        self.scale_y = self.game_height / self.LOGICAL_HEIGHT

    def update_layout(
        self,
        offset_x: int,
        offset_y: int,
        game_width: int,
        game_height: int,
        client_width: Optional[int] = None,
        client_height: Optional[int] = None,
    ) -> None:
        """Update mapping parameters when window size or game area changes."""
        self.game_offset_x = offset_x
        self.game_offset_y = offset_y
        self.game_width = max(1, game_width)
        self.game_height = max(1, game_height)
        if client_width is not None:
            self.client_width = client_width
        if client_height is not None:
            self.client_height = client_height
        self._update_scales()

    def logical_to_physical(self, log_x: int, log_y: int, clamp: bool = True) -> Tuple[int, int]:
        """
        Convert logical (1280x720) coordinates to physical window client coordinates.
        """
        phys_x = int(round(self.game_offset_x + log_x * self.scale_x))
        phys_y = int(round(self.game_offset_y + log_y * self.scale_y))

        if clamp:
            phys_x = max(0, min(phys_x, self.client_width - 1))
            phys_y = max(0, min(phys_y, self.client_height - 1))

        return phys_x, phys_y

    def physical_to_logical(self, phys_x: int, phys_y: int) -> Tuple[int, int]:
        """
        Convert physical window client coordinates to logical (1280x720) coordinates.
        """
        rel_x = phys_x - self.game_offset_x
        rel_y = phys_y - self.game_offset_y

        log_x = int(round(rel_x / self.scale_x))
        log_y = int(round(rel_y / self.scale_y))

        # Clamp to logical boundary
        log_x = max(0, min(log_x, self.LOGICAL_WIDTH))
        log_y = max(0, min(log_y, self.LOGICAL_HEIGHT))

        return log_x, log_y

    def anchor_to_physical(
        self,
        anchor: Anchor,
        delta_x: int,
        delta_y: int,
    ) -> Tuple[int, int]:
        """
        Calculate physical position relative to an anchor point.
        Useful when UI elements are pinned to screen corners in widescreen modes.

        delta_x and delta_y are in logical pixel scale.
        """
        scaled_dx = int(round(delta_x * self.scale_x))
        scaled_dy = int(round(delta_y * self.scale_y))

        if anchor == Anchor.TOP_LEFT:
            base_x = self.game_offset_x
            base_y = self.game_offset_y
        elif anchor == Anchor.TOP_RIGHT:
            base_x = self.game_offset_x + self.game_width
            base_y = self.game_offset_y
        elif anchor == Anchor.BOTTOM_LEFT:
            base_x = self.game_offset_x
            base_y = self.game_offset_y + self.game_height
        elif anchor == Anchor.BOTTOM_RIGHT:
            base_x = self.game_offset_x + self.game_width
            base_y = self.game_offset_y + self.game_height
        elif anchor == Anchor.CENTER:
            base_x = self.game_offset_x + self.game_width // 2
            base_y = self.game_offset_y + self.game_height // 2
        else:
            base_x = self.game_offset_x
            base_y = self.game_offset_y

        return (base_x + scaled_dx, base_y + scaled_dy)
