from __future__ import annotations

import pytest

from desktopstudie.core.services import geocoder
from tests.core.conftest import FixtureClient


def test_geocode_returns_lambert72_candidates_in_order():
    client = FixtureClient([("geolocation/v4/Location", "geocoder_kortrijksesteenweg.json")])
    hits = geocoder.geocode(client, "Kortrijksesteenweg 100 Gent")
    assert hits[0].address == "Kortrijksesteenweg 100, 9000 Gent"
    assert hits[0].x == pytest.approx(104326.8)
    assert hits[0].y == pytest.approx(192506.67)
    assert hits[0].municipality == "Gent"
    assert "q=Kortrijksesteenweg%20100%20Gent" in client.calls[0]


def test_geocode_empty_result_gives_empty_list():
    client = FixtureClient([("geolocation", b'{"LocationResult":[]}')])
    assert geocoder.geocode(client, "onbestaand") == []


@pytest.mark.live
def test_live_geocode():
    from desktopstudie.core.services.http import HttpClient

    hits = geocoder.geocode(HttpClient(), "Kortrijksesteenweg 100 Gent")
    assert hits and hits[0].municipality == "Gent"
