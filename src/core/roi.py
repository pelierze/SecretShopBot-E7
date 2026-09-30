"""
ROI (Region of Interest) definitions and utilities.
All definitions are strictly maintained in 1280x720 logical coordinates.
"""
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import numpy as np


@dataclass
class ROI:
    """A Region of Interest defined in 1280x720 logical coordinate space."""
    x: int
    y: int
    w: int
    h: int
    name: Optional[str] = None

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        """
        Crops this ROI from a 1280x720 normalized frame.
        """
        if frame is None or frame.size == 0:
            raise ValueError("Invalid frame for cropping")
        return frame[self.y : self.y2, self.x : self.x2]

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "name": self.name}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ROI":
        return cls(
            x=data["x"],
            y=data["y"],
            w=data["w"],
            h=data["h"],
            name=data.get("name"),
        )
