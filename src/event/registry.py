"""Dynamic loader for event-specific packages."""

from importlib import import_module
from types import ModuleType


def load_event_module(event_id: str) -> ModuleType:
    if not event_id or any(part in event_id for part in ("/", "\\", ".")):
        raise ValueError(f"Invalid event id: {event_id!r}")
    return import_module(f"src.event.events.{event_id}")
