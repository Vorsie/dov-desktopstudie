from __future__ import annotations

import pytest

from desktopstudie.core import catalogue, checks
from desktopstudie.core.model import (
    Cpt,
    GwFilter,
    GwLevel,
    MapFact,
    Provenance,
    Signalering,
    StudyResult,
    StudyZone,
    VbLayer,
    VirtualBorehole,
)
from tests.core.conftest import fixture_json


def _result(gent_ring):
    return StudyResult(zone=StudyZone(ring=gent_ring, name="z"), created_at="t")


def _vb(model, *layers):
    return VirtualBorehole(x=0, y=0, model=model, layers=[
        VbLayer(code=c, name=n, top_mtaw=t, base_mtaw=b, thickness_m=t - b, color="#000", texture=tx)
        for c, n, t, b, tx in layers])


def test_anthropogenic_layers_in_the_formation_model_are_summed(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_F"] = _vb(
        "g3dv3_F",
        ("g3dv3_F_1", "Antropogeen", 10.0, 8.5, "opvulling en ophoging"),
        ("g3dv3_F_2", "Antropogeen", 8.5, 8.0, "puin"),
        ("g3dv3_F_3", "Zand", 8.0, 0.0, "zand"),
    )
    sigs = [s for s in checks.run_all(r) if s.code == "antropogeen"]
    assert len(sigs) == 1
    assert "2.0 m" in sigs[0].fact  # 1.5 + 0.5
    assert "g3dv3_F" in sigs[0].fact


def test_clay_or_peat_within_10_m_below_surface_is_flagged_deeper_is_not(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_L"] = _vb("g3dv3_L",
        ("a", "Zand", 10.0, 4.0, "zand"),
        ("b", "Lid van Pittem", 4.0, -2.0, "klei en silt"),      # top at 6 m below surface -> flag
        ("c", "Diepe klei", -2.0, -20.0, "klei"))               # top at 12 m -> no flag
    sigs = [s for s in checks.run_all(r) if s.code == "slappe_laag"]
    assert len(sigs) == 1 and "Lid van Pittem" in sigs[0].fact


def test_soft_layer_match_is_whole_word_not_substring(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_L"] = _vb("g3dv3_L",
        ("a", "Laag A", 10.0, 8.0, "fijn kleirijkzand"),        # "klei" glued into another word -> no flag
        ("b", "Laag B", 8.0, 6.0, "fijn zand met silt"),        # "silt" alone is no longer a keyword -> no flag
        ("c", "Laag C", 6.0, 4.0, "klei, zand, grind"))         # "klei" as its own word -> flag
    sigs = [s for s in checks.run_all(r) if s.code == "slappe_laag"]
    assert len(sigs) == 1 and "Laag C" in sigs[0].fact


def test_shallow_tertiary_is_flagged_below_3_m(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_P"] = _vb(
        "g3dv3_P", ("p1", "Quartair", 10.0, 8.0, ""), ("p2", "Paleogeen", 8.0, -50.0, ""))
    assert any(s.code == "ondiep_tertiair" for s in checks.run_all(r))
    r.virtual_boreholes["g3dv3_P"] = _vb(
        "g3dv3_P", ("p1", "Quartair", 10.0, 5.0, ""), ("p2", "Paleogeen", 5.0, -50.0, ""))
    assert not any(s.code == "ondiep_tertiair" for s in checks.run_all(r))


