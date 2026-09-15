from __future__ import annotations

import pytest

from desktopstudie.core import catalogue as c
from tests.core.conftest import fixture_json

FIXTURE_FOR = {
    "bodemkaart": "wfs_bodemtypes_intersects.json",
    "quartair": "wfs_quartair_samengesteld_intersects.json",
    "quartair_200k": "wfs_quartair_200k_intersects.json",
    "quartair_dikte": "wfs_quartair_isopachen_intersects.json",
    "tertiair": "wfs_tertiair_50k_intersects.json",
    "hcov": "wfs_hcov_0100_vk_intersects.json",
    "gw_kwetsbaarheid": "wfs_gwkwb_kwbschaal_intersects.json",
    "erosie": "wfs_erosie_2014_intersects.json",
    "krimp_zwel": "wfs_indexplastisch_intersects.json",
    "ovam": "wfs_ovam_uitspraak_intersects.json",
    "grondverschuiving_gevoeligheid": "wfs_grndversch_gevoeligh_intersects.json",
    "grondverschuiving_gekarteerd": "wfs_grndversch_gekarteerd_intersects.json",
    "pfas_no_regret": "wfs_pfas_no_regret_intersects.json",
    "watertoets_pluviaal": "watertoets_fluviaal_hit.json",
    "watertoets_fluviaal": "watertoets_fluviaal_hit.json",
}


def test_fact_fields_exist_in_recorded_fixtures():
    for e in c.entries():
        if not e.fact_mode:
            continue
        assert e.id in FIXTURE_FOR, e.id
        data = fixture_json(FIXTURE_FOR[e.id])
        features = data["features"]
        assert features, f"{e.id}: fixture {FIXTURE_FOR[e.id]} has no features"
        for field_name in e.fact_fields:
            assert field_name in features[0]["properties"], f"{e.id}: missing field {field_name!r}"


def test_ids_are_unique_and_chapters_known():
    ids = [e.id for e in c.CATALOGUE]
    assert len(ids) == len(set(ids))
    assert {e.chapter for e in c.CATALOGUE} <= {"ligging", "historisch", "geologie"}


def test_enabled_entries_have_a_wms_url_and_layer():
    for e in c.entries():
        assert e.wms_url.startswith("https://"), e.id
        assert e.wms_layer, e.id


def test_ngi_historic_is_a_documented_empty_slot():
    slot = c.by_id("ngi_hist")
    assert slot.enabled is False
    assert "WMS" in slot.note


def test_fact_entries_declare_fields():
    for e in c.entries():
        if e.fact_mode == "wfs":
            assert e.wfs_typename and e.fact_fields, e.id
        if e.fact_mode == "gfi":
            assert e.fact_fields, e.id


def test_bodemkaart_fact_fields_include_texture_and_drainage_codes():
    fields = c.by_id("bodemkaart").fact_fields
    assert "Textuurklasse_code" in fields
    assert "Drainageklasse_code" in fields


def test_watertoets_labels_translate_gridcode():
    e = c.by_id("watertoets_fluviaal")
    assert e.value_labels["gridcode"]["3"].startswith("D - ")


def test_entries_are_hashable():
    entries = c.entries()
    assert len({e for e in entries}) == len(entries)
    hash(c.by_id("watertoets_fluviaal"))  # must not raise


def test_entries_filter_by_chapter_and_enabled():
    assert [e.id for e in c.entries("ligging")] == ["grb", "ortho", "ngi_topo", "dhmv_hillshade", "dhmv_dtm"]
    assert len(c.entries("historisch")) == 7
    assert len(c.entries("historisch", enabled_only=False)) == 9  # + ngi_hist and bommenkaart


def test_by_id_unknown_raises_key_error():
    with pytest.raises(KeyError):
        c.by_id("does_not_exist")


def test_every_fact_field_has_a_readable_label():
    for e in c.CATALOGUE:
        if e.fact_mode is None:
            continue
        missing = [f for f in e.fact_fields if f not in e.field_labels]
        assert not missing, f"{e.id} missing labels for {missing}"


def test_every_map_has_a_positive_scale_and_low_resolution_maps_zoom_out():
    assert all(e.scale > 0 for e in c.CATALOGUE)
    assert c.by_id("ferraris").scale > c.by_id("grb").scale
    assert c.by_id("quartair_200k").scale > c.by_id("bodemkaart").scale
    assert all(1000 <= e.scale <= 200000 for e in c.CATALOGUE)


def test_service_urls_carry_their_template_placeholders():
    assert "{model}" in c.VB_DOORPRIK_URL
    assert "{model}" in c.VB_PROFILE_URL and c.VB_PROFILE_URL.endswith("/profielbevraging/lagen")
    assert "{kind}" in c.WATERINFO_WMS_URL
    assert all(url.startswith("https://") for url in
               (c.DOV_WFS_URL, c.DOV_WMS_URL, c.GEOCODER_URL, c.VB_DOORPRIK_URL, c.VB_PROFILE_URL,
                c.WATERINFO_WMS_URL, c.DHMV_WCS_URL))


def test_bommenkaart_is_a_documented_empty_slot_naming_the_explosives_risk():
    slot = c.by_id("bommenkaart")
    assert slot.chapter == "historisch"
    assert slot.enabled is False
    assert "geen open data" in slot.note and "WMS" in slot.note
    assert "explosieven" in slot.note


def test_the_pfas_map_names_ovam_as_its_source():
    entry = c.by_id("pfas_no_regret")
    assert entry.chapter == "geologie"
    assert entry.attribution == "OVAM / Vlaamse overheid via DOV"
    # no_regret_zones is a STYLE of pfas:no_regret_huidig, not a WMS layer of its own
    assert entry.wms_layer == "pfas:no_regret_huidig"
    assert entry.wfs_typename == "pfas:no_regret_huidig"


