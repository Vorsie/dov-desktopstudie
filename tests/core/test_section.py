from __future__ import annotations

import pytest

from desktopstudie.core import section as s
from desktopstudie.core.logging_util import Log
from desktopstudie.core.model import Cpt, StudyZone
from desktopstudie.core.services.http import HttpError
from tests.core.conftest import FixtureClient

LINE = ((104126.0, 192506.0), (104526.0, 192506.0))


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
    client = FixtureClient([("doorprik/g3dv3_F", "vb_g3dv3_F.json")])
    zone = StudyZone(ring=gent_ring, name="z")
    cpts = [_cpt("in", 104326.0, 192520.0), _cpt("far", 104326.0, 192700.0)]
    sec = s.build_section(client, LINE, zone, cpts, [], [], n_points=5, corridor_m=50.0, model="g3dv3_F")
    assert len(sec.boreholes) == 5
    assert sec.failed_points == 0
    assert [p.label for p in sec.projected] == ["in"]
    assert sec.projected[0].along_m == pytest.approx(200.0)
    assert (sec.zone_from_m, sec.zone_to_m) == pytest.approx((100.0, 300.0))
    assert len(client.calls) == 5


def test_failed_point_is_skipped_and_counted(gent_ring):
    # LINE sampled at n_points=5 puts x=104226.00 exactly on the second point; route it to a
    # failure while every other point still resolves via the normal fixture.
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="WARNING")
    client = FixtureClient([
        ("x=104226.00", HttpError("url", 500, "boom")),
        ("doorprik/g3dv3_F", "vb_g3dv3_F.json"),
    ])
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, LINE, zone, [], [], [], n_points=5, corridor_m=50.0, model="g3dv3_F", log=log)
    assert len(sec.boreholes) == 4
    assert sec.failed_points == 1
    assert any("mislukt" in m for m in messages)


def test_all_points_failing_raises(gent_ring):
    client = FixtureClient([("doorprik/g3dv3_F", HttpError("url", 500, "boom"))])
    zone = StudyZone(ring=gent_ring, name="z")
    with pytest.raises(RuntimeError):
        s.build_section(client, LINE, zone, [], [], [], n_points=3, corridor_m=50.0, model="g3dv3_F")


def test_zone_extent_is_clipped_to_line(gent_ring):
    # gent_ring is a 200 x 200 m square; this line is a 50 m stretch through its middle, so the
    # unclipped ring-vertex projections would run well outside [0, length].
    line = ((104300.0, 192506.0), (104350.0, 192506.0))
    client = FixtureClient([("doorprik/g3dv3_F", "vb_g3dv3_F.json")])
    zone = StudyZone(ring=gent_ring, name="z")
    sec = s.build_section(client, line, zone, [], [], [], n_points=2, corridor_m=50.0, model="g3dv3_F")
    assert (sec.zone_from_m, sec.zone_to_m) == (0.0, 50.0)