def test_no_quartair_unit_in_the_period_model_flags_tertiary_at_surface(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_P"] = _vb("g3dv3_P", ("p1", "Paleogeen", 10.0, -50.0, ""))
    sigs = [s for s in checks.run_all(r) if s.code == "ondiep_tertiair"]
    assert len(sigs) == 1 and "Geen Quartair" in sigs[0].fact


def test_no_period_model_at_all_means_no_tertiary_flag(gent_ring):
    r = _result(gent_ring)
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


def test_soil_map_flags_antropogeen_via_generalised_legend_too(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("bodemkaart", "Bodemkaart", [
        {"Bodemtype": "Zcg", "Gegeneraliseerde_legende": "Antropogeen"},  # code alone would not match
    ]))
    codes = [s.code for s in checks.run_all(r)]
    assert codes.count("bodem_antropogeen") == 1


def test_bodemkaart_fixture_at_the_gent_zone_flags_antropogeen_only(gent_ring):
    data = fixture_json("wfs_bodemtypes_intersects.json")
    fields = catalogue.by_id("bodemkaart").fact_fields
    rows = [{k: f["properties"].get(k) for k in fields} for f in data["features"]]
    r = _result(gent_ring)
    r.map_facts.append(MapFact("bodemkaart", "Bodemkaart", rows))
    codes = [s.code for s in checks.run_all(r)]
    assert "bodem_antropogeen" in codes
    assert "bodem_nat" not in codes
    assert "bodem_veen_klei" not in codes


def test_shallow_groundwater_uses_nearest_filter_with_a_level(gent_ring):
    r = _result(gent_ring)
    r.gw_filters = [
        GwFilter("far", "1", 0, 0, 10.0, None, None, None, None, "", None,
                 distance_m=400.0, latest=GwLevel("2024-01-01", 9.5)),
        GwFilter("near", "1", 0, 0, 10.0, None, None, None, None, "", None, distance_m=50.0, latest=None),
    ]
    sigs = [s for s in checks.run_all(r) if s.code == "ondiep_grondwater"]
    assert len(sigs) == 1 and "far" in sigs[0].fact and "0.5 m" in sigs[0].fact


def test_groundwater_at_2_5_m_is_not_flagged_as_shallow(gent_ring):
    r = _result(gent_ring)
    r.gw_filters = [GwFilter("f", "1", 0, 0, 10.0, None, None, None, None, "", None,
                             distance_m=10.0, latest=GwLevel("2024-01-01", 7.5))]
    assert not any(s.code == "ondiep_grondwater" for s in checks.run_all(r))


def test_flood_reports_the_worst_class_translated_via_the_catalogue_labels(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("watertoets_fluviaal", "Watertoets fluviaal",
                               [{"gridcode": "1"}, {"gridcode": "3"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "overstroming"]
    assert len(sigs) == 1
    assert "D - Middelgrote" in sigs[0].fact


def test_flood_gridcode_zero_does_not_flag(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("watertoets_pluviaal", "Watertoets pluviaal", [{"gridcode": "0"}]))
    assert not any(s.code == "overstroming" for s in checks.run_all(r))


def test_flood_row_without_gridcode_flags_as_unknown_class(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("watertoets_pluviaal", "Watertoets pluviaal", [{}]))
    sigs = [s for s in checks.run_all(r) if s.code == "overstroming"]
    assert len(sigs) == 1 and "onbekend" in sigs[0].fact


def test_erosion_reads_totale_erosie_not_erosieklasse_alv(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("erosie", "Erosie", [{"Erosieklasse_ALV": "zeer hoog", "Totale_erosie": "laag"}]))
    assert not any(s.code == "erosie" for s in checks.run_all(r))  # ALV is ignored; Totale_erosie 'laag' -> no flag


def test_erosion_totale_erosie_hoog_is_flagged(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("erosie", "Erosie", [{"Erosieklasse_ALV": "laag", "Totale_erosie": "zeer hoog"}]))
    assert any(s.code == "erosie" for s in checks.run_all(r))


def test_erosie_fixture_with_a_hoog_parcel_flags_erosion(gent_ring):
    data = fixture_json("wfs_erosie_2014_hoog.json")
    fields = catalogue.by_id("erosie").fact_fields
    rows = [{k: f["properties"].get(k) for k in fields} for f in data["features"]]
    r = _result(gent_ring)
    r.map_facts.append(MapFact("erosie", "Erosie", rows))
    sigs = [s for s in checks.run_all(r) if s.code == "erosie"]
    assert len(sigs) == 1 and "hoog" in sigs[0].fact


def test_flood_unknown_numeric_gridcode_flags_as_klasse_n(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("watertoets_pluviaal", "Watertoets pluviaal", [{"gridcode": "4"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "overstroming"]
    assert len(sigs) == 1 and "klasse 4" in sigs[0].fact


def test_flood_non_numeric_gridcode_flags_without_raising(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("watertoets_pluviaal", "Watertoets pluviaal", [{"gridcode": "D"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "overstroming"]
    assert len(sigs) == 1


def test_erosion_summary_mentions_every_distinct_class_not_just_the_first_row(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("erosie", "Erosie", [
        {"Totale_erosie": "hoog"}, {"Totale_erosie": "zeer hoog"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "erosie"]
    assert len(sigs) == 1 and "hoog" in sigs[0].fact and "zeer hoog" in sigs[0].fact


def test_shrink_swell_and_ovam_are_flagged_when_present(gent_ring):
    r = _result(gent_ring)
    r.map_facts += [
        MapFact("krimp_zwel", "Krimp-zwel", [{"hoofdlithologie": "klei/silt"}]),
        MapFact("ovam", "OVAM", [{"uitspraak": "Er is een orienterend bodemonderzoek nodig"}]),
    ]
    codes = [s.code for s in checks.run_all(r)]
    assert "krimp_zwel" in codes and "ovam" in codes


def test_landslide_class_2_or_higher_is_flagged_class_1_is_not(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", [
        {"gevoelighd": "lage gevoeligheid", "klasse": "1"}]))
    assert not any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))
    r.map_facts[-1].rows.append({"gevoelighd": "matige gevoeligheid", "klasse": "2"})
    assert any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))


def test_landslide_wording_matig_or_hoog_flags_even_without_a_class(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", [
        {"gevoelighd": "hoge gevoeligheid", "klasse": None}]))
    assert any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))


def test_landslide_fact_names_the_highest_class_present(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", [
        {"gevoelighd": "matige gevoeligheid", "klasse": "2"},
        {"gevoelighd": "hoge gevoeligheid", "klasse": "3"},
        {"gevoelighd": "lage gevoeligheid", "klasse": "1"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "grondverschuiving_gevoelig"]
    assert len(sigs) == 1
    assert "hoge gevoeligheid" in sigs[0].fact and "3" in sigs[0].fact
    assert "hellingstabiliteit" in sigs[0].advice


def test_a_worded_high_row_outranks_a_numbered_moderate_one(gent_ring):
    # "hoge gevoeligheid" is the worst grade present even though that row carries no digit klasse,
    # so it - not the numbered class 2 row - is the one the fact has to name.
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", [
        {"gevoelighd": "matige gevoeligheid", "klasse": "2"},
        {"gevoelighd": "hoge gevoeligheid", "klasse": None}]))
    sigs = [s for s in checks.run_all(r) if s.code == "grondverschuiving_gevoelig"]
    assert len(sigs) == 1 and "hoge gevoeligheid" in sigs[0].fact


def test_a_worded_low_row_stays_below_the_threshold(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", [
        {"gevoelighd": "lage gevoeligheid", "klasse": None}]))
    assert not any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))


