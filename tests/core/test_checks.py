from __future__ import annotations

from desktopstudie.core import checks
from desktopstudie.core.model import (
    Cpt,
    GwFilter,
    GwLevel,
    MapFact,
    Provenance,
    StudyResult,
    StudyZone,
    VbLayer,
    VirtualBorehole,
)


def _result(gent_ring):
    return StudyResult(zone=StudyZone(ring=gent_ring, name="z"), created_at="t")


def _vb(model, *layers):
    return VirtualBorehole(x=0, y=0, model=model, layers=[
        VbLayer(code=c, name=n, top_mtaw=t, base_mtaw=b, thickness_m=t - b, color="#000", texture=tx)
        for c, n, t, b, tx in layers])


def test_anthropogenic_layer_in_virtual_borehole_is_flagged(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_L"] = _vb("g3dv3_L", ("g3dv3_L_1", "Antropogeen", 10.0, 8.5, "opvulling en ophoging"))
    codes = [s.code for s in checks.run_all(r)]
    assert "antropogeen" in codes


def test_clay_or_peat_within_10_m_below_surface_is_flagged_deeper_is_not(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_L"] = _vb("g3dv3_L",
        ("a", "Zand", 10.0, 4.0, "zand"),
        ("b", "Lid van Pittem", 4.0, -2.0, "klei en silt"),      # top at 6 m below surface -> flag
        ("c", "Diepe klei", -2.0, -20.0, "klei"))               # top at 12 m -> no flag
    sigs = [s for s in checks.run_all(r) if s.code == "slappe_laag"]
    assert len(sigs) == 1 and "Lid van Pittem" in sigs[0].fact


def test_shallow_tertiary_is_flagged_below_3_m(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_P"] = _vb(
        "g3dv3_P", ("p1", "Quartair", 10.0, 8.0, ""), ("p2", "Paleogeen", 8.0, -50.0, ""))
    assert any(s.code == "ondiep_tertiair" for s in checks.run_all(r))
    r.virtual_boreholes["g3dv3_P"] = _vb(
        "g3dv3_P", ("p1", "Quartair", 10.0, 5.0, ""), ("p2", "Paleogeen", 5.0, -50.0, ""))
    assert not any(s.code == "ondiep_tertiair" for s in checks.run_all(r))


def test_soil_map_wet_drainage_peat_texture_and_built_up_are_flagged(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("bodemkaart", "Bodemkaart", [
        {"Bodemtype": "Vep", "Textuurklasse_code": "V", "Drainageklasse_code": "e"},
        {"Bodemtype": "OB", "Textuurklasse_code": None, "Drainageklasse_code": None},
    ]))
    codes = [s.code for s in checks.run_all(r)]
    assert (codes.count("bodem_nat") == 1 and codes.count("bodem_veen_klei") == 1
            and codes.count("bodem_antropogeen") == 1)


def test_shallow_groundwater_uses_nearest_filter_with_a_level(gent_ring):
    r = _result(gent_ring)
    r.gw_filters = [
        GwFilter("far", "1", 0, 0, 10.0, None, None, None, None, "", None,
                 distance_m=400.0, latest=GwLevel("2024-01-01", 9.5)),
        GwFilter("near", "1", 0, 0, 10.0, None, None, None, None, "", None, distance_m=50.0, latest=None),
    ]
    sigs = [s for s in checks.run_all(r) if s.code == "ondiep_grondwater"]
    assert len(sigs) == 1 and "far" in sigs[0].fact and "0.5 m" in sigs[0].fact


def test_flood_erosion_shrink_swell_and_ovam_facts_are_flagged_when_present(gent_ring):
    r = _result(gent_ring)
    r.map_facts += [
        MapFact("watertoets_fluviaal", "Watertoets fluviaal", [{"gridcode": "3"}]),
        MapFact("watertoets_pluviaal", "Watertoets pluviaal", []),
        MapFact("erosie", "Erosie", [{"Erosieklasse_ALV": "zeer hoog"}]),
        MapFact("krimp_zwel", "Krimp-zwel", [{"hoofdlithologie": "klei/silt"}]),
        MapFact("ovam", "OVAM", [{"uitspraak": "Er is een orienterend bodemonderzoek nodig"}]),
    ]
    codes = [s.code for s in checks.run_all(r)]
    assert codes.count("overstroming") == 1 and "erosie" in codes and "krimp_zwel" in codes and "ovam" in codes


def test_no_cpt_within_radius_and_cpt_within_50_m(gent_ring):
    r = _result(gent_ring)
    assert any(s.code == "geen_cpt" for s in checks.run_all(r))
    r.cpts = [Cpt("k", "S1", 0, 0, None, 20.0, None, None, None, None, None, "", distance_m=30.0)]
    codes = [s.code for s in checks.run_all(r)]
    assert "geen_cpt" not in codes and "cpt_dichtbij" in codes


def test_relief_over_2_m_and_failed_sources_are_flagged(gent_ring):
    r = _result(gent_ring)
    r.relief = (8.0, 10.5, 9.0)
    r.provenance.append(Provenance("Bodemkaart", "https://x", "t", ok=False, message="timeout"))
    codes = [s.code for s in checks.run_all(r)]
    assert "relief" in codes and "bron_niet_beschikbaar" in codes
