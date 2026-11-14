"""Physiological bounds shared by sleep analysis and the dashboards.

Keeping these values in one place prevents the live dashboard, offline
dashboard and sleep classifier from silently disagreeing about what counts as a
usable heart-rate/SpO2 reading.
"""

from __future__ import annotations

#: Sentinel written by the band when it has no heart-rate measurement.
HR_UNAVAILABLE = 255
#: Plausible human heart-rate window used by every consumer.
HR_MIN = 30
HR_MAX = 220
#: Plausible pulse-oximeter window used for capture filtering.
SPO2_MIN = 50
SPO2_MAX = 100
#: Standard gravity, used to convert accelerometer counts to m/s^2.
STANDARD_GRAVITY = 9.80665
#: Rolling window size for live heart-rate smoothing during workout monitoring.
DEFAULT_HR_SMOOTHING_WINDOW = 5
#: Five-zone heart-rate classification boundaries as fractions of HRmax:
#: (zone_index, label, min_ratio_inclusive, max_ratio_exclusive).
WORKOUT_HR_ZONES = (
    (1, "Warmup", 0.50, 0.60),
    (2, "Fat Burn", 0.60, 0.70),
    (3, "Aerobic", 0.70, 0.80),
    (4, "Threshold", 0.80, 0.90),
    (5, "Peak", 0.90, 1.00),
)
