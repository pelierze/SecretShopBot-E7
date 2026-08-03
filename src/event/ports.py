"""Interfaces implemented by screen recognition and ADB adapters."""

from __future__ import annotations

from typing import Protocol

from .models import EventAction, EventState, MoveOutcome


class EventObserver(Protocol):
    """Reads the authoritative event state from the game screen."""

    def observe(self, previous_state: EventState) -> EventState:
        ...

    def observe_outcome(self, action: EventAction) -> MoveOutcome:
        ...


class EventExecutor(Protocol):
    """Executes one selected action through ADB or another input adapter."""

    def execute(self, action: EventAction) -> None:
        ...
