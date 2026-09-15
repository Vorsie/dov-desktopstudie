# tests/core/test_model.py
from __future__ import annotations

import json

import pytest

from desktopstudie.core import model as m


def test_zone_derives_centroid_bbox_and_wkt(gent_ring):
    zone = m.StudyZone(ring=gent_ring, name="Gent test", radius_m=500.0)
    assert zone.centroid == pytest.approx((104326.0, 192506.0))
    assert zone.bbox == (104226.0, 192406.0, 104426.0, 192606.0)
    assert zone.wkt.startswith("POLYGON((")
    assert zone.area_m2 == 40000.0


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
