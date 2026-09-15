"""Cross-section: the DOV profile query drawn as contiguous coloured columns along the line, with
the doorprik anchors it was stacked on marked as dashed verticals - or, when the profile is
missing, those anchors themselves as wide columns. Surface line over the column tops, the study
zone marked outside the geology, projected investigations as vertical markers."""
from __future__ import annotations

import math
import statistics
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from matplotlib.colors import to_rgb

from .. import geometry
from ..model import ProjectedPoint, Section, VbLayer
from .common import Rectangle, new_figure, note_skipped_labels, save

DEFAULT_COLUMN_HALF_WIDTH_M = 25.0  # fallback when there is only one column to place
SURFACE_LABEL = "maaiveld (G3Dv3)"
ZONE_LABEL = "onderzoekszone"
ANCHOR_LABEL = "doorprik"
ANCHOR_COLOUR = "#333333"
ZONE_COLOUR = "red"
HEADROOM_M = 5.0  # air above the highest surface: room for the zone band and the test labels
LEGEND_LABEL_CHARS = 48  # a full DOV formation name is far too long for a 6 pt legend entry
TEST_LABEL_PT = 6
TEST_LABEL_CHARS = 20
LANES = 3  # rows of test labels above the axes; beyond three the header eats the section
LANE_GAP_PT = 2.0  # air between one lane's longest label and the next lane's baseline
BASE_OFFSET_PT = 2.0  # air between the axes top and the first lane
TITLE_GAP_PT = 4.0
DEFAULT_TITLE_PAD_PT = 6.0
# Two DOV colours closer than this in RGB read as one on paper; the later formation gets a hatch.
COLOUR_DISTANCE = 0.08
HATCH = "//"
HATCH_EDGE = "#777777"


def _anchor_chainages(section: Section) -> List[float]:
    """Distance along the section line for each doorprik anchor, from its real (x, y) position -
    not its index - so projected CPTs/boreholes (also given in along-line metres) line up with the
    columns even when some anchors are missing (failed_points > 0)."""
    return geometry.chainages(section.line, [(vb.x, vb.y) for vb in section.boreholes])


def _column_half_width(xs: Sequence[float]) -> float:
    """Half the median gap between consecutive chainages, so regularly spaced columns touch with
    no gaps; a real gap (a failed point, or irregular sampling) stays visible. Taken from the
    chainages actually drawn rather than from a declared resolution, which can disagree with them."""
    ordered = sorted(xs)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    if not gaps:
        return DEFAULT_COLUMN_HALF_WIDTH_M
    return statistics.median(gaps) / 2.0


def _colour_distance(a: str, b: str) -> float:
    return math.dist(to_rgb(a), to_rgb(b))


def hatched_names(layer_lists: Sequence[Sequence[VbLayer]]) -> Set[str]:
    """Formations whose DOV colour is within COLOUR_DISTANCE of one already used by another
    formation. G3Dv3 hands out several flat yellows a few hundredths of an RGB step apart; printed
    side by side they read as one unit, which is the one mistake a section must not invite. The
    FIRST formation to claim a colour keeps it flat, so the drawing order decides who gets the
    hatch and the same section always hatches the same units."""
    claimed: Dict[str, str] = {}  # formation name -> its colour, in drawing order
    hatched: Set[str] = set()
    for layers in layer_lists:
        for layer in layers:
            if layer.name in claimed or layer.name in hatched:
                continue
            if any(_colour_distance(layer.color, other) < COLOUR_DISTANCE for other in claimed.values()):
                hatched.add(layer.name)
            else:
                claimed[layer.name] = layer.color
    return hatched


def _draw_columns(ax, xs: Sequence[float], surfaces: Sequence[Optional[float]],
                  layer_lists: Sequence[Sequence[VbLayer]], half_width: float, max_depth_m: float,
                  lw: float, hatched: Set[str]) -> Dict[str, str]:
    """One coloured column per (chainage, surface, layers) triple, clipped at `max_depth_m` below
    that column's own surface. Returns {layer name: colour} in drawing order, for the legend."""
    seen: Dict[str, str] = {}
    for x, surface, layers in zip(xs, surfaces, layer_lists):
        floor = (surface if surface is not None else 0.0) - max_depth_m
        for layer in layers:
            if layer.top_mtaw <= floor:
                break
            base = max(layer.base_mtaw, floor)
            marked = layer.name in hatched
            ax.add_patch(Rectangle((x - half_width, base), 2 * half_width, layer.top_mtaw - base,
                                   facecolor=layer.color, edgecolor=HATCH_EDGE if marked else "#555555",
                                   lw=lw, hatch=HATCH if marked else None))
            seen.setdefault(layer.name, layer.color)
    return seen


