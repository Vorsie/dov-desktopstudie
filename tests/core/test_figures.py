from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from desktopstudie.core.figures import borehole_column, common, cpt_figure, section_figure, vb_column
from desktopstudie.core.model import (
    Borehole,
    Cpt,
    CptProfile,
    LithologyLayer,
    ProfileColumn,
    ProjectedPoint,
    Section,
    SectionProfile,
    VbLayer,
    VirtualBorehole,
)
from desktopstudie.core.services.dov_xml import parse_cpt_profile
from desktopstudie.core.services.virtuele_boring import parse_doorprik, parse_profile
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


def test_section_columns_are_placed_at_their_true_chainage():
    vb = parse_doorprik(fixture_json("vb_g3dv3_F.json"), 104326.0, 192506.0, "g3dv3_F")
    base_x, y = 104000.0, 192506.0
    chainages = [i * 40.0 for i in range(11) if i not in (3, 7)]  # boreholes at 120 m and 280 m failed
    boreholes = [VirtualBorehole(base_x + c, y, "g3dv3_F", vb.layers) for c in chainages]
    sec = Section(line=((base_x, y), (base_x + 400.0, y)), boreholes=boreholes, projected=[],
                 zone_from_m=100.0, zone_to_m=300.0, failed_points=2)
    fig, ax = section_figure._build_section_figure(sec, max_depth_m=60.0)
    try:
        assert chainages == [0.0, 40.0, 80.0, 160.0, 200.0, 240.0, 320.0, 360.0, 400.0]
        centres = sorted({round(patch.get_x() + patch.get_width() / 2.0, 6) for patch in ax.patches})
        assert centres == chainages
        legend_labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert "maaiveld (G3Dv3)" in legend_labels and "onderzoekszone" in legend_labels
    finally:
        plt.close(fig)


def test_cpt_qc_axis_clips_a_spike_and_labels_it():
    depth = [i * 0.1 for i in range(150)]
    qc = [2.0] * 149 + [60.0]  # one erratic spike among 149 unremarkable readings
    cpt = Cpt("k", "S1", 0, 0, None, 15.0, "2024-01-01", "continu elektrisch", None, None, None, "", 5.0,
             profile=CptProfile(depth_m=depth, qc_mpa=qc, fs_kpa=[None] * 150, u_kpa=[None] * 150))
    fig, axes = cpt_figure._build_cpt_figure(cpt)
    try:
        assert axes[0].get_xlim()[1] <= 50.0
        assert "afgekapt" in axes[0].get_xlabel()
        assert axes[0].get_ylim()[0] > axes[0].get_ylim()[1]  # depth increasing downward
        assert len(axes[0].lines) == 1
    finally:
        plt.close(fig)


def test_cpt_without_a_profile_draws_a_placeholder_message():
    cpt = Cpt("k", "S2", 0, 0, None, None, None, None, None, None, None, "", 5.0, profile=None)
    fig, axes = cpt_figure._build_cpt_figure(cpt)
    try:
        assert any("geen meetreeks" in t.get_text() for t in axes[0].texts)
    finally:
        plt.close(fig)


def test_cpt_title_has_no_trailing_separator_when_method_is_missing():
    cpt = Cpt("k", "S3", 0, 0, None, None, "2024-01-01", None, None, None, None, "", 5.0, profile=None)
    fig, _ = cpt_figure._build_cpt_figure(cpt)
    try:
        assert not fig._suptitle.get_text().split("\n")[0].endswith("-")
    finally:
        plt.close(fig)


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
        drawn_depth, skipped = common.draw_depth_column(ax, bands, max_depth_m=10.0)
        ys = [t.get_position()[1] for t in ax.texts]
        step = 0.028 * drawn_depth
        assert skipped == 0
        assert ys == sorted(ys)
        assert all(y2 - y1 >= step - 1e-9 for y1, y2 in zip(ys, ys[1:]))
    finally:
        plt.close(fig)


