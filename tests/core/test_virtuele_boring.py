from __future__ import annotations

import pytest

from desktopstudie.core.logging_util import Log
from desktopstudie.core.services import virtuele_boring as vb
from tests.core.conftest import FixtureClient, fixture_json

# The doorprik at 104326/192506 - the middle of the profile line - in its own top-to-bottom order.
ANCHOR_ORDER = ["g3dv3_F_2", "g3dv3_F_8", "g3dv3_F_31", "g3dv3_F_32", "g3dv3_F_33",
                "g3dv3_F_35", "g3dv3_F_36", "g3dv3_F_37", "g3dv3_F_42", "g3dv3_F_50"]


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


def test_profile_query_sends_both_endpoints_and_an_integer_resolution():
    client = FixtureClient([("profielbevraging/lagen", "vb_profile_g3dv3_F.json")])
    payload = vb.fetch_profile(client, "g3dv3_F", (104126.0, 192506.0), (104526.0, 192506.0), 100.0)
    assert len(payload["data"]) == 5
    call = client.calls[0]
    assert "lagenmodel/g3dv3_F/profielbevraging/lagen" in call
    assert "xValues=104126.00%2C104526.00" in call
    assert "yValues=192506.00%2C192506.00" in call
    assert "resolution=100" in call


def test_an_empty_profile_answer_is_warned_about_not_silently_returned():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([("profielbevraging", b'{"data": [], "layers": []}')])
    payload = vb.fetch_profile(client, "g3dv3_F", (0.0, 0.0), (100.0, 0.0), 10.0, log=log)
    assert payload["data"] == []
    assert any("profiel" in m and "leeg" in m for m in messages)


def test_profile_columns_stack_downwards_from_the_given_surface():
    profile = vb.parse_profile(fixture_json("vb_profile_g3dv3_F.json"), "g3dv3_F", ANCHOR_ORDER,
                               lambda along: 14.62 - along / 1000.0)
    assert profile.model == "g3dv3_F"
    assert profile.resolution_m == 100.0  # the payload's own sampling step
    assert [c.along_m for c in profile.columns] == [0.0, 100.0, 200.0, 300.0, 400.0]
    column = profile.columns[2]  # dist 200 m: the spot the doorprik fixture was taken at
    assert column.surface_mtaw == pytest.approx(14.42)
    assert column.layers[0].top_mtaw == pytest.approx(column.surface_mtaw)
    for layer in column.layers:
        assert layer.base_mtaw == pytest.approx(layer.top_mtaw - layer.thickness_m)
    for upper, lower in zip(column.layers, column.layers[1:]):
        assert lower.top_mtaw == pytest.approx(upper.base_mtaw)  # contiguous, no gaps
    assert [layer.code for layer in column.layers] == ANCHOR_ORDER  # order respected
    assert column.layers[0].name == "Formatie van Gent" and column.layers[0].color == "#FFFF00"
    assert "dekzanden" in column.layers[0].texture


def test_layers_with_zero_thickness_are_left_out_of_the_column():
    profile = vb.parse_profile(fixture_json("vb_profile_g3dv3_F.json"), "g3dv3_F", ANCHOR_ORDER, lambda a: 14.62)
    assert all(layer.thickness_m > 0 for column in profile.columns for layer in column.layers)
    # every record lists all 50 model codes; only the 9-10 with a thickness make it into the column
    assert [len(column.layers) for column in profile.columns] == [10, 9, 10, 9, 10]
    assert not any(layer.code in ("dist", "INV") for column in profile.columns for layer in column.layers)


def test_a_unit_the_anchor_lacks_is_stacked_at_its_own_place_not_below_the_deepest_unit():
    # At dist 0 the profile has g3dv3_F_4 (Formatie van Arenberg en Stokkem, Quaternary), which the
    # anchor doorprik does not: it belongs just under g3dv3_F_2, not under the Silurian at the base.
    profile = vb.parse_profile(fixture_json("vb_profile_g3dv3_F.json"), "g3dv3_F", ANCHOR_ORDER, lambda a: 14.62)
    codes = [layer.code for layer in profile.columns[0].layers]
    assert codes[0] == "g3dv3_F_4"  # g3dv3_F_2 is absent here, so the next shallowest unit is on top
    assert codes[1] == "g3dv3_F_8"
    assert codes[-1] == "g3dv3_F_50"


def test_an_unknown_profile_code_gets_the_grey_fallback_colour():
    payload = {"data": [{"dist": 0.0, "INV": 0.0, "x_9": 4.0, "x_10": 0.0}], "layers": [], "resolution": 5}
    profile = vb.parse_profile(payload, "x", [], lambda along: 3.0)
    layer = profile.columns[0].layers[0]
    assert layer.code == "x_9" and layer.name == "x_9" and layer.color == vb.FALLBACK_COLOR
    assert (layer.top_mtaw, layer.base_mtaw) == (3.0, -1.0)


@pytest.mark.live
def test_live_hcov_model():
    from desktopstudie.core.services.http import HttpClient

    bh = vb.fetch_virtual_borehole(HttpClient(), 104326.0, 192506.0, "hcovv2_S")
    assert bh.layers
    assert bh.layers[0].name != bh.layers[0].code
    assert bh.layers[0].color != vb.FALLBACK_COLOR


@pytest.mark.live
def test_live_profile():
    from desktopstudie.core.services.http import HttpClient

    payload = vb.fetch_profile(HttpClient(), "g3dv3_F", (104126.0, 192506.0), (104526.0, 192506.0), 100.0)
    assert [record["dist"] for record in payload["data"]] == [0.0, 100.0, 200.0, 300.0, 400.0]
    profile = vb.parse_profile(payload, "g3dv3_F", ANCHOR_ORDER, lambda along: 14.62)
    assert len(profile.columns) == 5
    assert profile.columns[2].layers[0].top_mtaw == pytest.approx(14.62)
    assert all(layer.color != vb.FALLBACK_COLOR for layer in profile.columns[2].layers)
