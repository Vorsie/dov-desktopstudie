from __future__ import annotations

import pytest

from desktopstudie.core.services import virtuele_boring as vb
from tests.core.conftest import FixtureClient


def test_doorprik_joins_data_with_layer_metadata():
    client = FixtureClient([("doorprik/g3dv3_F", "vb_g3dv3_F.json")])
    bh = vb.fetch_virtual_borehole(client, 104326.0, 192506.0, "g3dv3_F")
    assert bh.model == "g3dv3_F"
    assert bh.layers[0].code == "g3dv3_F_2"
    assert bh.layers[0].name == "Formatie van Gent"
    assert bh.layers[0].color == "#FFFF00"
    assert "dekzand" in bh.layers[0].texture
    assert bh.surface_mtaw == pytest.approx(14.62)
    assert "x=104326" in client.calls[0] and "crs=EPSG%3A31370" in client.calls[0]


def test_period_model_exposes_quaternary_base():
    client = FixtureClient([("doorprik/g3dv3_P", "vb_g3dv3_P.json")])
    bh = vb.fetch_virtual_borehole(client, 104326.0, 192506.0, "g3dv3_P")
    base = vb.base_of(bh, "Quartair")
    assert base is not None and base < bh.surface_mtaw


def test_unknown_layer_gets_grey_fallback():
    payload = {"data": [{"name": "x_9", "top": 5.0, "base": 1.0, "thickness": 4.0}], "layers": []}
    bh = vb.parse_doorprik(payload, 0.0, 0.0, "x")
    assert bh.layers[0].color == "#cccccc" and bh.layers[0].name == "x_9"


def test_layers_named_matches_case_insensitively_and_by_prefix():
    client = FixtureClient([("doorprik/g3dv3_F", "vb_g3dv3_F.json")])
    bh = vb.fetch_virtual_borehole(client, 104326.0, 192506.0, "g3dv3_F")
    by_lower = vb.layers_named(bh, "formatie van gent")
    by_prefix = vb.layers_named(bh, "Formatie")
    assert by_lower and by_lower[0].name == "Formatie van Gent"
    assert by_prefix and by_prefix[0].name == "Formatie van Gent"


def test_thickness_falls_back_to_top_minus_base_when_none():
    payload = {"data": [{"name": "x_9", "top": 5.0, "base": 1.0, "thickness": None}], "layers": []}
    bh = vb.parse_doorprik(payload, 0.0, 0.0, "x")
    assert bh.layers[0].thickness_m == pytest.approx(4.0)


@pytest.mark.live
def test_live_hcov_model():
    from desktopstudie.core.services.http import HttpClient

    bh = vb.fetch_virtual_borehole(HttpClient(), 104326.0, 192506.0, "hcovv2_S")
    assert bh.layers
    assert bh.layers[0].name != bh.layers[0].code
    assert bh.layers[0].color != vb.FALLBACK_COLOR
