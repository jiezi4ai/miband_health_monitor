"""Sleep-session and non-wear span detection from band activity samples.

Two signals, in two roles: the band's own ``kind`` state machine anchors *where*
a night is, and stillness extends it outward. Extending on stillness alone would
swallow an entire day spent sitting down; anchoring on stillness alone loses the
edges of a real night. Non-wear (``0xF3``) stretches are reported separately so
an off-wrist night is never printed as hours in bed.
"""

from __future__ import annotations

from datetime import tzinfo
from typing import Optional, Sequence

from .constants import (
    ANCHOR_MINUTES,
    EXTENSION_GAP_MINUTES,
    MIN_ANCHOR_MINUTES,
    MIN_NONWEAR_MINUTES,
    MIN_SESSION_MINUTES,
    MIN_STILL_LANDING,
    MINUTE,
    SESSION_GAP_MINUTES,
)
from .samples import is_asleep_minute, is_nonwear, is_sleep_kind, is_still_minute, local_iso


def detect_sessions(
    samples: Sequence[dict],
    *,
    gap_minutes: int = SESSION_GAP_MINUTES,
    min_minutes: int = MIN_SESSION_MINUTES,
    anchor_minutes: int = ANCHOR_MINUTES,
    extension_gap_minutes: int = EXTENSION_GAP_MINUTES,
) -> list[list[dict]]:
    """Group samples into sleep sessions.

    Two signals, in two roles:

    * ``kind`` **anchors**: the band's own state machine says "sleep" for part of
      every real night and never during the day, so it decides *where* a night
      is. Runs of it are clustered, allowing ``gap_minutes`` of wake-up between.
    * **stillness extends**: from the first and last anchor minute the session
      grows outward while adjacent minutes are still (no steps and low
      movement intensity) and the wrist is on, bridging short roll-over bursts
      up to ``extension_gap_minutes`` when sustained stillness follows, and never
      more than ``anchor_minutes`` past the anchor.
    """
    anchors = [index for index, sample in enumerate(samples) if is_sleep_kind(sample["kind"])]
    if not anchors:
        return []

    # Cluster the anchor minutes; a wake-up shorter than gap_minutes stays inside.
    clusters: list[list[int]] = [[anchors[0]]]
    for index in anchors[1:]:
        if samples[index]["ts"] - samples[clusters[-1][-1]]["ts"] > gap_minutes * MINUTE:
            clusters.append([index])
        else:
            clusters[-1].append(index)

    out_gap = min(gap_minutes, extension_gap_minutes)

    def _has_still_landing(index: int, direction: int) -> bool:
        """True when at least MIN_STILL_LANDING contiguous minutes are still."""
        prev_ts = samples[index]["ts"]
        for offset in range(1, MIN_STILL_LANDING):
            nxt = index + direction * offset
            if not (0 <= nxt < len(samples)):
                return False
            if abs(samples[nxt]["ts"] - prev_ts) > MINUTE * 1.5:
                return False
            if not is_still_minute(samples[nxt]):
                return False
            prev_ts = samples[nxt]["ts"]
        return True

    def extend(start: int, direction: int, limit_ts: float) -> int:
        """Walk outward from ``start`` on stillness, bridging brief movement."""
        current = start
        while True:
            found = None
            probe = current + direction
            while 0 <= probe < len(samples):
                if abs(samples[probe]["ts"] - samples[current]["ts"]) > out_gap * MINUTE:
                    break
                if is_still_minute(samples[probe]):
                    if probe == current + direction or _has_still_landing(probe, direction):
                        found = probe
                        break
                probe += direction
            if found is None:
                return current
            if abs(samples[found]["ts"] - limit_ts) > anchor_minutes * MINUTE:
                return current
            current = found

    sessions: list[list[dict]] = []
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        left = extend(first, -1, samples[first]["ts"])
        right = extend(last, +1, samples[last]["ts"])
        # Do not begin or end a session on a step/non-wear edge anchor.
        while left < right and not is_asleep_minute(samples[left]):
            left += 1
        while right > left and not is_asleep_minute(samples[right]):
            right -= 1
        session = list(samples[left:right + 1])
        asleep = sum(1 for sample in session if is_asleep_minute(sample))
        if asleep < min_minutes or len(cluster) < MIN_ANCHOR_MINUTES:
            continue
        if sessions and session[0]["ts"] - sessions[-1][-1]["ts"] <= gap_minutes * MINUTE:
            # The extension of the previous cluster reached up to this one: one
            # night, not two (a 2-minute roll-over must not split the report).
            sessions[-1].extend(
                sample for sample in session if sample["ts"] > sessions[-1][-1]["ts"]
            )
        else:
            sessions.append(session)
    return sessions


def detect_nonwear_spans(
    samples: Sequence[dict],
    *,
    min_minutes: int = MIN_NONWEAR_MINUTES,
    tz: Optional[str | tzinfo] = None,
) -> list[dict]:
    """Long stretches the band spent off the wrist, oldest first."""
    spans: list[dict] = []
    run: list[dict] = []

    def close() -> None:
        nonlocal run
        if len(run) >= min_minutes:
            spans.append(
                {
                    "start": local_iso(run[0]["ts"], tz=tz),
                    "end": local_iso(run[-1]["ts"], tz=tz),
                    "minutes": len(run),
                    "hours": round(len(run) / 60, 1),
                }
            )
        run = []

    for sample in samples:
        if is_nonwear(sample["kind"]):
            run.append(sample)
        elif run:
            close()
    if run:
        close()
    return spans
