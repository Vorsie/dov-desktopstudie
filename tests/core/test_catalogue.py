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
    assert len(c.entries("historisch", enabled_only=False)) == 8


def test_by_id_unknown_raises_key_error():
    with pytest.raises(KeyError):
        c.by_id("does_not_exist")


def test_every_map_has_a_positive_scale_and_low_resolution_maps_zoom_out():
    assert all(e.scale > 0 for e in c.CATALOGUE)
    assert c.by_id("ferraris").scale > c.by_id("grb").scale
    assert c.by_id("quartair_200k").scale > c.by_id("bodemkaart").scale
