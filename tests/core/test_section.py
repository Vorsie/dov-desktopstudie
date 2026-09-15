from __future__ import annotations

import pytest

from desktopstudie.core import section as s
from desktopstudie.core.model import Cpt, StudyZone
from tests.core.conftest import FixtureClient


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
    zone = StudyZone(ring=gent_ring, name="z", section_line=((104126.0, 192506.0), (104526.0, 192506.0)))
    cpts = [_cpt("in", 104326.0, 192520.0), _cpt("far", 104326.0, 192700.0)]
    sec = s.build_section(client, zone, cpts, [], [], n_points=5, corridor_m=50.0, model="g3dv3_F")
    assert len(sec.boreholes) == 5
    assert [p.label for p in sec.projected] == ["in"]
    assert sec.projected[0].along_m == pytest.approx(200.0)
    assert (sec.zone_from_m, sec.zone_to_m) == pytest.approx((100.0, 300.0))
    assert len(client.calls) == 5