def _crowded_column(n: int) -> Borehole:
    """A borehole with `n` alternating thin/thick layers, each with a description long enough to
    be shortened, i.e. the worst case for label placement in draw_depth_column."""
    words = ["zand", "klei", "leem", "silt", "grind", "veen", "steen"]
    layers = []
    top = 0.0
    for i in range(n):
        base = top + (0.3 if i % 2 == 0 else 1.9)
        layers.append(LithologyLayer(top, base, f"{words[i % len(words)]} laag {i} met een lange omschrijving erbij"))
        top = base
    return Borehole("k", "B-MANY", 0, 0, None, top, None, None, None, None, "", 50.0, lithology=layers)


def _band_labels(ax):
    """The per-band labels: everything except the note that counts the labels left out, which is a
    caption about the figure rather than a label of a layer."""
    return [t for t in ax.texts if not t.get_text().endswith("laaglabels weggelaten")]


def _assert_labels_inside(fig, ax) -> None:
    fig.canvas.draw()
    box = ax.get_window_extent()
    for text in _band_labels(ax):
        extent = text.get_window_extent()
        assert extent.y1 <= box.y1 + 0.5, f"{text.get_text()!r} sticks out above the column"
        assert extent.y0 >= box.y0 - 0.5, f"{text.get_text()!r} sticks out below the column"
        assert extent.x1 <= box.x1 + 0.5, f"{text.get_text()!r} runs past the right edge of the column"


def test_column_labels_never_leave_the_axes():
    # 27 layers still fit; 40 no longer do, so some labels are dropped - but no label, in either
    # column, may be drawn above the top edge, below the bottom edge or past the right edge.
    for n_layers in (27, 40):
        fig, ax = borehole_column._build_borehole_figure(_crowded_column(n_layers))
        try:
            assert ax.texts
            _assert_labels_inside(fig, ax)
        finally:
            plt.close(fig)


def test_draw_depth_column_reports_the_labels_it_had_to_skip():
    fig, ax = plt.subplots()
    try:
        bands = [(i * 1.0, i * 1.0 + 1.0, "#abcdef", f"laag {i}") for i in range(60)]
        drawn_depth, skipped = common.draw_depth_column(ax, bands, max_depth_m=60.0)
        assert drawn_depth == 60.0
        assert skipped > 0, "60 labels cannot fit in 60 m at the minimum label step"
        assert skipped == 60 - len(ax.texts)
    finally:
        plt.close(fig)


ANCHOR_ORDER = ["g3dv3_F_2", "g3dv3_F_8", "g3dv3_F_31", "g3dv3_F_32", "g3dv3_F_33",
                "g3dv3_F_35", "g3dv3_F_36", "g3dv3_F_37", "g3dv3_F_42", "g3dv3_F_50"]


def _profile_section():
    vb = parse_doorprik(fixture_json("vb_g3dv3_F.json"), 104326.0, 192506.0, "g3dv3_F")
    profile = parse_profile(fixture_json("vb_profile_g3dv3_F.json"), "g3dv3_F", ANCHOR_ORDER,
                            lambda along: 14.62, 100.0)
    anchors = [VirtualBorehole(104126.0 + 200.0 * i, 192506.0, "g3dv3_F", vb.layers) for i in range(3)]
    section = Section(line=((104126.0, 192506.0), (104526.0, 192506.0)), boreholes=anchors,
                      projected=[ProjectedPoint("cpt", "S407", 200.0, 5.0, 14.0, 32.0)],
                      zone_from_m=100.0, zone_to_m=300.0, profile=profile)
    return section, profile


def test_section_with_a_profile_draws_one_rectangle_per_visible_profile_layer():
    section, profile = _profile_section()
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        visible = sum(1 for column in profile.columns for layer in column.layers
                      if layer.top_mtaw > column.surface_mtaw - 60.0)
        assert len(ax.patches) == visible + 1  # + the zone band in the headroom
        # columns are contiguous: each one spans the full sample spacing and they touch
        lefts = sorted({round(patch.get_x(), 6) for patch in _geology(ax, profile)})
        assert lefts == [-50.0, 50.0, 150.0, 250.0, 350.0]
        assert {round(patch.get_width(), 6) for patch in _geology(ax, profile)} == {100.0}
    finally:
        plt.close(fig)


