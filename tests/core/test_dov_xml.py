from __future__ import annotations

import pytest

from desktopstudie.core.logging_util import Log
from desktopstudie.core.services import dov_xml
from tests.core.conftest import fixture_bytes


def test_modern_cpt_has_qc_in_mpa_and_fs_in_kpa():
    p = dov_xml.parse_cpt_profile(fixture_bytes("sondering_2024-090319.xml"))
    assert len(p.depth_m) == 1536
    assert all(b > a for a, b in zip(p.depth_m, p.depth_m[1:]))
    assert max(v for v in p.qc_mpa if v is not None) < 100.0   # MPa, not kPa
    assert max(v for v in p.fs_kpa if v is not None) > 1.0     # kPa magnitude
    assert len(p.fs_kpa) == len(p.depth_m)


def test_old_mechanical_cpt_has_no_fs():
    p = dov_xml.parse_cpt_profile(fixture_bytes("sondering_1965-039716.xml"))
    assert len(p.depth_m) == 102
    assert all(v is None for v in p.fs_kpa)
    assert p.qc_mpa[0] is not None


def test_lithological_description_layers():
    # interpretatie_2016-252456.xml: 5 <laag> elements, last <tot> = 48.00 (boring B938)
    layers = dov_xml.parse_lithology(fixture_bytes("interpretatie_2016-252456.xml"))
    assert len(layers) == 5
    assert layers[0].top_m == 0.0
    assert layers[-1].base_m == 48.0
    assert layers[0].kind == "beschrijving" and layers[0].description


def test_coded_lithology_layers_keep_raw_codes():
    layers = dov_xml.parse_lithology(fixture_bytes("interpretatie_2024-382762.xml"))
    assert len(layers) == 54
    assert layers[0].kind == "gecodeerd"
    assert layers[0].description.startswith("FZ")
    assert "donkerbruin" in layers[0].description


def test_coded_layer_keeps_raw_tokens():
    layers = dov_xml.parse_lithology(fixture_bytes("interpretatie_2024-382762.xml"))
    raw = layers[0].raw
    assert raw["hoofdnaam"] == "FZ"
    assert raw["bijmenging"] and isinstance(raw["bijmenging"], list)
    assert "plaatselijk" in raw["bijmenging"][0]


def test_groundwater_levels_sorted_by_date():
    levels = dov_xml.parse_groundwater_levels(fixture_bytes("filter_1985-007948.xml"))
    assert len(levels) == 170
    assert levels[0].date <= levels[-1].date
    assert isinstance(levels[-1].level_mtaw, float)


def test_filter_without_levels_gives_empty_list():
    levels = dov_xml.parse_groundwater_levels(b"<filter xmlns='http://kern.schemas.dov.vlaanderen.be'></filter>")
    assert levels == []


def test_groundwater_without_usable_levels_logs_warning():
    xml = (b"<ns4:dov-schema xmlns:ns4='http://kern.schemas.dov.vlaanderen.be'>"
           b"<filter><peilmeting><methode>peillint</methode></peilmeting></filter>"
           b"</ns4:dov-schema>")
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="DEBUG")
    levels = dov_xml.parse_groundwater_levels(xml, log=log)
    assert levels == []
    assert any("peilmeting" in m for m in messages)


def test_off_scale_reading_keeps_magnitude():
    xml = (b"<ns4:dov-schema xmlns:ns4='http://kern.schemas.dov.vlaanderen.be'>"
           b"<sondering><sondeonderzoek>"
           b"<meetdata><diepte>1.0</diepte><qc>&gt;50.0</qc></meetdata>"
           b"</sondeonderzoek></sondering></ns4:dov-schema>")
    p = dov_xml.parse_cpt_profile(xml)
    assert p.qc_mpa == [50.0]


def test_sondeerdiepte_variant_is_supported():
    xml = (b"<ns4:dov-schema xmlns:ns4='http://kern.schemas.dov.vlaanderen.be'>"
           b"<sondering><sondeonderzoek>"
           b"<meetdata><sondeerdiepte>2.5</sondeerdiepte><qc>1.2</qc></meetdata>"
           b"<meetdata><sondeerdiepte>3.0</sondeerdiepte><qc>1.4</qc></meetdata>"
           b"</sondeonderzoek></sondering></ns4:dov-schema>")
    p = dov_xml.parse_cpt_profile(xml)
    assert p.depth_m == [2.5, 3.0]


def test_empty_cpt_logs_warning():
    xml = (b"<ns4:dov-schema xmlns:ns4='http://kern.schemas.dov.vlaanderen.be'>"
           b"<sondering><sondeonderzoek>"
           b"<meetdata><qc>1.0</qc></meetdata>"
           b"<meetdata><qc>2.0</qc></meetdata>"
           b"</sondeonderzoek></sondering></ns4:dov-schema>")
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="DEBUG")
    p = dov_xml.parse_cpt_profile(xml, log=log)
    assert p.depth_m == []
    assert any("zonder bruikbare diepte" in m for m in messages)


def test_partial_cpt_warns_how_many_rows_were_skipped():
    xml = (b"<ns4:dov-schema xmlns:ns4='http://kern.schemas.dov.vlaanderen.be'>"
           b"<sondering><sondeonderzoek>"
           b"<meetdata><diepte>1.0</diepte><qc>1.0</qc></meetdata>"
           b"<meetdata><qc>2.0</qc></meetdata>"
           b"<meetdata><diepte>3.0</diepte><qc>3.0</qc></meetdata>"
           b"</sondeonderzoek></sondering></ns4:dov-schema>")
    messages: list[str] = []
    log = Log("test", sink=messages.append, level="INFO")
    p = dov_xml.parse_cpt_profile(xml, log=log)
    assert p.depth_m == [1.0, 3.0]
    assert any("1 van 3 meetdata-rijen zonder" in m for m in messages)


def test_doctype_is_rejected():
    xml = b"<?xml version='1.0'?><!DOCTYPE foo [<!ENTITY x 'y'>]><foo/>"
    with pytest.raises(ValueError):
        dov_xml.parse_cpt_profile(xml)


@pytest.mark.live
def test_live_cpt_profile():
    from desktopstudie.core.services.http import HttpClient

    data = HttpClient().get("https://www.dov.vlaanderen.be/data/sondering/2024-090319.xml")
    p = dov_xml.parse_cpt_profile(data)
    assert len(p.depth_m) == 1536
