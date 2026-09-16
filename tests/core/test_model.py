from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from desktopstudie.core import geometry as g
from desktopstudie.core import model as m


def test_zone_derives_centroid_bbox_and_wkt(gent_ring):
    zone = m.StudyZone(ring=gent_ring, name="Gent test", radius_m=500.0)
    assert zone.centroid == pytest.approx((104326.0, 192506.0))
    assert zone.bbox == (104226.0, 192406.0, 104426.0, 192606.0)
    assert zone.wkt.startswith("POLYGON((")
    assert zone.area_m2 == 40000.0


def test_a_zone_around_a_point_is_a_circle_named_after_the_address_or_the_point():
    """Adres of X/Y, in de plugin en in de scripts: één constructor. Met een adres heet de zone
    naar het adres en draagt ze het; zonder heet ze naar het coördinaat, op de meter afgerond."""
    zone = m.StudyZone.around_point(104326.0, 192506.0, 50.0, 600.0,
                                    address="Kortrijksesteenweg 100, 9000 Gent")
    assert zone.name == zone.address == "Kortrijksesteenweg 100, 9000 Gent"
    assert zone.radius_m == 600.0
    assert len(zone.ring) >= 32
    assert all(abs(g.distance(point, (104326.0, 192506.0)) - 50.0) < 1e-6 for point in zone.ring)

    bare = m.StudyZone.around_point(104326.4, 192506.0, 50.0, 500.0)
    assert bare.name == "104326/192506" and bare.address is None


