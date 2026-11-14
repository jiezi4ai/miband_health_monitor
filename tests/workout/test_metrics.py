"""Unit tests for workout physiological formulas and cumulative delta counters."""

from __future__ import annotations

import pytest

from miband_monitor.workout import (
    CumulativeCounter,
    WorkoutProfile,
    classify_hr_zone,
    estimate_kcal_per_min,
    is_valid_bpm,
)


def test_workout_profile_defaults_and_validation() -> None:
    profile = WorkoutProfile()
    assert profile.age == 30
    assert profile.weight_kg == 70.0
    assert profile.sex == "male"
    assert profile.resolved_hr_max == 190

    custom = WorkoutProfile(age=35, weight_kg=60.0, sex="FEMALE", hr_max=182)
    assert custom.sex == "female"
    assert custom.resolved_hr_max == 182

    with pytest.raises(ValueError):
        WorkoutProfile(age=0)
    with pytest.raises(ValueError):
        WorkoutProfile(weight_kg=-10)
    with pytest.raises(ValueError):
        WorkoutProfile(sex="other")


def test_hr_validation_and_zone_classification() -> None:
    assert not is_valid_bpm(0)
    assert not is_valid_bpm(255)
    assert not is_valid_bpm(29)
    assert not is_valid_bpm(221)
    assert is_valid_bpm(30)
    assert is_valid_bpm(220)

    assert classify_hr_zone(0, 200) is None
    assert classify_hr_zone(255, 200) is None
    assert classify_hr_zone(90, 200) == (0, "Rest")
    assert classify_hr_zone(100, 200) == (1, "Warmup")
    assert classify_hr_zone(120, 200) == (2, "Fat Burn")
    assert classify_hr_zone(140, 200) == (3, "Aerobic")
    assert classify_hr_zone(160, 200) == (4, "Threshold")
    assert classify_hr_zone(185, 200) == (5, "Peak")
    assert classify_hr_zone(205, 200) == (5, "Peak")


def test_keytel_kcal_estimation() -> None:
    male = WorkoutProfile(age=30, weight_kg=70.0, sex="male")
    female = WorkoutProfile(age=30, weight_kg=60.0, sex="female")

    assert estimate_kcal_per_min(0, male) == 0.0
    assert estimate_kcal_per_min(255, female) == 0.0
    assert estimate_kcal_per_min(140, male) == pytest.approx(12.714, abs=0.05)
    assert estimate_kcal_per_min(140, female) == pytest.approx(8.807, abs=0.05)
    assert estimate_kcal_per_min(35, male) == 0.0  # clamped at zero


def test_cumulative_counter_with_midnight_rollover() -> None:
    counter = CumulativeCounter()
    assert counter.total == 0
    assert counter.update(5000) == 0
    assert counter.update(5400) == 400
    # Midnight rollover on 0x0007 counter
    assert counter.update(30) == 430
    assert counter.update(250) == 650
    assert counter.total == 650