def _draw_surface_line(ax, xs: Sequence[float], surfaces: Sequence[Optional[float]], half_width: float):
    """The surface over the column tops. Drawn with steps-mid so it runs flat across each column
    and jumps at the boundary, exactly like the flat-topped columns underneath it; the duplicated
    end points one full column beyond each end put the outermost step at the outer column edge
    (the overshoot is clipped by the x limits) instead of half a column short of it."""
    plot_surfaces = [s if s is not None else float("nan") for s in surfaces]
    if xs:
        line_xs = [xs[0] - 2 * half_width] + list(xs) + [xs[-1] + 2 * half_width]
        line_ys = [plot_surfaces[0]] + plot_surfaces + [plot_surfaces[-1]]
    else:
        line_xs, line_ys = [], []
    handle, = ax.plot(line_xs, line_ys, color="black", lw=1.2, drawstyle="steps-mid", label=SURFACE_LABEL)
    return handle


def _draw_zone(ax, section: Section, top: float):
    """The study zone marked WITHOUT tinting the geology: a light band in the headroom above the
    highest surface, plus a dashed vertical at each edge. A translucent overlay across the columns
    would shift every layer colour inside the zone, which is exactly where the reader compares them."""
    band = ax.add_patch(Rectangle((section.zone_from_m, top), section.zone_to_m - section.zone_from_m,
                                      HEADROOM_M, facecolor=ZONE_COLOUR, alpha=0.15, edgecolor="none"))
    for x in (section.zone_from_m, section.zone_to_m):
        ax.axvline(x, color=ZONE_COLOUR, lw=1.0, linestyle="--", zorder=3)
    return band


def _draw_anchors(ax, section: Section, xs: Sequence[float], surfaces: Sequence[Optional[float]],
                  max_depth_m: float):
    """The doorprik anchors as thin dashed verticals: they carry the elevations the profile was
    stacked on, so the reader can see which columns are pinned and which are interpolated."""
    handle = None
    for x, vb in zip(_anchor_chainages(section), section.boreholes):
        top = vb.surface_mtaw if vb.surface_mtaw is not None else geometry.interpolate(x, xs, surfaces)
        drawn, = ax.plot([x, x], [top, top - max_depth_m], color=ANCHOR_COLOUR, lw=0.7,
                         linestyle="--", zorder=3)
        handle = handle or drawn
    return handle


def _zone_proxy():
    """One legend swatch showing both halves of the zone marking: the headroom band and the dashed
    edge."""
    return Rectangle((0, 0), 1, 1, facecolor=ZONE_COLOUR, alpha=0.15, edgecolor=ZONE_COLOUR,
                         linestyle="--", lw=1.0)


def _draw_legend(ax, surface_line, anchor_line, seen: Dict[str, str], hatched: Set[str]) -> None:
    handles = [surface_line, _zone_proxy()]
    labels = [SURFACE_LABEL, ZONE_LABEL]
    if anchor_line is not None:
        handles.append(anchor_line)
        labels.append(ANCHOR_LABEL)
    handles += [Rectangle((0, 0), 1, 1, facecolor=colour, edgecolor="#555555",
                          hatch=HATCH if name in hatched else None)
                for name, colour in seen.items()]
    labels += [textwrap.shorten(name, LEGEND_LABEL_CHARS) for name in seen]
    ax.legend(handles, labels, fontsize=6, loc="upper left", bbox_to_anchor=(0, -0.12),
              ncol=2 if len(labels) <= 8 else 3)


def _short_label(text: str) -> str:
    """textwrap.shorten is no use here: a test number is a single word, and shorten replaces a word
    that does not fit with a bare '[...]' - losing the whole name."""
    return text if len(text) <= TEST_LABEL_CHARS else text[: TEST_LABEL_CHARS - 1] + "…"