def test_the_landslide_maps_expose_the_class_and_the_report_link():
    assert c.by_id("grondverschuiving_gevoeligheid").fact_fields == ("gevoelighd", "klasse")
    assert c.by_id("grondverschuiving_gevoeligheid").legend is True
    assert "rapport" in c.by_id("grondverschuiving_gekarteerd").fact_fields
    assert c.by_id("grondverschuiving_gekarteerd").scale == 10000


def test_the_label_tables_of_a_catalogue_entry_cannot_be_written_into():
    # The catalogue is module-level shared state: a caller that wrote into a label table would
    # change the map for every later study in the same QGIS session. The write has to fail here,
    # not show up as a wrong header three reports later.
    entry = c.by_id("watertoets_fluviaal")
    with pytest.raises(TypeError):
        entry.value_labels["gridcode"]["0"] = "iets anders"
    with pytest.raises(TypeError):
        entry.value_labels["gridcode"] = {}
    with pytest.raises(TypeError):
        entry.field_labels["gridcode"] = "Iets anders"
    assert entry.value_labels["gridcode"]["0"].startswith("A - ")
    assert entry.field_labels["gridcode"] == "Klasse"


def test_a_catalogue_entry_without_label_tables_still_reads_like_a_mapping():
    entry = c.by_id("grb")
    assert entry.value_labels == {} and entry.field_labels == {}
    assert entry.value_labels.get("x", {}).get("y") is None


def test_the_gxg_map_names_the_real_layer_and_carries_the_style():
    # gxg:gxg is a STYLE of gxg:ghg_mmv_main, not a layer of its own: a GetMap on gxg:gxg answers
    # with a ServiceException, exactly like pfas:no_regret_zones (both verified live 2026-09-15).
    entry = c.by_id("gxg_ghg")
    assert entry.wms_layer == "gxg:ghg_mmv_main"
    assert entry.wms_style == "gxg:gxg"


def test_the_groundwater_level_maps_are_a_highest_and_a_lowest_one():
    # GxG is a pair: the mean highest (GHG) and the mean lowest (GLG) groundwater level. One map
    # titled "GxG" hides which of the two the reader is looking at, so each gets its own entry and
    # its own page. Both draw with the same named style (live GetMap 2026-09-15: gxg:glg_mmv_main
    # + gxg:gxg -> HTTP 200 image/png).
    ghg, glg = c.by_id("gxg_ghg"), c.by_id("gxg_glg")
    assert ghg.title == "Gemiddeld hoogste grondwaterstand (GHG)"
    assert glg.title == "Gemiddeld laagste grondwaterstand (GLG)"
    assert glg.wms_layer == "gxg:glg_mmv_main"
    assert glg.wms_style == "gxg:gxg"
    assert glg.chapter == ghg.chapter == "geologie"
    assert glg.attribution == ghg.attribution and glg.licence == ghg.licence
    assert glg.legend is True and glg.scale == 25000
    # they stay neighbours, so the report shows the highest and the lowest level side by side
    ids = [e.id for e in c.entries("geologie")]
    assert ids.index("gxg_glg") == ids.index("gxg_ghg") + 1


def test_a_map_without_an_explicit_style_asks_the_service_for_its_default():
    # An empty styles parameter means "the layer default"; only maps whose wanted rendering is a
    # named style fill wms_style in.
    assert c.by_id("grb").wms_style == ""
    assert [e.id for e in c.entries() if e.wms_style] == ["gxg_ghg", "gxg_glg"]


def test_a_map_id_says_which_of_the_two_gxg_levels_it_is():
    # "gxg" alone names the pair, not a map: with GHG and GLG side by side, an id that could mean
    # either is the one thing a reader of the report tree cannot resolve.
    with pytest.raises(KeyError):
        c.by_id("gxg")
    assert {"gxg_ghg", "gxg_glg"} <= {e.id for e in c.entries("geologie")}


def test_every_map_carries_legend_options_for_the_legend_image():
    # The legend is fetched as a picture (GetLegendGraphic). Without LEGEND_OPTIONS GeoServer
    # answers with one endless column of classes - a strip no page can hold - so every entry
    # carries a column layout and a readable font size.
    for entry in c.CATALOGUE:
        assert "columns:" in entry.legend_options, entry.id
        assert "fontSize:" in entry.legend_options, entry.id


def test_the_soil_map_has_no_legend_page():
    # The soil map legend lists every soil series in Flanders (hundreds of classes): on paper it
    # is unreadable and pages long. The fact table names the soil types inside the zone, which is
    # what the reader actually needs.
    soil = c.by_id("bodemkaart")
    assert soil.legend is False
    assert soil.fact_mode == "wfs" and soil.fact_fields


def test_the_maps_with_a_degenerate_legend_have_no_legend_page():
    # HCOV 0100 and the composite quartair map answer GetLegendGraphic with a 20x20 stamp that
    # names nothing: a blank page with a coloured square on it. Their fact tables carry the units
    # in the zone, so the page is dropped rather than printed empty.
    for map_id in ("hcov", "quartair"):
        entry = c.by_id(map_id)
        assert entry.legend is False, map_id
        assert entry.fact_mode == "wfs" and entry.fact_fields, map_id


def test_the_height_model_has_no_legend_page():
    # The DHMV legend is a colour ramp of 27 x 18 mm with two numbers on it (300 to -50). A whole
    # sheet for that is a sheet the reader turns past; what the colours mean - height in mTAW -
    # belongs in a sentence, not on a page of its own.
    assert c.by_id("dhmv_dtm").legend is False
