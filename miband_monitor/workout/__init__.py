"""Real-time workout tracking domain package.

Depends downward only on ``miband_monitor.config`` and contains no BLE, storage,
UI or CLI side effects.
"""

from __future__ import annotations

from .constants import (
    STATE_FINISHED,
    STATE_GAP_FILLING,
    STATE_RECONNECTING,
    STATE_STREAMING,
    WORKOUT_STATES,
)
from .metrics import (
    CumulativeCounter,
    WorkoutProfile,
    classify_hr_zone,
    estimate_kcal_per_min,
    is_valid_bpm,
)
from .session import WorkoutSession

__all__ = [
    "CumulativeCounter",
    "STATE_FINISHED",
    "STATE_GAP_FILLING",
    "STATE_RECONNECTING",
    "STATE_STREAMING",
    "WORKOUT_STATES",
    "WorkoutProfile",
    "WorkoutSession",
    "classify_hr_zone",
    "estimate_kcal_per_min",
    "is_valid_bpm",
]
