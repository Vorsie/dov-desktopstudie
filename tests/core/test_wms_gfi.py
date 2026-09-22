from __future__ import annotations

import pytest

from desktopstudie.core.logging_util import Log
from desktopstudie.core.services import wms_gfi
from tests.core.conftest import FixtureClient

URL = "https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/overstromingsgevoelige_gebieden_fluviaal/MapServer/WMSServer"


def test_hit_returns_properties_with_layer_name():
    client = FixtureClient([("GetFeatureInfo", "watertoets_fluviaal_hit.json")])
    rows = wms_gfi.feature_info_at_point(client, URL, "0", 102000.0, 191500.0)
    assert rows[0]["gridcode"] == "3"
    assert rows[0]["layerName"].startswith("Overstromingsgevoelige")
    call = client.calls[0]
    assert "bbox=101950.00%2C191450.00%2C102050.00%2C191550.00" in call
    assert "info_format=application%2Fgeo%2Bjson" in call
    assert "width=101" in call and "height=101" in call
    assert "i=50" in call and "j=50" in call
    assert "styles=" in call
    assert "format=image%2Fpng" in call


def test_empty_response_gives_no_rows():
    client = FixtureClient([("GetFeatureInfo", "watertoets_pluviaal_empty.json")])
    assert wms_gfi.feature_info_at_point(client, URL, "0", 104326.0, 192506.0) == []


def test_the_number_of_features_is_logged_at_debug_level():
    # Zero features is the normal answer for a point outside the mapped area, so this is a DEBUG
    # line, not a WARNING - but it still has to say what was asked and what came back.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="DEBUG")
    client = FixtureClient([("GetFeatureInfo", "watertoets_pluviaal_empty.json")])
    assert wms_gfi.feature_info_at_point(client, URL, "0", 104326.0, 192506.0, log=log) == []
    assert any("DEBUG" in m and "0" in m for m in messages)


def test_a_hit_is_logged_at_debug_level_too():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="DEBUG")
    client = FixtureClient([("GetFeatureInfo", "watertoets_fluviaal_hit.json")])
    rows = wms_gfi.feature_info_at_point(client, URL, "0", 102000.0, 191500.0, log=log)
    assert any("DEBUG" in m and str(len(rows)) in m for m in messages)


@pytest.mark.live
def test_live_flood_point():
    from desktopstudie.core.services.http import HttpClient

    rows = wms_gfi.feature_info_at_point(HttpClient(), URL, "0", 102000.0, 191500.0)
    assert rows and rows[0]["gridcode"] in {"1", "2", "3"}


def test_a_coarse_coverage_is_not_asked_at_one_metre_per_pixel():
    """De krimp-zwelkaart antwoordde niets waar ze wel degelijk een klasse tekent.

    Niet de plek en niet de WMS-versie: de RESOLUTIE van de vraag. Het rooster is 100 m, en
    gevraagd op 1 m per pixel (101 pixels over 100 m) antwoordt GeoServer met nul objecten. Live
    gemeten op 2026-09-21, op drie punten tegelijk (Wervik 57611,6/165524,9, Brugge
    67624,8/212695,4, Brasschaat 157084,4/221428,5): op 1,0 en 2,0 m per pixel nul objecten, vanaf
    3,0 m per pixel klasse 2, 4 en 1 - dezelfde klassen die de kaart daar tekent.

    Grover vragen mag niet het standaardgedrag worden: dezelfde vraag op 9 m per pixel verschuift
    de GLG van 3,54 naar 3,52 m, want dan middelt ze buurcellen mee. Dus zegt de kaart zelf hoe
    grof ze bevraagd wil worden, en de rest blijft op 101 pixels staan.
    """
    client = FixtureClient([("GetFeatureInfo", "watertoets_fluviaal_hit.json")])

    wms_gfi.feature_info_at_point(client, URL, "0", 102000.0, 191500.0, m_per_pixel=10.0)
    call = client.calls[-1]
    assert "width=11" in call and "height=11" in call, call
    assert "i=5" in call and "j=5" in call, "het gevraagde punt blijft het middelste beeldpunt"
    assert "bbox=101950.00%2C191450.00%2C102050.00%2C191550.00" in call, "en dezelfde doos"

    wms_gfi.feature_info_at_point(client, URL, "0", 102000.0, 191500.0)
    assert "width=101" in client.calls[-1], "zonder vraag blijft het fijne rooster staan"
