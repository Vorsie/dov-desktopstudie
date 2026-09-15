from __future__ import annotations

from desktopstudie.core.services import wms_gfi
from tests.core.conftest import FixtureClient

URL = "https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/overstromingsgevoelige_gebieden_fluviaal/MapServer/WMSServer"


def test_hit_returns_properties_with_layer_name():
    client = FixtureClient([("GetFeatureInfo", "watertoets_fluviaal_hit.json")])
    rows = wms_gfi.feature_info_at_point(client, URL, "0", 102000.0, 191500.0)
    assert rows[0]["gridcode"] == "3"
    assert rows[0]["layerName"].startswith("Overstromingsgevoelige")
    call = client.calls[0]
    assert "bbox=101950%2C191450%2C102050%2C191550" in call and "info_format=application%2Fgeo%2Bjson" in call


def test_empty_response_gives_no_rows():
    client = FixtureClient([("GetFeatureInfo", "watertoets_pluviaal_empty.json")])
    assert wms_gfi.feature_info_at_point(client, URL, "0", 104326.0, 192506.0) == []