def _geology(ax, profile):
    """The column rectangles: everything except the zone band, which starts at the highest surface."""
    top = max(column.surface_mtaw for column in profile.columns)
    return [patch for patch in ax.patches if patch.get_y() < top - 1e-9]


def test_the_zone_marking_stays_out_of_the_geology():
    section, profile = _profile_section()
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        top = max(column.surface_mtaw for column in profile.columns)
        band = [patch for patch in ax.patches if patch.get_y() >= top - 1e-9]
        assert len(band) == 1, "the zone is one band in the headroom, not a tint over the columns"
        assert band[0].get_x() == pytest.approx(section.zone_from_m)
        assert band[0].get_width() == pytest.approx(section.zone_to_m - section.zone_from_m)
        # nothing coloured reaches down into the geology
        assert all(p.get_y() + p.get_height() <= top + 1e-9 for p in _geology(ax, profile))
        # the zone edges are two dashed red verticals instead
        edges = [line for line in ax.lines
                 if line.get_linestyle() == "--" and line.get_color() == section_figure.ZONE_COLOUR]
        assert len(edges) == 2
    finally:
        plt.close(fig)


def test_column_width_follows_the_real_spacing_not_the_declared_resolution():
    section, profile = _profile_section()
    profile.resolution_m = 10.0  # the answer was sampled every 100 m; the drawing must follow that
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        assert {round(patch.get_width(), 6) for patch in _geology(ax, profile)} == {100.0}
    finally:
        plt.close(fig)


def test_the_surface_line_steps_over_the_flat_topped_columns():
    section, _ = _profile_section()
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        surface = next(line for line in ax.lines if line.get_label() == "maaiveld (G3Dv3)")
        assert surface.get_drawstyle() == "steps-mid"
    finally:
        plt.close(fig)


def test_section_legend_labels_are_shortened_to_fit():
    section, _ = _profile_section()
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert labels and all(len(label) <= 48 for label in labels)
        # the longest DOV formation name is shortened, not dropped
        assert any(label.startswith("Formatie van Rozebeke") for label in labels)
    finally:
        plt.close(fig)


def test_section_with_a_profile_marks_the_doorprik_anchors_in_the_legend():
    section, _ = _profile_section()
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert "doorprik" in labels
        assert "maaiveld (G3Dv3)" in labels and "onderzoekszone" in labels
        anchors = [line for line in ax.lines
                   if line.get_linestyle() == "--" and line.get_color() == section_figure.ANCHOR_COLOUR]
        assert len(anchors) == 3  # one per doorprik anchor
    finally:
        plt.close(fig)


def test_section_without_a_profile_still_draws_the_anchor_columns(tmp_path):
    section, _ = _profile_section()
    section.profile = None
    fig, ax = section_figure._build_section_figure(section, max_depth_m=60.0)
    try:
        assert len(ax.patches) > 1
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert "doorprik" not in labels  # the anchors are the columns here, no separate marker
    finally:
        plt.close(fig)
    assert _png_ok(section_figure.plot_section(section, tmp_path / "fallback.png", max_depth_m=60.0))


def test_section_profile_png_is_written(tmp_path):
    section, _ = _profile_section()
    assert _png_ok(section_figure.plot_section(section, tmp_path / "profile.png", max_depth_m=60.0))


