"""Inline SVG hypnogram rendering for the offline dashboard.

Drawing server-side (and run-length encoded) keeps the chart crisp at any width
and avoids the canvas resize dance the live charts need. The stage palette is
also injected into the page as JavaScript colours, so it lives here next to the
lanes it must agree with.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .constants import STAGE_AWAKE, STAGE_DEEP, STAGE_LIGHT, STAGE_UNKNOWN
from .strings import FLAT_IN_BED_LABEL, HYPNOGRAM_LABEL

#: Lane index for the hypnogram, top row is the deepest stage (awake at bottom).
STAGE_LANES = {STAGE_DEEP: 0, STAGE_LIGHT: 1, STAGE_AWAKE: 2}

#: Geometry of the flat in-bed band shown for a night without heart rate: no
#: stages exist, so stacking four empty lanes would pretend data exists.
FLAT_BAND_HEIGHT = 44
FLAT_BAND_Y = 12
FLAT_BAND_BAR_HEIGHT = 20
FLAT_BAND_FILL = "#33404f"

#: Bottom strip of a hypnogram: measured off-wrist minutes get a hatch, while a
#: minute the band never recorded stays transparent (unset, not zero).
NONWEAR_STRIP_HEIGHT = 6
NONWEAR_PATTERN_ID = "hypnoNonwearHatch"
NONWEAR_STRIP_FILL = f"url(#{NONWEAR_PATTERN_ID})"

#: A recorded minute with no heart-rate reading is neither a stage nor a gap:
#: paint it in the bottom lane with this muted grey when ``show_unknown`` is set.
UNKNOWN_MINUTE_FILL = "#475569"


def _stage_style() -> dict[str, str]:
    return {
        STAGE_DEEP: "#8b5cf6",
        STAGE_LIGHT: "#38bdf8",
        STAGE_AWAKE: "#64748b",
        STAGE_UNKNOWN: "#2a323c",
    }


def hypnogram_svg(
    stages: Sequence[str],
    *,
    height: int = 44,
    lane_gap: float = 1.0,
    nonwear: Optional[Sequence[bool]] = None,
    show_unknown: bool = False,
) -> str:
    """Render a hypnogram as inline SVG, one rectangle run per stage stretch.

    Drawing this server-side (and run-length encoded) keeps it crisp at any
    width and avoids the canvas resize dance the live charts need.  When
    *nonwear* is supplied, a thin bottom strip hatches the minutes the band
    explicitly measured as off the wrist; minutes with no record stay empty.
    With *show_unknown*, a recorded minute without heart rate is painted grey
    in the bottom lane instead of being silently left blank.
    """
    colors = _stage_style()
    width = max(1, len(stages))
    # One lane per drawable stage: the last one must still land inside the viewBox.
    lane = height / len(STAGE_LANES)
    strip = NONWEAR_STRIP_HEIGHT if nonwear is not None else 0
    parts = [
        f'<svg class="hypno" viewBox="0 0 {width} {height + strip}" '
        f'preserveAspectRatio="none" role="img" aria-label="{HYPNOGRAM_LABEL}">'
    ]
    if strip:
        parts.append(
            f'<defs><pattern id="{NONWEAR_PATTERN_ID}" width="6" height="6" '
            'patternUnits="userSpaceOnUse">'
            '<rect width="6" height="6" fill="#1e2630"/>'
            '<path d="M-1 7 L7 -1" stroke="#4a5866" stroke-width="1"/>'
            '</pattern></defs>'
        )
    for index in range(1, len(STAGE_LANES)):
        y = index * lane
        parts.append(
            f'<line x1="0" y1="{y:.2f}" x2="{width}" y2="{y:.2f}" '
            f'stroke="#2a323c" stroke-width="0.6"/>'
        )

    run_start = 0
    while run_start < len(stages):
        stage = stages[run_start]
        run_end = run_start
        while run_end + 1 < len(stages) and stages[run_end + 1] == stage:
            run_end += 1
        color = colors.get(stage)
        if show_unknown and stage == STAGE_UNKNOWN:
            y = (len(STAGE_LANES) - 1) * lane
            parts.append(
                f'<rect x="{run_start}" y="{y:.2f}" width="{run_end - run_start + 1}" '
                f'height="{max(1.0, lane - lane_gap):.2f}" fill="{UNKNOWN_MINUTE_FILL}"/>'
            )
        elif color and stage in STAGE_LANES:
            y = STAGE_LANES[stage] * lane
            parts.append(
                f'<rect x="{run_start}" y="{y:.2f}" width="{run_end - run_start + 1}" '
                f'height="{max(1.0, lane - lane_gap):.2f}" fill="{color}"/>'
            )
        run_start = run_end + 1

    if strip:
        run_start = 0
        flags = list(nonwear or [])
        while run_start < min(len(flags), width):
            if not flags[run_start]:
                run_start += 1
                continue
            run_end = run_start
            while (
                run_end + 1 < len(flags)
                and flags[run_end + 1]
            ):
                run_end += 1
            parts.append(
                f'<rect x="{run_start}" y="{height}" width="{run_end - run_start + 1}" '
                f'height="{strip}" fill="{NONWEAR_STRIP_FILL}"/>'
            )
            run_start = run_end + 1

    parts.append("</svg>")
    return "".join(parts)


def flat_in_bed_svg(minutes: int) -> str:
    """One flat in-bed band for a night the band recorded no heart rate for.

    Without heart rate there is nothing to stack, so the whole in-bed span is
    drawn as a single band instead of four empty lanes.
    """
    width = max(1, minutes)
    return (
        f'<svg class="hypno" viewBox="0 0 {width} {FLAT_BAND_HEIGHT}" '
        f'preserveAspectRatio="none" role="img" aria-label="{FLAT_IN_BED_LABEL}">'
        f'<rect x="0" y="{FLAT_BAND_Y}" width="{width}" height="{FLAT_BAND_BAR_HEIGHT}" '
        f'fill="{FLAT_BAND_FILL}"/></svg>'
    )
