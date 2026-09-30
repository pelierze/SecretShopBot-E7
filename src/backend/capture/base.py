"""
Capture backend abstract base class.
"""
from abc import ABC, abstractmethod
from typing import Optional, Tuple
import numpy as np


class CaptureBackend(ABC):
    """Abstract base class for capturing game frames."""

    @abstractmethod
    def capture(self) -> Optional[np.ndarray]:
        """
        Capture the current frame from the target environment.
        
        Returns:
            np.ndarray: BGR image array (OpenCV format), or None if capture failed.
        """
        pass

    @abstractmethod
    def get_raw_size(self) -> Tuple[int, int]:
        """
        Get the current raw width and height of the capture target.

        Returns:
            Tuple[int, int]: (width, height)
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the backend is currently connected and ready."""
        pass

    def close(self) -> None:
        """Release any allocated resources."""
        pass
