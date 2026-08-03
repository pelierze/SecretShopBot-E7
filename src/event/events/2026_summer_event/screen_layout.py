"""Resolution-aware screen regions for the 2026 summer event."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


Box = Tuple[int, int, int, int]
Point = Tuple[int, int]


@dataclass(frozen=True)
class SummerEventScreenLayout:
    reference_size: Tuple[int, int]
    regions: Dict[str, Box]
    tap_points: Dict[str, Point]

    def validate(self) -> None:
        width, height = self.reference_size
        if width <= 0 or height <= 0:
            raise ValueError("Reference size must be positive")
        for name, (x, y, box_width, box_height) in self.regions.items():
            if min(x, y, box_width, box_height) < 0 or box_width <= 0 or box_height <= 0:
                raise ValueError(f"Invalid region: {name}")
            if x + box_width > width or y + box_height > height:
                raise ValueError(f"Region exceeds reference screen: {name}")
        for name, (x, y) in self.tap_points.items():
            if not 0 <= x < width or not 0 <= y < height:
                raise ValueError(f"Tap point exceeds reference screen: {name}")

    def scale_box(self, name: str, screen_size: Tuple[int, int]) -> Box:
        x, y, width, height = self.regions[name]
        scale_x, scale_y = self._scale(screen_size)
        return (
            self._round_pixel(x * scale_x),
            self._round_pixel(y * scale_y),
            self._round_pixel(width * scale_x),
            self._round_pixel(height * scale_y),
        )

    def scale_point(self, name: str, screen_size: Tuple[int, int]) -> Point:
        x, y = self.tap_points[name]
        scale_x, scale_y = self._scale(screen_size)
        return self._round_pixel(x * scale_x), self._round_pixel(y * scale_y)

    def _scale(self, screen_size: Tuple[int, int]) -> Tuple[float, float]:
        width, height = screen_size
        if width <= 0 or height <= 0:
            raise ValueError("Screen size must be positive")
        reference_width, reference_height = self.reference_size
        return width / reference_width, height / reference_height

    @staticmethod
    def _round_pixel(value: float) -> int:
        return int(value + 0.5)


def load_screen_layout(path: Path) -> SummerEventScreenLayout:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    layout = SummerEventScreenLayout(
        reference_size=tuple(int(value) for value in raw["reference_size"]),
        regions={
            name: tuple(int(value) for value in values)
            for name, values in raw["regions"].items()
        },
        tap_points={
            name: tuple(int(value) for value in values)
            for name, values in raw["tap_points"].items()
        },
    )
    layout.validate()
    return layout
