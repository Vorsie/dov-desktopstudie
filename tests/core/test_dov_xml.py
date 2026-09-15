from __future__ import annotations

import pytest

from desktopstudie.core.services import dov_xml
from tests.core.conftest import fixture_bytes


def test_modern_cpt_has_qc_in_mpa_and_fs_in_kpa():
    p = dov_xml.parse_cpt_profile(fixture_bytes("sondering_2024-090319.xml"))
    assert len(p.depth_m) > 1000
    assert p.depth_m[1] > p.depth_m[0]
    assert max(v for v in p.qc_mpa if v is not None) < 100.0   # MPa, not kPa
    assert max(v for v in p.fs_kpa if v is not None) > 1.0     # kPa magnitude
    assert len(p.fs_kpa) == len(p.depth_m)


def test_old_mechanical_cpt_has_no_fs():
    p = dov_xml.parse_cpt_profile(fixture_bytes("sondering_1965-039716.xml"))
    assert len(p.depth_m) == 102
    assert all(v is None for v in p.fs_kpa)
    assert p.qc_mpa[0] is not None


def test_lithological_description_layers():
    layers = dov_xml.parse_lithology(fixture_bytes("interpretatie_2016-252456.xml"))
    assert len(layers) > 3
    assert layers[0].top_m == 0.0
    assert layers[-1].base_m > 40.0  # boring B938 gaat tot 48 m volgens de WFS
    assert layers[0].kind == "beschrijving" and layers[0].description


def test_coded_lithology_layers_keep_raw_codes():
    layers = dov_xml.parse_lithology(fixture_bytes("interpretatie_2024-382762.xml"))
    assert len(layers) == 54
    assert layers[0].kind == "gecodeerd"
    assert layers[0].description.startswith("FZ")
    assert "donkerbruin" in layers[0].description


def test_groundwater_levels_sorted_by_date():
    levels = dov_xml.parse_groundwater_levels(fixture_bytes("filter_1985-007948.xml"))
    assert len(levels) == 170
    assert levels[0].date <= levels[-1].date
    assert isinstance(levels[-1].level_mtaw, float)


def test_filter_without_levels_gives_empty_list():
    levels = dov_xml.parse_groundwater_levels(b"<filter xmlns='http://kern.schemas.dov.vlaanderen.be'></filter>")
    assert levels == []
