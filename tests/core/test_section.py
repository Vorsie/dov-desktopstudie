from __future__ import annotations

import json

import pytest

from desktopstudie.core import parallel
from desktopstudie.core import section as s
from desktopstudie.core.logging_util import Log
from desktopstudie.core.model import Cpt, StudyZone
from desktopstudie.core.services.http import HttpError
from tests.core.conftest import FixtureClient, fixture_bytes

LINE = ((104126.0, 192506.0), (104526.0, 192506.0))
ANCHOR = ("doorprik/g3dv3_F", "vb_g3dv3_F.json")
PROFILE = ("profielbevraging/lagen", "vb_profile_g3dv3_F.json")


def _client(*first):
    """Routes for both calls build_section makes; `first` wins over them (route order decides)."""
    return FixtureClient(list(first) + [PROFILE, ANCHOR])


def _cpt(number, x, y):
    return Cpt(permkey=number, number=number, x=x, y=y, z_mtaw=10.0, depth_m=20.0, date=None, method=None,
               cone=None, contractor=None, project=None, url="", distance_m=0.0)


def test_default_line_is_extended_longest_axis(gent_ring):
    zone = StudyZone(ring=gent_ring, name="z")
    p, q = s.section_line(zone, extension_m=100.0)
    assert s.geometry.distance(p, q) == pytest.approx(200.0 * 2 ** 0.5 + 200.0)


def test_user_line_wins_over_default(gent_ring):
    zone = StudyZone(ring=gent_ring, name="z", section_line=((0.0, 0.0), (10.0, 0.0)))
    assert s.section_line(zone, extension_m=100.0) == ((0.0, 0.0), (10.0, 0.0))


def test_build_section_samples_virtual_boreholes_and_projects_cpts(gent_ring):
    client = _client()
    zone = StudyZone(ring=gent_ring, name="z")
    cpts = [_cpt("in", 104326.0, 192520.0), _cpt("far", 104326.0, 192700.0)]
    sec = s.build_section(client, LINE, zone, cpts, [], [], n_points=5, corridor_m=50.0, model="g3dv3_F")
    assert len(sec.boreholes) == 5
    assert sec.failed_points == 0
    assert [p.label for p in sec.projected] == ["in"]
    assert sec.projected[0].along_m == pytest.approx(200.0)
    assert (sec.zone_from_m, sec.zone_to_m) == pytest.approx((100.0, 300.0))
    assert len(client.calls) == 6  # five doorprik anchors plus one profile query


def test_failed_point_is_skipped_and_counted(gent_ring):
    # LINE sampled at n_points=5 puts x=104226.00 exactly on the second point; route it to a
    # failure while every other point still resolves via the normal fixture.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = _client(("x=104226.00", HttpError("url", 500, "boom")))
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F", log=log)
    assert len(sec.boreholes) == 4
    assert sec.failed_points == 1
    assert any("104226/192506" in m for m in messages), messages


def test_cancelling_is_heard_while_the_doorprik_points_are_fetched(gent_ring):
    """Annuleren hoort binnen de doorsnedefase gehoord te worden. De punten zijn de langste
    reeks netwerkoproepen van die fase; wie daar niet pollt, laat de gebruiker de hele fase
    uitzitten nadat hij op Annuleren drukte."""
    client = _client()
    zone = StudyZone(ring=gent_ring, name="z")

    with pytest.raises(parallel.Cancelled):
        s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0,
                        model="g3dv3_F", should_cancel=lambda: True)


def test_all_points_failing_raises(gent_ring):
    client = FixtureClient([("doorprik/g3dv3_F", HttpError("url", 500, "boom"))])
    zone = StudyZone(ring=gent_ring, name="z")
    with pytest.raises(RuntimeError):
        s.build_section(client, LINE, zone, [], [], [], n_points=3, corridor_m=50.0, model="g3dv3_F")


def test_zone_extent_is_clipped_to_line(gent_ring):
    # gent_ring is a 200 x 200 m square; this line is a 50 m stretch through its middle, so the
    # unclipped ring-vertex projections would run well outside [0, length].
    line = ((104300.0, 192506.0), (104350.0, 192506.0))
    client = _client()
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, line, zone, [], [], [], n_points=2, corridor_m=50.0, model="g3dv3_F")
    assert (sec.zone_from_m, sec.zone_to_m) == (0.0, 50.0)


