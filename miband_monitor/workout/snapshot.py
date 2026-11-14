"""Pure snapshot and zone-breakdown formatting for :class:`WorkoutSession`."""

from __future__ import annotations

import time
from typing import Optional

from .constants import STATE_FINISHED, WORKOUT_HR_ZONES
from .metrics import WorkoutProfile, classify_hr_zone


def build_zone_breakdown(zone_seconds: dict[int, float], hr_max: int) -> list[dict]:
    """Return ordered Rest + Z1..Z5 zone summaries for snapshot serialization."""
    breakdown = [
        {
            "zone": 0,
            "label": "Rest",
            "min_bpm": 0,
            "max_bpm": max(0, int(round(hr_max * WORKOUT_HR_ZONES[0][2])) - 1),
            "seconds": round(zone_seconds.get(0, 0.0), 1),
        }
    ]
    for z_idx, z_label, low_ratio, high_ratio in WORKOUT_HR_ZONES:
        breakdown.append(
            {
                "zone": z_idx,
                "label": z_label,
                "min_bpm": int(round(hr_max * low_ratio)),
                "max_bpm": int(round(hr_max * high_ratio)) if z_idx < 5 else hr_max,
                "seconds": round(zone_seconds.get(z_idx, 0.0), 1),
            }
        )
    return breakdown


def format_workout_snapshot(
    *,
    state: str,
    started_at: float,
    ended_at: Optional[float],
    profile: WorkoutProfile,
    smoothing_values: list[int],
    valid_hr_count: int,
    filtered_hr_count: int,
    hr_sum: int,
    latest_hr: Optional[int],
    min_hr: Optional[int],
    max_hr: Optional[int],
    zone_seconds: dict[int, float],
    estimated_hr_kcal: float,
    net_steps: int,
    net_distance_m: int,
    net_band_kcal: int,
    battery_pct: Optional[int],
    battery_updated_at: Optional[float],
    reconnect_count: int,
    gaps: list[dict],
    gap_filled_count: int,
    timeline: Optional[list[dict]] = None,
) -> dict:
    """Assemble a JSON-serializable workout state dict."""
    end_ref = ended_at if ended_at is not None else time.time()
    elapsed_s = max(0.0, end_ref - started_at)
    hr_max = profile.resolved_hr_max
    smoothed = (
        round(sum(smoothing_values) / len(smoothing_values), 1)
        if smoothing_values
        else None
    )
    avg_hr = round(hr_sum / valid_hr_count, 1) if valid_hr_count > 0 else None
    current_zone = classify_hr_zone(latest_hr, hr_max) if latest_hr is not None else None

    data = {
        "active": state != STATE_FINISHED,
        "state": state,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_seconds": round(elapsed_s, 1),
        "profile": {
            "age": profile.age,
            "weight_kg": profile.weight_kg,
            "sex": profile.sex,
            "hr_max": hr_max,
        },
        "heart_rate": {
            "latest": latest_hr,
            "smoothed": smoothed,
            "avg": avg_hr,
            "min": min_hr,
            "max": max_hr,
            "valid_count": valid_hr_count,
            "filtered_count": filtered_hr_count,
            "zone": (
                {"index": current_zone[0], "label": current_zone[1]}
                if current_zone
                else None
            ),
        },
        "zones": build_zone_breakdown(zone_seconds, hr_max),
        "steps": {
            "net_steps": net_steps,
            "net_distance_m": net_distance_m,
            "net_band_kcal": net_band_kcal,
        },
        "calories": {
            "estimated_hr_kcal": round(estimated_hr_kcal, 1),
            "band_kcal": net_band_kcal,
        },
        "battery_pct": battery_pct,
        "battery_updated_at": battery_updated_at,
        "reconnect_count": reconnect_count,
        "gaps": [dict(g) for g in gaps],
        "gap_filled_count": gap_filled_count,
    }
    if timeline is not None:
        data["timeline"] = timeline
    return data
