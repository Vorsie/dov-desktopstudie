from __future__ import annotations

import pytest

from desktopstudie.core.logging_util import Log
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


def test_geocode_without_candidates_is_warned_about_not_silently_returned():
    # An address the geocoder does not know answers HTTP 200 with an empty LocationResult; the
    # caller has to be told WHICH query found nothing, not just handed an empty list.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([("geolocation", b'{"LocationResult":[]}')])
    assert geocoder.geocode(client, "onbestaand", log=log) == []
    assert any("onbestaand" in m and "geen" in m for m in messages)


def test_geocode_with_candidates_is_not_warned_about():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([("geolocation/v4/Location", "geocoder_kortrijksesteenweg.json")])
    assert geocoder.geocode(client, "Kortrijksesteenweg 100 Gent", log=log)
    assert messages == []


def test_geocode_hit_is_precise_for_a_house_number_match():
    client = FixtureClient([("geolocation/v4/Location", "geocoder_kortrijksesteenweg.json")])
    hits = geocoder.geocode(client, "Kortrijksesteenweg 100 Gent")
    assert hits[0].is_precise is True


def test_geocode_hit_is_not_precise_for_a_municipality_level_match():
    hit = geocoder.GeocodeHit(address="Gent", x=0.0, y=0.0, municipality="Gent", postcode="9000",
                               location_type="basisregisters_gemeente")
    assert hit.is_precise is False


@pytest.mark.live
def test_live_geocode():
    from desktopstudie.core.services.http import HttpClient

    hits = geocoder.geocode(HttpClient(), "Kortrijksesteenweg 100 Gent")
    assert hits and hits[0].municipality == "Gent"
