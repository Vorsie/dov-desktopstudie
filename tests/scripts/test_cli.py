"""Wat beide commandoregel-runners delen: de weigering van een opdracht zonder één plaats, het
geocoderen van een adres en de zone die eruit volgt.

`run_core.py` en `run_headless.py` hangen er allebei van af, dus een fout hier kost twee scripts.
Geen netwerk: de geocoder wordt met een FixtureClient bediend.
"""
from __future__ import annotations

import argparse

import pytest

from desktopstudie.core.logging_util import Log
from scripts import _cli
from tests.core.conftest import FixtureClient


def _args(**kwargs):
    defaults = {"adres": None, "x": None, "y": None, "buffer": 50.0, "straal": 500.0,
                "cache": "use", "out": "uitvoer/test"}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _parser():
    return _cli.add_location_args(argparse.ArgumentParser(prog="proef"))


def _log(lines=None):
    return Log("cli", lines.append if lines is not None else (lambda _m: None))


def test_address_and_coordinates_together_are_refused():
    """"Geef --adres OF --x/--y, niet allebei": twee plaatsen in één opdracht is geen plaats, en
    dat hoort te blijken vóór er iets opgehaald of weggeschreven wordt."""
    parser = _parser()

    with pytest.raises(SystemExit) as refused:
        _cli.check_location(parser, _args(adres="Gent", x=104326.0, y=192506.0))

    assert refused.value.code == 2


def test_neither_an_address_nor_a_full_coordinate_is_refused():
    """Geen locatie is net zo goed geen plaats - en een halve coördinaat ook niet."""
    parser = _parser()

    for incomplete in (_args(), _args(x=104326.0), _args(y=192506.0)):
        with pytest.raises(SystemExit) as refused:
            _cli.check_location(parser, incomplete)
        assert refused.value.code == 2


def test_an_address_or_a_full_coordinate_passes():
    parser = _parser()

    assert _cli.check_location(parser, _args(adres="Kortrijksesteenweg 100 Gent")) is None
    assert _cli.check_location(parser, _args(x=104326.0, y=192506.0)) is None


def test_a_coordinate_needs_no_geocoder():
    """Met --x/--y is er niets te zoeken; het adres blijft leeg en de client wordt niet geraakt."""
    client = FixtureClient()

    assert _cli.locate(_args(x=104326.0, y=192506.0), client, _log()) == (104326.0, 192506.0, None)
    assert client.calls == []


def test_an_address_that_is_found_gives_the_first_candidate():
    client = FixtureClient([("geolocation", "geocoder_kortrijksesteenweg.json")])

    x, y, address = _cli.locate(_args(adres="Kortrijksesteenweg 100 Gent"), client, _log())

    assert 100000 < x < 110000 and 188000 < y < 196000, (x, y)
    assert address and "Gent" in address


def test_an_address_that_is_not_found_is_none_and_says_so():
    """Niet gevonden is geen uitzondering maar een antwoord: het script eindigt met code 2, en de
    reden hoort in het log te staan in plaats van in een lege uitvoermap."""
    client = FixtureClient([("geolocation", b'{"LocationResult": []}')])
    lines = []

    assert _cli.locate(_args(adres="Nergensstraat 1"), client, _log(lines)) is None

    assert any("ERROR" in line and "Nergensstraat 1" in line for line in lines), lines


def test_the_zone_is_a_circle_of_the_buffer_around_the_point():
    """De zone is de cirkel met --buffer als straal; --straal is de zoekstraal eromheen, en de
    naam van de zone komt van het adres zodra er een is."""
    zone = _cli.zone_of(_args(buffer=50.0, straal=750.0), 104326.0, 192506.0,
                        "Kortrijksesteenweg 100, 9000 Gent")

    assert zone.radius_m == 750.0
    assert zone.address == "Kortrijksesteenweg 100, 9000 Gent"
    minx, miny, maxx, maxy = zone.bbox
    assert (maxx - minx) == pytest.approx(100.0, abs=1.0)
    assert (maxy - miny) == pytest.approx(100.0, abs=1.0)
    assert zone.area_m2 == pytest.approx(3.14159 * 50.0 ** 2, rel=0.01)


def test_a_zone_without_an_address_still_has_a_name():
    zone = _cli.zone_of(_args(), 104326.0, 192506.0, None)

    assert zone.name and zone.address is None
