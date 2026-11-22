"""B-9: kind->band mapping converges on sleep/samples.py single point."""

from __future__ import annotations

import json

from miband_monitor.offline_dashboard import _package_activity, collect
from miband_monitor.offline_dashboard.constants import (
    BAND_ACTIVE,
    BAND_NONWEAR,
    BAND_REST,
    BAND_SLEEP,
)
from miband_monitor.sleep import (
    BAND_CODES as SLEEP_BAND_CODES,
    KIND_NONWEAR,
    activity_band,
)
from miband_monitor.sleep.samples import BAND_CODES as SOURCE_BAND_CODES


def test_dashboard_band_codes_are_the_sleep_single_point():
    """All three layers (sleep, constants, classifier) share one encoding."""
    assert SLEEP_BAND_CODES is SOURCE_BAND_CODES
    assert (BAND_REST, BAND_ACTIVE, BAND_SLEEP, BAND_NONWEAR) == (0, 1, 2, 3)
    assert SLEEP_BAND_CODES == {
        "REST": BAND_REST,
        "ACTIVE": BAND_ACTIVE,
        "SLEEP": BAND_SLEEP,
        "NONWEAR": BAND_NONWEAR,
    }


def test_activity_band_classifier_ordering():
    """Nonwear wins over sleep; a still/worn minute is REST, a moving one ACTIVE."""
    assert activity_band({"kind": 0xF3}, in_sleep=True) == BAND_NONWEAR
    assert activity_band({"kind": 0xF0}, in_sleep=True) == BAND_SLEEP
    assert activity_band({"kind": 0xF0}, in_sleep=False) == BAND_REST
    assert activity_band({"kind": 1, "steps": 5, "intensity": 0}) == BAND_ACTIVE
    assert activity_band({"kind": KIND_NONWEAR, "steps": 0}) == BAND_NONWEAR


def test_packaged_activity_ships_code_map():
    """The payload carries the code map so JS never hardcodes `code === 3`."""
    series = _package_activity([{"ts": 1000.0, "kind": 0xF3, "steps": 0, "intensity": 0}])
    assert series["bands"] == SOURCE_BAND_CODES
    assert series["points"] == [[1000.0, BAND_NONWEAR]]


def test_rendered_html_reads_bands_from_payload(tmp_path):
    """The bundled JS references DATA.activity.bands, not a literal 3."""
    from tests.offline_dashboard.test_collect import make_db

    db = make_db(tmp_path, activity=[])
    payload = collect(db, days=7)
    assert payload["activity"]["bands"] == SOURCE_BAND_CODES

    from miband_monitor.offline_dashboard import render

    html = render(payload)
    assert "bands = DATA.activity.bands" in html
    assert "code === bands.NONWEAR" in html
    assert "code === 3" not in html
    # The code map survives JSON serialisation into the page.
    assert '"NONWEAR":3' in html or '"NONWEAR": 3' in html


def test_code_map_is_json_serialisable():
    assert json.loads(json.dumps(SOURCE_BAND_CODES)) == SOURCE_BAND_CODES
