"""Pure physiology and incremental counter helpers for workout sessions.

Nothing here touches BLE, SQLite or asyncio. Every calculation accepts plain
numbers/dicts and can be unit-tested deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .constants import (
    DEFAULT_WORKOUT_AGE,
    DEFAULT_WORKOUT_SEX,
    DEFAULT_WORKOUT_WEIGHT_KG,
    HR_MAX,
    HR_MIN,
    WORKOUT_HR_ZONES,
)

_JOULES_PER_KCAL = 4.184


@dataclass(frozen=True)
class WorkoutProfile:
    """Physiological profile used for HR zone thresholds and kcal estimation."""

    age: int = DEFAULT_WORKOUT_AGE
    weight_kg: float = DEFAULT_WORKOUT_WEIGHT_KG
    sex: str = DEFAULT_WORKOUT_SEX
    hr_max: Optional[int] = None

    def __post_init__(self) -> None:
        if int(self.age) <= 0:
            raise ValueError(f"age must be positive, got {self.age!r}")
        if float(self.weight_kg) <= 0:
            raise ValueError(f"weight_kg must be positive, got {self.weight_kg!r}")
        normalized_sex = str(self.sex).strip().lower()
        if normalized_sex not in ("male", "female"):
            raise ValueError(f"sex must be 'male' or 'female', got {self.sex!r}")
        object.__setattr__(self, "age", int(self.age))
        object.__setattr__(self, "weight_kg", float(self.weight_kg))
        object.__setattr__(self, "sex", normalized_sex)
        if self.hr_max is not None:
            resolved = int(self.hr_max)
            if not HR_MIN <= resolved <= HR_MAX + 20:
                raise ValueError(f"hr_max out of plausible range: {self.hr_max!r}")
            object.__setattr__(self, "hr_max", resolved)

    @property
    def resolved_hr_max(self) -> int:
        """Return explicit *hr_max* or Fox estimate (220 - age)."""
        if self.hr_max is not None:
            return self.hr_max
        return max(HR_MIN, 220 - self.age)


def is_valid_bpm(bpm: int) -> bool:
    """Return True if *bpm* lies within plausible human bounds (30..220)."""
    return HR_MIN <= int(bpm) <= HR_MAX


def classify_hr_zone(bpm: int, hr_max: int) -> Optional[tuple[int, str]]:
    """Map *bpm* to (zone_index, label) using 5-zone %HRmax bands.

    Values below 50% of *hr_max* return ``(0, "Rest")``; invalid HR values
    (e.g. ``0`` or ``255``) return ``None``.
    """
    if not is_valid_bpm(bpm) or hr_max <= 0:
        return None
    ratio = float(bpm) / float(hr_max)
    if ratio < WORKOUT_HR_ZONES[0][2]:
        return (0, "Rest")
    for zone_idx, label, low, high in WORKOUT_HR_ZONES:
        if zone_idx == 5 and ratio >= low:
            return (zone_idx, label)
        if low <= ratio < high:
            return (zone_idx, label)
    return (WORKOUT_HR_ZONES[-1][0], WORKOUT_HR_ZONES[-1][1])


def estimate_kcal_per_min(bpm: int, profile: WorkoutProfile) -> float:
    """Estimate instantaneous energy expenditure (kcal/min) via Keytel (2005)."""
    if not is_valid_bpm(bpm):
        return 0.0
    if profile.sex == "female":
        kj_per_min = (
            -20.4022
            + 0.4472 * bpm
            - 0.1263 * profile.weight_kg
            + 0.074 * profile.age
        )
    else:
        kj_per_min = (
            -55.0969
            + 0.6309 * bpm
            + 0.1988 * profile.weight_kg
            + 0.2017 * profile.age
        )
    return max(0.0, kj_per_min / _JOULES_PER_KCAL)


class CumulativeCounter:
    """Track net workout delta from a daily-resetting cumulative counter.

    The Mi Band 0x0007 steps characteristic reports cumulative totals for the
    current local day and resets to 0 at midnight. On the first observation,
    this tracker latches the session baseline; if a later observation drops
    below the prior raw value, a rollover is accrued before resetting the
    current epoch's baseline to 0.
    """

    def __init__(self) -> None:
        self.initialized = False
        self.baseline: int = 0
        self.last_raw: int = 0
        self._accrued_prior: int = 0

    def update(self, raw_value: int) -> int:
        """Record a new cumulative *raw_value* and return net session gain."""
        value = max(0, int(raw_value))
        if not self.initialized:
            self.initialized = True
            self.baseline = value
            self.last_raw = value
            return 0
        if value < self.last_raw:
            self._accrued_prior += max(0, self.last_raw - self.baseline)
            self.baseline = 0
        self.last_raw = value
        return self._accrued_prior + max(0, value - self.baseline)

    @property
    def total(self) -> int:
        """Current net delta accrued during this session."""
        if not self.initialized:
            return 0
        return self._accrued_prior + max(0, self.last_raw - self.baseline)
