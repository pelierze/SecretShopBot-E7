"""Interfaces implemented by screen recognition and ADB adapters."""

from __future__ import annotations

from typing import Protocol

from .models import EventAction, EventState, MoveOutcome


class EventRecognitionError(RuntimeError):
    """Raised when the event screen cannot be classified safely."""


class EventOutcomePending(RuntimeError):
    """Raised while an action animation has not produced a decisive screen change yet."""


class EventInputError(RuntimeError):
    """Raised when an input command cannot be delivered safely."""


class EventObserver(Protocol):
    """Reads the authoritative event state from the game screen."""

    def observe(self, previous_state: EventState) -> EventState:
        ...

    def observe_outcome(self, action: EventAction) -> MoveOutcome:
        """Use result popup, node movement, and stack changes to classify the outcome."""
        ...


class EventExecutor(Protocol):
    """Executes one selected action through ADB or another input adapter."""

    def execute(self, action: EventAction) -> None:
        ...
