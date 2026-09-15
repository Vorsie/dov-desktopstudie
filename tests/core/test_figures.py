from __future__ import annotations

from desktopstudie.core.figures import borehole_column, cpt_figure, section_figure, vb_column
from desktopstudie.core.model import Borehole, Cpt, LithologyLayer, ProjectedPoint, Section, VirtualBorehole
from desktopstudie.core.services.dov_xml import parse_cpt_profile
from desktopstudie.core.services.virtuele_boring import parse_doorprik
from tests.core.conftest import fixture_bytes, fixture_json


def _png_ok(path):
    return path.exists() and path.stat().st_size > 5000 and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cpt_figure_with_fs_and_without(tmp_path):
    modern = Cpt("2024-090319", "S407", 0, 0, 8.0, 32.2, "2024-04-05", "continu elektrisch", None, None, None, "",
                 12.0, profile=parse_cpt_profile(fixture_bytes("sondering_2024-090319.xml")))
    old = Cpt("1965-039716", "SIX", 0, 0, 6.26, 20.4, "1965-02-17", "discontinu mechanisch", "M4", None, None, "",
              210.0, profile=parse_cpt_profile(fixture_bytes("sondering_1965-039716.xml")))
    assert _png_ok(cpt_figure.plot_cpt(modern, tmp_path / "modern.png"))
    assert _png_ok(cpt_figure.plot_cpt(old, tmp_path / "old.png"))


def test_borehole_column(tmp_path):
    bh = Borehole("k", "B938", 0, 0, 7.0, 48.0, None, None, None, None, "", 100.0, lithology=[
        LithologyLayer(0.0, 1.2, "bruin fijn zand"), LithologyLayer(1.2, 6.0, "grijze klei"),
        LithologyLayer(6.0, 48.0, "groen zand")])
    assert _png_ok(borehole_column.plot_borehole(bh, tmp_path / "bh.png"))


def test_vb_column_and_section(tmp_path):
    vb = parse_doorprik(fixture_json("vb_g3dv3_F.json"), 104326.0, 192506.0, "g3dv3_F")
    assert _png_ok(vb_column.plot_virtual_borehole(vb, tmp_path / "vb.png"))
    sec = Section(line=((104126.0, 192506.0), (104526.0, 192506.0)),
                  boreholes=[VirtualBorehole(104126.0 + 100 * i, 192506.0, "g3dv3_F", vb.layers) for i in range(5)],
                  projected=[ProjectedPoint("cpt", "S407", 200.0, 5.0, 14.0, 32.0),
                             ProjectedPoint("boring", "B1", 250.0, -3.0, None, 10.0)],  # no Z: hangs from the surface
                  zone_from_m=100.0, zone_to_m=300.0)
    assert _png_ok(section_figure.plot_section(sec, tmp_path / "sec.png", max_depth_m=60.0))


def test_section_surface_interpolation():
    assert section_figure._surface_at(50.0, [0.0, 100.0], [10.0, 12.0]) == 11.0
    assert section_figure._surface_at(-5.0, [0.0, 100.0], [10.0, 12.0]) == 10.0
    assert section_figure._surface_at(500.0, [0.0, 100.0], [10.0, None]) == 10.0