def _draw_test_labels(fig, ax, projected: Sequence[ProjectedPoint]) -> Tuple[int, float]:
    """The projected tests' labels, above the axes instead of inside them: inside, a label covers
    the very columns it annotates and, on a busy line, its neighbours as well.

    Each label is turned upright, so it is about one character WIDE and its whole name TALL. That
    is what fixes the lane height: a lane has to clear the longest label, because staggering two
    neighbours by a few points would still leave them overlapping over the rest of their length.
    A label goes in the lowest lane whose previous label is at least one label width away; a test
    that finds no free lane is dropped and counted. Returns (dropped, the title padding in points
    that the lanes actually used need)."""
    if not projected:
        return 0, 0.0
    order = sorted(projected, key=lambda p: p.along_m)
    anns = [ax.annotate(_short_label(p.label), xy=(p.along_m, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(0, BASE_OFFSET_PT), textcoords="offset points", rotation=90,
                        rotation_mode="anchor", ha="left", va="center", fontsize=TEST_LABEL_PT,
                        clip_on=False)
            for p in order]
    # A renderer is enough to measure text; fig.canvas.draw() would paint every column first,
    # which on a 40-column profile costs more than the whole rest of the figure.
    renderer = fig.canvas.get_renderer()
    px_per_pt = fig.dpi / 72.0
    boxes = [ann.get_window_extent(renderer) for ann in anns]
    lane_step_pt = max(box.height for box in boxes) / px_per_pt + LANE_GAP_PT
    axes_px = ax.get_window_extent().width
    x_lo, x_hi = ax.get_xlim()
    label_width_m = (max(box.width for box in boxes) * (x_hi - x_lo) / axes_px) if axes_px else 0.0
    last_in_lane: List[Optional[float]] = [None] * LANES
    skipped = 0
    highest_lane = 0
    for point, ann in zip(order, anns):
        lane = next((i for i in range(LANES)
                     if last_in_lane[i] is None or point.along_m - last_in_lane[i] >= label_width_m), None)
        if lane is None:
            skipped += 1
            ann.remove()
            continue
        last_in_lane[lane] = point.along_m
        highest_lane = max(highest_lane, lane)
        ann.set_position((0.0, BASE_OFFSET_PT + lane * lane_step_pt))
    return skipped, BASE_OFFSET_PT + highest_lane * lane_step_pt + (lane_step_pt - LANE_GAP_PT) + TITLE_GAP_PT


def _title(section: Section, fig, left: float, right: float, bottom: float, top: float,
           has_profile: bool) -> str:
    # vertical exaggeration: how many times taller a metre looks than it is wide, given the
    # rendered figure size and the drawn axis ranges
    fig_w, fig_h = fig.get_size_inches()
    x_range = max(right - left, 1e-9)
    y_range = max((top + HEADROOM_M) - bottom, 1e-9)
    ve = (fig_h / y_range) / (fig_w / x_range)
    source = (f"profielbevraging elke {section.profile.resolution_m:.0f} m" if has_profile
              else "virtuele boringen")
    title = (f"Geologische doorsnede uit {source} (DOV G3Dv3) - geen eigen interpretatie - "
             f"verticale overdrijving ≈ {ve:.0f}x")
    if section.failed_points > 0:
        title += f" ({section.failed_points} punt(en) niet beschikbaar)"
    return title


def _build_section_figure(section: Section, max_depth_m: float = 60.0):
    fig, ax = new_figure((11, 6))
    profile = section.profile
    has_profile = profile is not None and bool(profile.columns)
    if has_profile:
        xs = [column.along_m for column in profile.columns]
        surfaces: List[Optional[float]] = [column.surface_mtaw for column in profile.columns]
        layer_lists = [column.layers for column in profile.columns]
        lw = 0.0  # no visible outline: at profile resolution the columns must read as bands
    else:
        xs = _anchor_chainages(section)
        surfaces = [vb.surface_mtaw for vb in section.boreholes]
        layer_lists = [vb.layers for vb in section.boreholes]
        lw = 0.3
    half_width = _column_half_width(xs)
    hatched = hatched_names(layer_lists)
    seen = _draw_columns(ax, xs, surfaces, layer_lists, half_width, max_depth_m, lw, hatched)
    surface_line = _draw_surface_line(ax, xs, surfaces, half_width)
    top = max((s for s in surfaces if s is not None), default=0.0)
    _draw_zone(ax, section, top)
    anchor_line = _draw_anchors(ax, section, xs, surfaces, max_depth_m) if has_profile else None
    for p in section.projected:
        # a test without Z hangs from the modelled surface at its position along the line
        z = p.z_mtaw if p.z_mtaw is not None else geometry.interpolate(p.along_m, xs, surfaces)
        ax.plot([p.along_m, p.along_m], [z, z - (p.depth_m or 0.0)], color="black", lw=1.5)
    left = (min(xs) if xs else 0.0) - half_width
    right = (max(xs) if xs else 0.0) + half_width
    bottom = top - max_depth_m
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top + HEADROOM_M)
    ax.set_xlabel("afstand langs de doorsnedelijn [m]")
    ax.set_ylabel("peil [mTAW]")
    _draw_legend(ax, surface_line, anchor_line, seen, hatched)
    # the labels need the final x limits: their lanes are spaced in data units
    skipped, title_pad = _draw_test_labels(fig, ax, section.projected)
    note_skipped_labels(ax, skipped, what="proeflabels")
    ax.set_title(_title(section, fig, left, right, bottom, top, has_profile), fontsize=9,
                 pad=max(DEFAULT_TITLE_PAD_PT, title_pad))
    return fig, ax


def plot_section(section: Section, path: Path, max_depth_m: float = 60.0) -> Path:
    fig, _ = _build_section_figure(section, max_depth_m)
    return save(fig, path)
