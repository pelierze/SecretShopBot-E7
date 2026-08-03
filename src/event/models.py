"""Data models shared by event implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set


class EventPlan(str, Enum):
    TARGET_100M = "100m"
    TARGET_200M = "200m"
    TARGET_300M = "300m"


class EventAction(str, Enum):
    BASIC = "basic"
    SHIELD = "shield"
    LEAP = "leap"
    SUPER_DASH = "super_dash"
    STOP = "stop"

    @property
    def display_name(self) -> str:
        return {
            EventAction.BASIC: "달리기",
            EventAction.SHIELD: "보호",
            EventAction.LEAP: "도움닫기",
            EventAction.SUPER_DASH: "슈퍼럭키",
            EventAction.STOP: "중지",
        }[self]


class MoveOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass
class ItemInventory:
    shield: int = 2
    leap: int = 1
    super_dash: int = 2


@dataclass
class EventStats:
    attempts: Dict[EventAction, int] = field(default_factory=dict)
    successes: Dict[EventAction, int] = field(default_factory=dict)
    failures: Dict[EventAction, int] = field(default_factory=dict)
    rewards: Dict[int, int] = field(default_factory=dict)
    drinks_used: int = 0
    rollbacks: int = 0

    def increment(self, bucket: Dict, key) -> None:
        bucket[key] = bucket.get(key, 0) + 1


@dataclass
class EventState:
    position_m: int = 0
    plan: EventPlan = EventPlan.TARGET_100M
    items: ItemInventory = field(default_factory=ItemInventory)
    collected_reward_tiles: Set[int] = field(default_factory=set)
    stats: EventStats = field(default_factory=EventStats)
    active: bool = True
