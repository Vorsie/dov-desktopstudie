from __future__ import annotations

from desktopstudie.core.figures import borehole_column, common, cpt_figure, section_figure, vb_column
from desktopstudie.core.figures.common import plt
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


def test_lithology_colour_recognises_dutch_keywords_and_dov_codes():
    assert common.lithology_colour("grijze klei") == "#9fb8a0"
    assert common.lithology_colour("FZ") == "#f5e07a"  # DOV coded hoofdnaam for fijn zand
    assert common.lithology_colour("puin") == "#e6e6e6"  # unknown -> grey fallback


def test_borehole_figure_axes_and_size():
    bh = Borehole("k", "B938", 0, 0, 7.0, 48.0, None, None, None, None, "", 100.0, lithology=[
        LithologyLayer(0.0, 1.2, "bruin fijn zand"), LithologyLayer(1.2, 6.0, "grijze klei"),
        LithologyLayer(6.0, 48.0, "groen zand")])
    fig, ax = borehole_column._build_borehole_figure(bh)
    try:
        assert ax.get_ylim()[0] > ax.get_ylim()[1]
        assert len(ax.patches) == 3
        fig.canvas.draw()
        assert fig.get_size_inches()[0] == 5.0
    finally:
        plt.close(fig)


def test_borehole_figure_with_no_lithology_draws_a_placeholder_message():
    bh = Borehole("k", "B000", 0, 0, None, None, None, None, None, None, "", 100.0, lithology=[])
    fig, ax = borehole_column._build_borehole_figure(bh)
    try:
        assert len(ax.patches) == 0
        assert any("geen laaggegevens" in t.get_text() for t in ax.texts)
    finally:
        plt.close(fig)


def test_vb_figure_axes_and_size():
    vb = parse_doorprik(fixture_json("vb_g3dv3_F.json"), 104326.0, 192506.0, "g3dv3_F")
    fig, ax = vb_column._build_vb_figure(vb, max_depth_m=60.0)
    try:
        within_cap = sum(1 for layer in vb.layers if vb.depth_of(layer)[0] < 60.0)
        assert ax.get_ylim()[0] > ax.get_ylim()[1]
        assert len(ax.patches) == within_cap  # layers below the 60 m cap are clipped away
        fig.canvas.draw()
        assert fig.get_size_inches()[0] == 5.0
    finally:
        plt.close(fig)


def test_draw_depth_column_avoids_label_collisions():
    fig, ax = plt.subplots()
    try:
        # 6 heavily overlapping 0.3 m bands packed near the top of a 10 m column: without
        # collision avoidance their labels would all land on top of each other.
        bands = [(i * 0.05, i * 0.05 + 0.3, "#abcdef", f"laag {i}") for i in range(6)]
        drawn_depth = common.draw_depth_column(ax, bands, max_depth_m=10.0)
        ys = [t.get_position()[1] for t in ax.texts]
        step = 0.028 * drawn_depth
        assert ys == sorted(ys)
        assert all(y2 - y1 >= step - 1e-9 for y1, y2 in zip(ys, ys[1:]))
    finally:
        plt.close(fig)
