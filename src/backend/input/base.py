"""
Input backend abstract base class.
"""
from abc import ABC, abstractmethod


class InputBackend(ABC):
    """Abstract base class for sending inputs to the target environment."""

    @abstractmethod
    def click(self, x: int, y: int, delay: float = 0.5) -> bool:
        """
        Send a click/tap at physical coordinates (x, y).

        Args:
            x: Physical X coordinate
            y: Physical Y coordinate
            delay: Delay in seconds after click

        Returns:
            bool: True if input was successfully sent.
        """
        pass

    @abstractmethod
    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        delay: float = 0.5,
    ) -> bool:
        """
        Send a swipe/drag from physical (x1, y1) to (x2, y2).

        Args:
            x1: Starting physical X coordinate
            y1: Starting physical Y coordinate
            x2: Ending physical X coordinate
            y2: Ending physical Y coordinate
            duration_ms: Duration of swipe in milliseconds
            delay: Delay in seconds after swipe

        Returns:
            bool: True if swipe was successfully sent.
        """
        pass

    def press_key(self, key_code: int) -> bool:
        """
        Send a key press.

        Args:
            key_code: Virtual key code or platform key code

        Returns:
            bool: True if key was sent.
        """
        return False

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the backend is connected and ready."""
        pass

    def close(self) -> None:
        """Release any allocated resources."""
        pass
