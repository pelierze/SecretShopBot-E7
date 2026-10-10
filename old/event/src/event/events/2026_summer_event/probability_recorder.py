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
        self.confirmed_log_path = self.log_dir / "2026_summer_event_confirmed_probabilities.csv"
        self.applied_log_path = self.log_dir / "2026_summer_event_applied_probabilities.csv"
        self.known_tiles = frozenset(int(position) for position in known_tiles)
        self.session = session
        self._counts = {}
        self._ocr_sequences = {}
        self._confirmed_probabilities = self._load_confirmed_probabilities()
        self._load_existing_counts()
        self._load_ocr_sequences()
        self._promote_historical_sequences()

    def load_displayed_probabilities(self):
        return dict(self._confirmed_probabilities)

    def _load_ocr_sequences(self):
        if not self.ocr_log_path.exists():
            return
        try:
            with self.ocr_log_path.open("r", newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    position = int(row["position_m"])
                    probability = float(row["ocr_success_probability"])
                    sequence = self._ocr_sequences.setdefault(position, [])
                    if sequence and sequence[-1] != probability:
                        sequence.clear()
                    sequence.append(probability)
                    if len(sequence) > 3:
                        del sequence[:-3]
        except (OSError, KeyError, TypeError, ValueError):
            self._ocr_sequences = {}

    def _promote_historical_sequences(self) -> None:
        """Migrate three matching legacy OCR rows into the confirmed store."""
        for position_m, sequence in self._ocr_sequences.items():
            if (
                position_m not in self.known_tiles
                and position_m not in self._confirmed_probabilities
                and len(sequence) >= 3
                and len(set(sequence[-3:])) == 1
            ):
                try:
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    self._confirm_probability(position_m, sequence[-1])
                except OSError as exc:
                    logger.warning("기존 OCR 확률의 확정 데이터를 저장하지 못했습니다: %s", exc)

    def record_displayed_probability(self, position_m: int, probability: float) -> bool:
        position_m = int(position_m)
        probability = round(float(probability), 6)
        with self._file_lock:
            if position_m in self.known_tiles or position_m in self._confirmed_probabilities:
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
                sequence = self._ocr_sequences.setdefault(position_m, [])
                if sequence and sequence[-1] != probability:
                    sequence.clear()
                sequence.append(probability)
                confirmed_now = len(sequence) >= 3 and len(set(sequence[-3:])) == 1
                if confirmed_now:
                    self._confirm_probability(position_m, probability)
                # Returning True means that a stable value was newly confirmed.
                # Raw observations one and two are still persisted above, but do
                # not produce repetitive application log messages.
                return confirmed_now
            except OSError as exc:
                logger.warning("미등록 타일 OCR 확률 로그를 저장하지 못했습니다: %s", exc)
                return False

    def confirmed_probability(self, position_m: int):
        return self._confirmed_probabilities.get(int(position_m))

    def load_outcome_counts(self):
        totals = {}
        for (tile_m, _action), (attempts, successes) in self._counts.items():
            tile_successes, tile_attempts = totals.get(tile_m, (0, 0))
            totals[tile_m] = (tile_successes + successes, tile_attempts + attempts)
        return totals

    def write_applied_probabilities(self, probabilities, sources) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self._file_lock:
            write_header = (
                not self.applied_log_path.exists()
                or self.applied_log_path.stat().st_size == 0
            )
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            with self.applied_log_path.open("a", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=(
                        "timestamp",
                        "session",
                        "position_m",
                        "applied_probability",
                        "source",
                    ),
                )
                if write_header:
                    writer.writeheader()
                for position_m, probability in sorted(probabilities.items()):
                    writer.writerow(
                        {
                            "timestamp": timestamp,
                            "session": self.session,
                            "position_m": position_m,
                            "applied_probability": f"{probability:.6f}",
                            "source": sources.get(position_m, "predicted"),
                        }
                    )
        return self.applied_log_path

    def _load_confirmed_probabilities(self):
        confirmed = {}
        if not self.confirmed_log_path.exists():
            return confirmed
        try:
            with self.confirmed_log_path.open("r", newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    confirmed[int(row["position_m"])] = float(row["ocr_success_probability"])
        except (OSError, KeyError, TypeError, ValueError):
            return {}
        return confirmed

    def _confirm_probability(self, position_m: int, probability: float) -> None:
        self._confirmed_probabilities[position_m] = probability
        write_header = not self.confirmed_log_path.exists() or self.confirmed_log_path.stat().st_size == 0
        with self.confirmed_log_path.open("a", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=(
                    "timestamp",
                    "session",
                    "position_m",
                    "ocr_success_probability",
                    "observations",
                    "priority",
                ),
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "session": self.session,
                    "position_m": position_m,
                    "ocr_success_probability": f"{probability:.6f}",
                    "observations": 3,
                    "priority": "high",
                }
            )
        logger.info("신규 타일 확률 확정: %sM = %.2f%% (동일 OCR 3회)", position_m, probability * 100)

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
