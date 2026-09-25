"""Distinguish theme selection states using shape and absolute color together."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.image_matcher import read_image


@dataclass(frozen=True)
class ThemeSelectionObservation:
    state: str  # unselected, selected, unknown
    bounds: tuple[int, int, int, int] | None
    shape_scores: tuple[float, float]
    color_errors: tuple[float, float]


class ThemeSelectionDetector:
    """Read-only detector; ambiguous or unrelated screens return unknown.

    Correlation locates the card but ignores much of the background color shift.
    Normalized mean absolute BGR error distinguishes the two selected states.
    Thresholds are provisional and configurable; this class never sends input.
    """

    def __init__(self, templates_dir: Path, *, min_shape_score=0.90,
                 max_color_error=0.06, min_color_margin=0.04):
        self.templates = tuple(
            read_image(str(Path(templates_dir) / f"select_supply_{index}.png"))
            for index in (1, 2)
        )
        if any(template is None for template in self.templates):
            raise ValueError("테마 선택 전·후 템플릿을 읽을 수 없습니다.")
        self.min_shape_score = min_shape_score
        self.max_color_error = max_color_error
        self.min_color_margin = min_color_margin

    def observe(self, screen: np.ndarray) -> ThemeSelectionObservation:
        scores, errors, boxes = [], [], []
        for template in self.templates:
            height, width = template.shape[:2]
            if (screen is None or screen.ndim != 3 or screen.shape[2] != 3
                    or screen.shape[0] < height or screen.shape[1] < width):
                return ThemeSelectionObservation("unknown", None, (0.0, 0.0), (1.0, 1.0))
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(result)
            sample = screen[y:y + height, x:x + width]
            error = float(np.abs(sample.astype(np.float32) - template).mean() / 255.0)
            scores.append(score)
            errors.append(error)
            boxes.append((x, y, width, height))

        winner = int(errors[1] < errors[0])
        other = 1 - winner
        # Both templates describe the same card, even though their crop sizes differ.
        centers = [(x + w / 2, y + h / 2) for x, y, w, h in boxes]
        same_card = all(abs(a - b) <= 20 for a, b in zip(*centers))
        known = (
            same_card
            and min(scores) >= self.min_shape_score
            and errors[winner] <= self.max_color_error
            and errors[other] - errors[winner] >= self.min_color_margin
        )
        state = ("unselected", "selected")[winner] if known else "unknown"
        return ThemeSelectionObservation(
            state, boxes[winner] if known else None, tuple(scores), tuple(errors),
        )
