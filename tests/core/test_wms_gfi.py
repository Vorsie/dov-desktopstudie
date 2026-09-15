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
