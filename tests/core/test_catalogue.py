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
