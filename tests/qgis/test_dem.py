"""Reliëf van de zone uit het DHMV II DTM. De offline test bewijst alleen dat een onbereikbare
WCS niet stilzwijgend als "geen hoogteverschil" doorgaat; dat de echte dekking bruikbare peilen
geeft, kan alleen live (het WCS moet een DescribeCoverage beantwoorden vóór de laag geldig is)."""
from __future__ import annotations

import pytest

# Poort 9 (discard) op de loopback: de verbinding wordt geweigerd in plaats van te wachten, dus
# deze test blijft offline en snel.
DEAD_WCS_URL = "http://127.0.0.1:9/wcs"


def test_an_unreachable_dtm_gives_no_relief_and_says_so(qgs_app, gent_zone, monkeypatch):
    """Een bron die faalt, faalt luid: geen reliëf én een WARNING, nooit stil een leeg resultaat."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import dem, layers

    monkeypatch.setattr(dem, "DHMV_WCS_URL", DEAD_WCS_URL)
    lines = []
    log = Log("dem", lines.append, scope="qgis")

    assert dem.relief_of_zone(layers.zone_layer(gent_zone), log) is None
    assert any("WARNING" in line and "DHMV" in line for line in lines), lines


def test_no_log_is_a_valid_caller(qgs_app, gent_zone, monkeypatch):
    """`log` is optioneel; zonder logger mag het falen geen AttributeError worden."""
    from desktopstudie.qgis import dem, layers

    monkeypatch.setattr(dem, "DHMV_WCS_URL", DEAD_WCS_URL)
    assert dem.relief_of_zone(layers.zone_layer(gent_zone)) is None


@pytest.mark.live
def test_live_relief_of_the_gent_zone(qgs_app, gent_zone):
    """Gent ligt rond 9 à 11 mTAW; de zone is 50 m groot, dus het gemiddelde hoort ruim binnen
    8 - 20 mTAW te liggen en tussen het minimum en het maximum."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import dem, layers

    lines = []
    relief = dem.relief_of_zone(layers.zone_layer(gent_zone), Log("dem", lines.append, scope="qgis"))

    assert relief is not None, lines
    lo, hi, mean = relief
    assert all(isinstance(value, float) for value in relief)
    assert 8.0 < mean < 20.0
    assert lo <= mean <= hi


@pytest.mark.live
def test_live_relief_reports_what_it_found(qgs_app, gent_zone):
    """Een gelukte fase logt haar samenvatting: anders is "reliëf ontbreekt" achteraf niet te
    onderscheiden van "reliëf is nooit opgevraagd"."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import dem, layers

    lines = []
    dem.relief_of_zone(layers.zone_layer(gent_zone), Log("dem", lines.append, scope="qgis"))
    assert any("INFO" in line for line in lines), lines