def test_a_crowded_borehole_figure_says_how_many_labels_it_left_out():
    # 40 layers do not fit at the minimum label step, so some labels are dropped; a column with
    # fewer labels than bands must say so, otherwise it reads as a borehole with fewer layers.
    fig, ax = borehole_column._build_borehole_figure(_crowded_column(40))
    try:
        notes = [t.get_text() for t in ax.texts if t.get_text().endswith("laaglabels weggelaten")]
        assert len(notes) == 1
        assert notes[0].startswith(str(40 - (len(ax.texts) - 1)))  # the note counts every dropped label
    finally:
        plt.close(fig)


def test_the_skipped_label_note_does_not_sit_on_top_of_the_deepest_label():
    # Inside a full column every spot is taken: the bands fill it to the bottom and the labels run
    # down the right-hand side, so the note has to sit clear of the deepest label to stay readable.
    fig, ax = borehole_column._build_borehole_figure(_crowded_column(40))
    try:
        fig.canvas.draw()
        note = next(t for t in ax.texts if t.get_text().endswith("laaglabels weggelaten"))
        note_box = note.get_window_extent()
        assert all(not note_box.overlaps(label.get_window_extent()) for label in _band_labels(ax))
    finally:
        plt.close(fig)


def test_a_borehole_figure_whose_labels_all_fit_carries_no_note():
    fig, ax = borehole_column._build_borehole_figure(_crowded_column(27))
    try:
        assert not any("weggelaten" in t.get_text() for t in ax.texts)
    finally:
        plt.close(fig)


def test_a_crowded_virtual_borehole_figure_says_how_many_labels_it_left_out():
    layers = [VbLayer(code=f"c{i}", name=f"Eenheid {i}", top_mtaw=20.0 - i, base_mtaw=19.0 - i,
                      thickness_m=1.0, color="#abcdef", texture="") for i in range(40)]
    fig, ax = vb_column._build_vb_figure(VirtualBorehole(0.0, 0.0, "g3dv3_F", layers), max_depth_m=60.0)
    try:
        assert any(t.get_text().endswith("laaglabels weggelaten") for t in ax.texts)
    finally:
        plt.close(fig)


def _cpt_with_profile() -> Cpt:
    return Cpt("2024-090319", "S407", 0, 0, 8.0, 32.2, "2024-04-05", "continu elektrisch", None, None, None, "",
               12.0, profile=parse_cpt_profile(fixture_bytes("sondering_2024-090319.xml")))


def _simple_virtual_borehole() -> VirtualBorehole:
    layers = [VbLayer(code=f"c{i}", name=f"Eenheid {i}", top_mtaw=20.0 - 3 * i, base_mtaw=17.0 - 3 * i,
                      thickness_m=3.0, color="#abcdef", texture="") for i in range(4)]
    return VirtualBorehole(0.0, 0.0, "g3dv3_F", layers)


def test_figure_modules_leave_no_pyplot_state_behind():
    """pyplot parks every figure it makes in a process-global registry and only lets go when
    someone closes it. In a long-running QGIS session that is a leak, and from a worker thread it
    is a race on shared state - so the figure modules must not go through pyplot at all. The
    figures are kept alive in a list on purpose: the question is what the registry holds, not what
    the garbage collector happens to have swept."""
    before = plt.get_fignums()
    figures = [
        common.new_figure((4.0, 3.0)),
        common.new_figure_grid(3, (9.0, 4.0), sharey=True),
        cpt_figure._build_cpt_figure(_cpt_with_profile()),
        borehole_column._build_borehole_figure(_crowded_column(5)),
        vb_column._build_vb_figure(_simple_virtual_borehole()),
        section_figure._build_section_figure(_profile_section()[0]),
    ]
    assert len(figures) == 6
    assert before == [], f"an earlier test leaked pyplot figures: {before}"
    assert plt.get_fignums() == [], "a figure module registered a figure with pyplot"


def test_saving_a_figure_does_not_need_pyplot(tmp_path):
    fig, ax = common.new_figure((4.0, 3.0))
    ax.plot([0, 1], [0, 1])
    assert _png_ok(common.save(fig, tmp_path / "plain.png"))
    assert plt.get_fignums() == []


