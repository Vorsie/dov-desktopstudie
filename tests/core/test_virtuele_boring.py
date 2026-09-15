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


def test_a_doorprik_without_layers_is_warned_about_not_silently_returned():
    # "Buiten het model" answers with an empty data[] and HTTP 200; without a WARNING the study
    # would show an empty column as if the ground there had no geology.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([("doorprik/g3dv3_F", b'{"data": [], "layers": []}')])
    bh = vb.fetch_virtual_borehole(client, 250000.0, 150000.0, "g3dv3_F", log=log)
    assert bh.layers == []
    assert any("virtuele boring g3dv3_F op 250000/150000" in m and "geen lagen" in m for m in messages)


def test_a_doorprik_with_layers_is_not_warned_about():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([("doorprik/g3dv3_F", "vb_g3dv3_F.json")])
    bh = vb.fetch_virtual_borehole(client, 104326.0, 192506.0, "g3dv3_F", log=log)
    assert bh.layers and messages == []


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


def test_the_profile_answer_carries_its_own_surface_datum():
    # DOV pads every column of a profile answer down to one common floor (minValue), so that floor
    # plus the column's own thickness sum is the modelled surface. At dist 200 m that has to be the
    # 14.62 mTAW the doorprik reports for the very same spot.
    surface_at = vb.profile_surface_at(fixture_json("vb_profile_g3dv3_F.json"))
    assert surface_at is not None
    assert surface_at(200.0) == pytest.approx(14.62)
    assert surface_at(0.0) == pytest.approx(8.01)
    assert surface_at(400.0) == pytest.approx(21.16)
    assert surface_at(50.0) == pytest.approx(9.68)  # halfway between two records: interpolated


def test_a_profile_answer_without_a_floor_has_no_surface_of_its_own():
    assert vb.profile_surface_at({"data": [{"dist": 0.0, "x_1": 2.0}], "layers": []}) is None
    assert vb.profile_surface_at({"data": [], "layers": [], "minValue": -10.0}) is None


def _padded_payload(**overrides):
    """A knownLowBoundary answer in the shape hcovv1 returns: the column stops at its real base
    (-9) and INV pads it down to the common floor (-10)."""
    payload = {"minValue": -10.0, "maxValue": 5.0, "knownLowBoundary": True, "layers": [],
               "data": [{"dist": 0.0, "INV": 1.0, "h_1": 4.0, "h_2": 10.0, "h_3": 0.0}]}
    payload.update(overrides)
    return payload


def test_inv_padding_counts_towards_the_surface_datum():
    # hcovv1 stops at a real model base and pads the rest of the column down to the common floor
    # with INV. That padding occupies vertical space, so leaving it out of the sum puts the surface
    # metres too low: live check 2026-09-15 on the fixture line gave doorprik tops
    # 8.38/11.55/14.59/17.79/21.36, which equal minValue + the sum INCLUDING INV.
    surface_at = vb.profile_surface_at(_padded_payload())
    assert surface_at is not None
    assert surface_at(0.0) == pytest.approx(5.0)  # -10 + (1 INV + 4 + 10), not -10 + 14


def test_inv_padding_is_never_a_drawn_layer():
    profile = vb.parse_profile(_padded_payload(), "hcovv1", [], lambda along: 5.0)
    column = profile.columns[0]
    assert [layer.code for layer in column.layers] == ["h_1", "h_2"]
    assert column.layers[-1].base_mtaw == pytest.approx(-9.0)  # the real base; the INV metre is not drawn


def test_a_surface_datum_that_contradicts_maxvalue_is_refused_and_warned_about():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    # the answer claims a highest surface of 99 mTAW while its own columns stack to 5
    assert vb.profile_surface_at(_padded_payload(maxValue=99.0), log=log) is None
    assert any("maxValue" in m for m in messages)


def test_a_surface_datum_inside_the_maxvalue_tolerance_is_accepted():
    assert vb.profile_surface_at(_padded_payload(maxValue=5.04)) is not None   # 0.04 m: within 0.05
    assert vb.profile_surface_at(_padded_payload(maxValue=5.20)) is None       # 0.20 m: too far off


