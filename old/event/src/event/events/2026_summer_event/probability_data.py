"""Sparse probability data loading and update helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class TileProbability:
    position_m: int
    success_probability: float
    source: Optional[str] = None
    updated_at: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class ProbabilityDataset:
    schema_version: int
    event_id: str
    tiles: Dict[int, TileProbability]
    updated_at: Optional[str] = None

    @property
    def probabilities(self) -> Dict[int, float]:
        return {position: tile.success_probability for position, tile in self.tiles.items()}

    @property
    def fingerprint(self) -> str:
        """Stable hash used to decide whether generated routes are stale."""
        canonical = {
            str(position): tile.success_probability
            for position, tile in sorted(self.tiles.items())
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def missing_positions(self, positions: Iterable[int]) -> tuple:
        return tuple(position for position in positions if position not in self.tiles)


def load_probability_data(path: Path) -> ProbabilityDataset:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tiles = {}
    for raw_position, raw_tile in raw.get("tiles", {}).items():
        position = int(raw_position)
        if isinstance(raw_tile, (int, float)):
            raw_tile = {"success_probability": raw_tile}
        tile = TileProbability(
            position_m=position,
            success_probability=float(raw_tile["success_probability"]),
            source=raw_tile.get("source"),
            updated_at=raw_tile.get("updated_at"),
            note=raw_tile.get("note"),
        )
        _validate_tile(tile)
        tiles[position] = tile

    return ProbabilityDataset(
        schema_version=int(raw.get("schema_version", 1)),
        event_id=str(raw.get("event_id", "2026_summer_event")),
        tiles=tiles,
        updated_at=raw.get("updated_at"),
    )


def _validate_tile(tile: TileProbability) -> None:
    if tile.position_m < 0 or tile.position_m % 10:
        raise ValueError(f"Position must be a non-negative 10M tile: {tile.position_m}")
    if not 0.0 <= tile.success_probability <= 1.0:
        raise ValueError(
            f"Probability must be between 0 and 1 at {tile.position_m}M: "
            f"{tile.success_probability}"
        )