def test_the_profile_is_sampled_along_the_whole_line_and_hangs_from_the_model_datum(gent_ring):
    client = _client()
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F")
    assert sec.profile is not None
    assert sec.profile.model == "g3dv3_F"
    assert sec.profile.resolution_m == 10.0  # max(5, 400 m / 40)
    profile_call = next(c for c in client.calls if "profielbevraging" in c)
    assert "resolution=10" in profile_call
    assert "xValues=104126.00%2C104526.00" in profile_call
    # every column hangs from the profile's own datum, and at the chainage where a doorprik anchor
    # sits the two agree: column 2 is at 200 m, the midpoint the doorprik fixture was taken at
    assert sec.profile.columns[2].surface_mtaw == pytest.approx(sec.boreholes[2].surface_mtaw)
    assert all(column.layers[0].top_mtaw == pytest.approx(column.surface_mtaw)
               for column in sec.profile.columns)
    assert [round(column.surface_mtaw, 2) for column in sec.profile.columns] == [8.01, 11.35, 14.62,
                                                                                 17.48, 21.16]
    # and stacks in the anchor borehole's own top-to-bottom order
    assert sec.profile.columns[2].layers[0].code == sec.boreholes[0].layers[0].code
    assert len(sec.boreholes) == 5  # the doorprik anchors stay alongside the profile


def test_a_failing_profile_leaves_the_doorprik_section_intact(gent_ring):
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = _client(("profielbevraging", HttpError("url", 500, "boom")))
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F", log=log)
    assert sec.profile is None
    assert len(sec.boreholes) == 5
    assert any("profiel" in m for m in messages)


def test_with_profile_false_never_calls_the_profile_endpoint(gent_ring):
    client = FixtureClient([ANCHOR])
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=3, corridor_m=50.0, model="g3dv3_F",
                          with_profile=False)
    assert sec.profile is None
    assert not any("profielbevraging" in call for call in client.calls)


def test_a_profile_answer_without_a_datum_falls_back_to_the_doorprik_anchors(gent_ring):
    # strip minValue: with no floor of its own the profile has to hang on the anchors' surface
    payload = json.loads(fixture_bytes("vb_profile_g3dv3_F.json").decode("utf-8"))
    payload.pop("minValue")
    client = _client(("profielbevraging", json.dumps(payload).encode("utf-8")))
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F")
    assert sec.profile is not None
    # the anchors all come from the same fixture, so their interpolated surface is flat at 14.62
    assert all(column.surface_mtaw == pytest.approx(14.62) for column in sec.profile.columns)


def test_the_profile_carries_the_section_when_every_doorprik_anchor_fails(gent_ring):
    # Every anchor is down but the profile answers: the section is still worth drawing, because the
    # profile brings both the layers and (via its own datum) the elevations to hang them on.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([PROFILE, ("doorprik/g3dv3_F", HttpError("url", 500, "boom"))])
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F", log=log)
    assert sec.boreholes == []
    assert sec.failed_points == 5
    assert sec.profile is not None and len(sec.profile.columns) == 5
    assert sec.profile.columns[2].surface_mtaw == pytest.approx(14.62)
    # with no anchor to take an order from, the units stack on their numeric suffix
    codes = [layer.code for layer in sec.profile.columns[2].layers]
    assert codes == sorted(codes, key=lambda code: int(code.rsplit("_", 1)[-1]))
    assert any("mislukt" in m for m in messages)


def test_the_section_raises_only_when_both_the_anchors_and_the_profile_are_gone(gent_ring):
    client = FixtureClient([("profielbevraging", HttpError("url", 500, "boom")),
                            ("doorprik/g3dv3_F", HttpError("url", 500, "boom"))])
    zone = StudyZone(ring=gent_ring, name="z")
    with pytest.raises(RuntimeError):
        s.build_section(client, LINE, zone, [], [], [], n_points=3, corridor_m=50.0, model="g3dv3_F")


def test_without_anchors_a_profile_that_has_no_datum_cannot_carry_the_section(gent_ring):
    payload = json.loads(fixture_bytes("vb_profile_g3dv3_F.json").decode("utf-8"))
    payload.pop("minValue")  # nothing to hang the columns on, and no anchor either
    client = FixtureClient([("profielbevraging", json.dumps(payload).encode("utf-8")),
                            ("doorprik/g3dv3_F", HttpError("url", 500, "boom"))])
    zone = StudyZone(ring=gent_ring, name="z")
    with pytest.raises(RuntimeError):
        s.build_section(client, LINE, zone, [], [], [], n_points=3, corridor_m=50.0, model="g3dv3_F")