def test_a_column_outside_the_model_is_skipped_and_warned_about():
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    payload = {"minValue": -10.0, "maxValue": -6.0, "layers": [], "data": [
        {"dist": 0.0, "h_1": 4.0}, {"dist": 50.0, "h_1": 0.0, "INV": 0.0}, {"dist": 100.0, "h_1": 4.0}]}
    profile = vb.parse_profile(payload, "x", [], lambda along: -6.0, log=log)
    assert [column.along_m for column in profile.columns] == [0.0, 100.0]  # no column at 50 m
    assert any("50" in m and "1 kolom" in m for m in messages)


def test_a_column_with_only_padding_is_dropped():
    # INV is bottom padding, never a drawable layer, so a record whose only positive entry is INV
    # has no geology either: it lies outside the model exactly like an all-zero column and must be
    # dropped, not drawn as a zero-layer column hanging at minValue + INV.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    payload = {"minValue": -10.0, "maxValue": -6.0, "layers": [], "data": [
        {"dist": 0.0, "h_1": 4.0, "INV": 0.0},
        {"dist": 50.0, "h_1": 0.0, "INV": 1.5},
        {"dist": 100.0, "h_1": 4.0, "INV": 0.0}]}
    profile = vb.parse_profile(payload, "x", [], lambda along: -6.0, log=log)
    assert [column.along_m for column in profile.columns] == [0.0, 100.0]
    assert any("50" in m and "1 kolom" in m for m in messages)
    surface_at = vb.profile_surface_at(payload)
    assert surface_at(50.0) == pytest.approx(-6.0)  # bridged, not -8.5 (the floor plus the padding)


def test_a_column_outside_the_model_carries_no_surface_either():
    payload = {"minValue": -10.0, "maxValue": -6.0, "layers": [], "data": [
        {"dist": 0.0, "h_1": 4.0}, {"dist": 50.0, "h_1": 0.0}]}
    surface_at = vb.profile_surface_at(payload)
    assert surface_at is not None
    assert surface_at(0.0) == pytest.approx(-6.0)
    assert surface_at(50.0) == pytest.approx(-6.0)  # bridged from the usable column, not -10 (the floor)
    assert vb.profile_surface_at({"minValue": -10.0, "layers": [],
                                  "data": [{"dist": 0.0, "h_1": 0.0}]}) is None  # nothing usable at all


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
    surface_at = vb.profile_surface_at(payload)
    profile = vb.parse_profile(payload, "g3dv3_F", ANCHOR_ORDER, surface_at)
    assert len(profile.columns) == 5
    # the doorprik at the midpoint of the line is the same spot as the column at dist 200 m
    doorprik = vb.fetch_virtual_borehole(HttpClient(), 104326.0, 192506.0, "g3dv3_F")
    assert profile.columns[2].layers[0].top_mtaw == pytest.approx(doorprik.surface_mtaw, abs=0.01)
    assert all(layer.color != vb.FALLBACK_COLOR for layer in profile.columns[2].layers)


@pytest.mark.live
def test_live_hcovv1_profile_datum_matches_the_doorprik_at_every_anchor():
    from desktopstudie.core.services.http import HttpClient

    client = HttpClient()
    p, q = (104126.0, 192506.0), (104526.0, 192506.0)
    payload = vb.fetch_profile(client, "hcovv1", p, q, 100.0)
    assert payload["knownLowBoundary"] is True
    assert any(record.get("INV", 0.0) > 0 for record in payload["data"]), "hcovv1 pads with INV"
    surface_at = vb.profile_surface_at(payload)
    assert surface_at is not None
    for i in range(5):
        along = i * 100.0
        x = p[0] + (q[0] - p[0]) * along / 400.0
        doorprik = vb.fetch_virtual_borehole(client, x, p[1], "hcovv1")
        assert surface_at(along) == pytest.approx(doorprik.surface_mtaw, abs=0.02)