CROWDED_TESTS = [("GEO-64/286-S2", 100.0), ("GEO-64/286-S3", 103.0), ("GEO-64/097-S1", 130.0),
                 ("GEO-64/097-S2", 140.0), ("GEO-73/488-SIII", 180.0), ("GEO-73/422-SXIII", 237.0),
                 ("Gent-inventarisatie-p17/1", 290.0)]


def _crowded_section() -> Section:
    """The profile section with seven projected tests, two of them 3 m apart - closer than one
    upright label is wide, so they cannot share a lane."""
    section, _ = _profile_section()
    section.projected = [ProjectedPoint("cpt", name, along, 5.0, 14.0, 20.0) for name, along in CROWDED_TESTS]
    return section


def _test_labels(ax):
    """The labels of the projected tests: everything but the note counting the ones left out."""
    return [t for t in ax.texts if not t.get_text().endswith("weggelaten")]


def test_section_test_labels_do_not_overlap_each_other():
    fig, ax = section_figure._build_section_figure(_crowded_section(), max_depth_m=60.0)
    fig.canvas.draw()
    labels = _test_labels(ax)
    assert len(labels) >= 6, "at most one of seven labels may be dropped on this line"
    boxes = [(t.get_text(), t.get_window_extent()) for t in labels]
    for i, (name, box) in enumerate(boxes):
        for other_name, other in boxes[i + 1:]:
            assert not box.overlaps(other), f"{name!r} overlaps {other_name!r}"


def test_section_test_labels_sit_above_the_axes_clear_of_the_title():
    fig, ax = section_figure._build_section_figure(_crowded_section(), max_depth_m=60.0)
    fig.canvas.draw()
    axes_top = ax.get_window_extent().y1
    title_box = ax.title.get_window_extent()
    for text in _test_labels(ax):
        box = text.get_window_extent()
        assert box.y0 >= axes_top - 1.0, f"{text.get_text()!r} hangs into the plot"
        assert not box.overlaps(title_box), f"{text.get_text()!r} runs into the title"


def _colour_section(colour_a: str, colour_b: str) -> Section:
    layers = [VbLayer("a", "Formatie van Gent", 20.0, 10.0, 10.0, colour_a, ""),
              VbLayer("b", "Formatie van Rozebeke", 10.0, 0.0, 10.0, colour_b, "")]
    columns = [ProfileColumn(along_m=x, surface_mtaw=20.0, layers=layers) for x in (0.0, 10.0)]
    profile = SectionProfile(model="g3dv3_F", resolution_m=10.0, columns=columns)
    return Section(line=((0.0, 0.0), (20.0, 0.0)), boreholes=[], projected=[], zone_from_m=0.0,
                   zone_to_m=20.0, profile=profile)


def _hatched_formations(ax):
    """Which of the drawn layer colours carry a hatch, keyed by their legend label."""
    legend = zip(ax.get_legend().get_texts(), ax.get_legend().legend_handles)
    return {label.get_text() for label, handle in legend if getattr(handle, "get_hatch", bool)()}


def test_two_formations_in_near_identical_colours_are_told_apart_by_a_hatch():
    # DOV hands out several flat yellows a few hundredths of an RGB step apart; printed side by
    # side they read as one unit, which is exactly the mistake a section must not invite.
    fig, ax = section_figure._build_section_figure(_colour_section("#f5e07a", "#f3de78"), max_depth_m=60.0)
    assert _hatched_formations(ax) == {"Formatie van Rozebeke"}  # the later one gets the hatch
    hatched = [p for p in ax.patches if p.get_hatch()]
    assert hatched, "the columns themselves must carry the hatch, not just the legend"


def test_formations_in_clearly_different_colours_stay_flat():
    fig, ax = section_figure._build_section_figure(_colour_section("#f5e07a", "#6b4f2a"), max_depth_m=60.0)
    assert _hatched_formations(ax) == set()
    assert not [p for p in ax.patches if p.get_hatch()]