def test_study_result_round_trips_to_json(gent_ring, tmp_path):
    zone = m.StudyZone(ring=gent_ring, name="Gent test")
    cpt = m.Cpt(permkey="1965-039716", number="GEO-64/306-SIX", x=104007.0, y=192682.0, z_mtaw=6.26,
                depth_m=20.4, date="1965-02-17", method="discontinu mechanisch", cone="M4",
                contractor="RIG", project="GEO-64/306",
                url="https://www.dov.vlaanderen.be/data/sondering/1965-039716",
                distance_m=210.0,
                profile=m.CptProfile(depth_m=[0.2, 0.4], qc_mpa=[1.0, 2.0], fs_kpa=[None, 10.0],
                                      u_kpa=[None, None]))
    result = m.StudyResult(zone=zone, created_at="2026-09-15T10:00:00", cpts=[cpt])
    result.signaleringen.append(m.Signalering(code="geen_cpt", fact="0 CPT", source="DOV", advice="onderzoek",
                                                severity="aandacht"))
    path = tmp_path / "studie.json"
    result.write_json(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["zone"]["name"] == "Gent test"
    assert data["cpts"][0]["profile"]["qc_mpa"] == [1.0, 2.0]
    assert data["signaleringen"][0]["code"] == "geen_cpt"
    assert data["summary"]["n_cpts"] == 1


def test_virtual_borehole_helpers():
    vb = m.VirtualBorehole(x=1.0, y=2.0, model="g3dv3_F", layers=[
        m.VbLayer(code="g3dv3_F_1", name="Antropogeen", top_mtaw=10.0, base_mtaw=9.0, thickness_m=1.0,
                  color="#EA152E", texture="opvulling"),
        m.VbLayer(code="g3dv3_F_2", name="Formatie van Gent", top_mtaw=9.0, base_mtaw=5.0, thickness_m=4.0,
                  color="#FFFF00", texture="eolische dekzanden"),
    ])
    assert vb.surface_mtaw == 10.0
    assert vb.depth_of(vb.layers[1]) == (1.0, 5.0)


def test_representative_point_is_inside_l_shaped_zone():
    ring = [(0.0, 0.0), (200.0, 0.0), (200.0, 60.0), (60.0, 60.0), (60.0, 200.0), (0.0, 200.0)]
    zone = m.StudyZone(ring=ring, name="L-zone")
    assert g.point_in_ring(*zone.representative_point, ring)


def test_write_json_handles_numpy_scalars_paths_and_nested_section(gent_ring, tmp_path):
    zone = m.StudyZone(ring=gent_ring, name="Gent test")
    layer = m.VbLayer(code="g3dv3_F_1", name="Antropogeen", top_mtaw=10.0, base_mtaw=9.0, thickness_m=1.0,
                       color="#EA152E", texture="opvulling")
    vb = m.VirtualBorehole(x=104326.0, y=192506.0, model="g3dv3_F", layers=[layer])
    section = m.Section(line=((0.0, 0.0), (10.0, 0.0)), boreholes=[vb],
                         projected=[m.ProjectedPoint("cpt", "S1", 5.0, 1.0, 10.0, 20.0)],
                         zone_from_m=2.0, zone_to_m=8.0)
    result = m.StudyResult(zone=zone, created_at="2026-09-15T10:00:00",
                            relief=(np.float32(8.0), np.float32(10.5), np.float32(9.0)),
                            figures={"section": Path("figuren/section.png")},
                            section=section)
    result.figures["arr"] = np.array([1.0, 2.0])  # type mismatch is deliberate: pins array serialisation
    path = tmp_path / "studie.json"
    result.write_json(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["relief"] == [8.0, 10.5, 9.0]
    assert data["figures"]["section"].endswith("section.png")
    assert data["figures"]["arr"] == [1.0, 2.0]
    assert data["section"]["boreholes"][0]["layers"][0]["name"] == layer.name
    assert data["section"]["line"] == [[0.0, 0.0], [10.0, 0.0]]


def test_gw_filter_latest_depth_is_surface_minus_level():
    filt = m.GwFilter(gw_id="1985-007948", filter_no="1", x=0.0, y=0.0, z_mtaw=10.0, aquifer=None,
                       filter_base_m=None, filter_length_m=None, network=None, url="", report_url=None,
                       distance_m=0.0, latest=m.GwLevel(date="2024-01-01", level_mtaw=8.5))
    assert filt.latest_depth_m == pytest.approx(1.5)

    filt_no_surface = dataclasses.replace(filt, z_mtaw=None)
    assert filt_no_surface.latest_depth_m is None


def test_depth_of_with_zero_surface_elevation():
    vb = m.VirtualBorehole(x=0.0, y=0.0, model="g3dv3_F", layers=[
        m.VbLayer(code="a", name="Antropogeen", top_mtaw=0.0, base_mtaw=-2.0, thickness_m=2.0,
                  color="#000000", texture="opvulling"),
        m.VbLayer(code="b", name="Formatie van Gent", top_mtaw=-2.0, base_mtaw=-5.0, thickness_m=3.0,
                  color="#FFFF00", texture="eolische dekzanden"),
    ])
    assert vb.depth_of(vb.layers[1]) == (2.0, 5.0)


def test_section_carries_a_stacked_profile_that_round_trips_to_json(gent_ring, tmp_path):
    layer = m.VbLayer(code="g3dv3_F_31", name="Formatie van Maldegem", top_mtaw=10.84, base_mtaw=-11.34,
                      thickness_m=22.18, color="#93AB71", texture="klei")
    profile = m.SectionProfile(model="g3dv3_F", resolution_m=10.0, columns=[
        m.ProfileColumn(along_m=0.0, surface_mtaw=14.62, layers=[layer]),
        m.ProfileColumn(along_m=10.0, surface_mtaw=14.50, layers=[layer]),
    ])
    section = m.Section(line=((0.0, 0.0), (10.0, 0.0)), boreholes=[], projected=[], zone_from_m=0.0,
                        zone_to_m=10.0, profile=profile)
    assert section.failed_points == 0  # profile is the last field, so failed_points keeps its default
    result = m.StudyResult(zone=m.StudyZone(ring=gent_ring, name="z"), created_at="t", section=section)
    path = tmp_path / "studie.json"
    result.write_json(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["section"]["profile"]["resolution_m"] == 10.0
    assert data["section"]["profile"]["columns"][1]["along_m"] == 10.0
    assert data["section"]["profile"]["columns"][0]["layers"][0]["code"] == "g3dv3_F_31"


def test_a_section_without_a_profile_defaults_to_none():
    section = m.Section(line=((0.0, 0.0), (10.0, 0.0)), boreholes=[], projected=[], zone_from_m=0.0, zone_to_m=10.0)
    assert section.profile is None
