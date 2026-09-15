# tests/core/test_catalogue.py
from __future__ import annotations

from desktopstudie.core import catalogue as c


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
