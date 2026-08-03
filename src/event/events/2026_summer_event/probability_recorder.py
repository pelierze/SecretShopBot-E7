"""Persistent observations for tiles missing from the supplied probability data."""

from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ...models import EventAction, MoveOutcome


logger = logging.getLogger(__name__)


class UnknownTileProbabilityRecorder:
    FIELDNAMES = (
        "timestamp",
        "session",
        "position_m",
        "probability_tile_m",
        "action",
        "outcome",
        "attempts",
        "successes",
        "failures",
        "observed_success_probability",
    )
    _file_lock = threading.Lock()

    def __init__(self, log_dir: Path, known_tiles: Iterable[int], session: str = ""):
        self.log_dir = Path(log_dir)
        self.log_path = self.log_dir / "2026_summer_event_unknown_probabilities.csv"
        self.ocr_log_path = self.log_dir / "2026_summer_event_ocr_probabilities.csv"
        self.known_tiles = frozenset(int(position) for position in known_tiles)
        self.session = session
        self._counts = {}
        self._recorded_ocr_values = set()
        self._load_existing_counts()
        self._ocr_probabilities = self.load_displayed_probabilities()

    def load_displayed_probabilities(self):
        probabilities = {}
        if not self.ocr_log_path.exists():
            return probabilities
        try:
            with self.ocr_log_path.open("r", newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    position = int(row["position_m"])
                    probability = float(row["ocr_success_probability"])
                    probabilities[position] = probability
                    self._recorded_ocr_values.add((position, round(probability, 6)))
        except (OSError, KeyError, TypeError, ValueError):
            return {}
        return probabilities

    def record_displayed_probability(self, position_m: int, probability: float) -> bool:
        key = (int(position_m), round(float(probability), 6))
        with self._file_lock:
            if key in self._recorded_ocr_values:
                return False
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                write_header = not self.ocr_log_path.exists() or self.ocr_log_path.stat().st_size == 0
                with self.ocr_log_path.open("a", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=("timestamp", "session", "position_m", "ocr_success_probability"),
                    )
                    if write_header:
                        writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "session": self.session,
                            "position_m": position_m,
                            "ocr_success_probability": f"{probability:.6f}",
                        }
                    )
                self._recorded_ocr_values.add(key)
                return True
            except OSError as exc:
                logger.warning("미등록 타일 OCR 확률 로그를 저장하지 못했습니다: %s", exc)
                return False

    def record(
        self,
        position_m: int,
        probability_tile_m: int,
        action: EventAction,
        outcome: MoveOutcome,
    ) -> bool:
        if action is EventAction.SUPER_DASH or probability_tile_m in self.known_tiles:
            return False

        key = (probability_tile_m, action.value)
        with self._file_lock:
            self._load_existing_counts()
            attempts, successes = self._counts.get(key, (0, 0))
            attempts += 1
            successes += int(outcome is MoveOutcome.SUCCESS)
            self._counts[key] = attempts, successes
            failures = attempts - successes
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                write_header = not self.log_path.exists() or self.log_path.stat().st_size == 0
                with self.log_path.open("a", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(stream, fieldnames=self.FIELDNAMES)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "session": self.session,
                            "position_m": position_m,
                            "probability_tile_m": probability_tile_m,
                            "action": action.value,
                            "outcome": outcome.value,
                            "attempts": attempts,
                            "successes": successes,
                            "failures": failures,
                            "observed_success_probability": f"{successes / attempts:.6f}",
                        }
                    )
            except OSError as exc:
                logger.warning("미등록 타일 확률 로그를 저장하지 못했습니다: %s", exc)
                return False
        return True

    def _load_existing_counts(self) -> None:
        if not self.log_path.exists():
            return
        loaded_counts = {}
        try:
            with self.log_path.open("r", newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    key = (int(row["probability_tile_m"]), row["action"])
                    loaded_counts[key] = (int(row["attempts"]), int(row["successes"]))
            self._counts = loaded_counts
        except (OSError, KeyError, TypeError, ValueError):
            # A malformed historic log must never prevent event automation.
            return