def test_no_landslide_susceptibility_rows_means_no_flag(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", []))
    assert not any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))


def test_gevoeligheid_fixture_at_the_rural_zone_is_class_1_and_does_not_flag(gent_ring):
    data = fixture_json("wfs_grndversch_gevoeligh_intersects.json")
    fields = catalogue.by_id("grondverschuiving_gevoeligheid").fact_fields
    rows = [{k: f["properties"].get(k) for k in fields} for f in data["features"]]
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gevoeligheid", "Gevoeligheid", rows))
    assert rows and rows[0]["klasse"] == "1"
    assert not any(s.code == "grondverschuiving_gevoelig" for s in checks.run_all(r))


def test_one_mapped_landslide_is_enough_to_flag_and_the_fact_names_it(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gekarteerd", "Gekarteerd", [
        {"naam": "Koppenberg", "type": "Grote GV met diep schuifvlak", "gemeente": "Oudenaarde"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "grondverschuiving_gekarteerd"]
    assert len(sigs) == 1
    assert "Koppenberg" in sigs[0].fact and "1" in sigs[0].fact
    assert "rapport" in sigs[0].advice.lower()


def test_mapped_landslide_fact_separates_the_polygon_count_from_the_named_ones(gent_ring):
    # One landslide is mapped as several polygons, so "how many polygons" and "how many are named"
    # are different numbers and the fact must give both rather than implying four landslides.
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gekarteerd", "Gekarteerd", [
        {"naam": "Koppenberg", "type": "Grote GV met diep schuifvlak"},
        {"naam": "Koppenberg", "type": "Grote GV met diep schuifvlak"},
        {"naam": "Nukerke", "type": "Grote GV met diep schuifvlak"},
        {"naam": None, "type": "Kleine GV"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "grondverschuiving_gekarteerd"]
    assert len(sigs) == 1
    assert sigs[0].fact.startswith("4 gekarteerde grondverschuiving(en)")
    assert "2 met naam" in sigs[0].fact
    assert "Koppenberg" in sigs[0].fact and "Nukerke" in sigs[0].fact


def test_no_mapped_landslides_means_no_flag(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gekarteerd", "Gekarteerd", []))
    assert not any(s.code == "grondverschuiving_gekarteerd" for s in checks.run_all(r))


def test_gekarteerd_fixture_flags_the_landslides_in_the_flemish_ardennes(gent_ring):
    data = fixture_json("wfs_grndversch_gekarteerd_intersects.json")
    fields = catalogue.by_id("grondverschuiving_gekarteerd").fact_fields
    rows = [{k: f["properties"].get(k) for k in fields} for f in data["features"]]
    r = _result(gent_ring)
    r.map_facts.append(MapFact("grondverschuiving_gekarteerd", "Gekarteerd", rows))
    sigs = [s for s in checks.run_all(r) if s.code == "grondverschuiving_gekarteerd"]
    assert len(sigs) == 1 and "Koppenberg" in sigs[0].fact


def test_one_pfas_no_regret_zone_is_enough_to_flag_and_the_fact_names_dossier_and_status(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("pfas_no_regret", "PFAS", [
        {"pfasdossiernr": "93685", "gemeente": "Zwijndrecht", "nrm_status_zone": "Locatiespecifiek vastgesteld"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "pfas_no_regret"]
    assert len(sigs) == 1
    assert "93685" in sigs[0].fact and "Locatiespecifiek vastgesteld" in sigs[0].fact
    assert "no-regret" in sigs[0].advice.lower() and "OVAM" in sigs[0].advice


def test_a_pfas_zone_without_a_dossier_number_still_flags(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("pfas_no_regret", "PFAS", [
        {"pfasdossiernr": None, "nrm_status_zone": "Locatiespecifiek vastgesteld"}]))
    sigs = [s for s in checks.run_all(r) if s.code == "pfas_no_regret"]
    assert len(sigs) == 1 and "zonder dossiernummer" in sigs[0].fact


def test_no_pfas_zones_means_no_flag(gent_ring):
    r = _result(gent_ring)
    r.map_facts.append(MapFact("pfas_no_regret", "PFAS", []))
    assert not any(s.code == "pfas_no_regret" for s in checks.run_all(r))


def test_pfas_fixture_near_zwijndrecht_flags_five_zones(gent_ring):
    data = fixture_json("wfs_pfas_no_regret_intersects.json")
    fields = catalogue.by_id("pfas_no_regret").fact_fields
    rows = [{k: f["properties"].get(k) for k in fields} for f in data["features"]]
    r = _result(gent_ring)
    r.map_facts.append(MapFact("pfas_no_regret", "PFAS", rows))
    sigs = [s for s in checks.run_all(r) if s.code == "pfas_no_regret"]
    assert len(sigs) == 1 and "5" in sigs[0].fact and "93685" in sigs[0].fact


def test_no_cpt_within_radius_and_cpt_within_50_m(gent_ring):
    r = _result(gent_ring)
    assert any(s.code == "geen_cpt" for s in checks.run_all(r))
    r.cpts = [Cpt("k", "S1", 0, 0, None, 20.0, None, None, None, None, None, "", distance_m=30.0)]
    codes = [s.code for s in checks.run_all(r)]
    assert "geen_cpt" not in codes and "cpt_dichtbij" in codes


def test_cpts_only_beyond_50_m_trigger_neither_flag(gent_ring):
    r = _result(gent_ring)
    r.cpts = [Cpt("k", "S1", 0, 0, None, 20.0, None, None, None, None, None, "", distance_m=120.0)]
    codes = [s.code for s in checks.run_all(r)]
    assert "geen_cpt" not in codes and "cpt_dichtbij" not in codes


def test_relief_over_2_m_is_flagged(gent_ring):
    r = _result(gent_ring)
    r.relief = (8.0, 10.5, 9.0)
    assert any(s.code == "relief" for s in checks.run_all(r))


def test_relief_of_1_5_m_is_not_flagged(gent_ring):
    r = _result(gent_ring)
    r.relief = (9.0, 10.5, 9.5)
    assert not any(s.code == "relief" for s in checks.run_all(r))


def test_failed_source_reports_message_as_fact_and_source_as_source(gent_ring):
    r = _result(gent_ring)
    r.provenance.append(Provenance("Bodemkaart", "https://x", "t", ok=False, message="timeout"))
    sigs = [s for s in checks.run_all(r) if s.code == "bron_niet_beschikbaar"]
    assert len(sigs) == 1
    assert sigs[0].fact == "Bron niet beschikbaar: timeout"
    assert sigs[0].source == "Bodemkaart"
    assert sigs[0].severity == "aandacht"


def test_successful_source_is_not_flagged(gent_ring):
    r = _result(gent_ring)
    r.provenance.append(Provenance("Bodemkaart", "https://x", "t", ok=True))
    assert not any(s.code == "bron_niet_beschikbaar" for s in checks.run_all(r))


def test_invalid_severity_raises_value_error(gent_ring, monkeypatch):
    def bad_rule(result):
        return [Signalering("x", "y", "z", "w", severity="ongeldig")]

    monkeypatch.setattr(checks, "RULES", [bad_rule])
    with pytest.raises(ValueError):
        checks.run_all(_result(gent_ring))


def test_validate_guards_signals_that_did_not_come_from_a_rule():
    # The orchestrator adds signals of its own (truncation, incomplete section), so the severity
    # vocabulary has to be guarded where the whole list is assembled, not only inside run_all.
    with pytest.raises(ValueError):
        checks.validate([Signalering("x", "y", "z", "w", severity="ongeldig")])


def test_validate_returns_the_signals_it_was_given():
    signals = [Signalering("a", "y", "z", "w", severity="info"),
               Signalering("b", "y", "z", "w", severity="aandacht")]
    assert checks.validate(signals) == signals
