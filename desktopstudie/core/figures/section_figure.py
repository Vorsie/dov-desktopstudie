"""Cross-section: virtual boreholes as coloured columns at their true chainage along the line,
surface line through their tops, zone extent shaded, projected investigations as vertical
markers."""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import List, Optional, Sequence

from .. import geometry
from ..model import Section
from .common import plt, save

DEFAULT_COLUMN_HALF_WIDTH_M = 25.0  # fallback when there is only one borehole to place


def _surface_at(along: float, xs: Sequence[float], surfaces: Sequence[Optional[float]]) -> float:
    """Linear interpolation of the modelled surface between sampled virtual boreholes."""
    pts = [(x, s) for x, s in zip(xs, surfaces) if s is not None]
    if not pts:
        return 0.0
    if along <= pts[0][0]:
        return pts[0][1]
    for (x0, s0), (x1, s1) in zip(pts, pts[1:]):
        if x0 <= along <= x1:
            return s0 + (s1 - s0) * (along - x0) / (x1 - x0) if x1 > x0 else s0
    return pts[-1][1]


def _chainages(section: Section) -> List[float]:
    """Distance along the section line for each borehole, from its real (x, y) position - not
    its index - so projected CPTs/boreholes (also given in along-line metres) line up with the
    virtual-borehole columns even when some boreholes are missing (failed_points > 0)."""
    p, q = section.line
    return [geometry.project_onto_line((vb.x, vb.y), p, q)[0] for vb in section.boreholes]


def _column_half_width(xs: Sequence[float]) -> float:
    """Half the median gap between consecutive chainages, so regularly spaced columns touch with
    no gaps; a real gap (a failed point, or irregular sampling) stays visible."""
    ordered = sorted(xs)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    if not gaps:
        return DEFAULT_COLUMN_HALF_WIDTH_M
    return statistics.median(gaps) / 2.0


def _build_section_figure(section: Section, max_depth_m: float = 60.0):
    xs = _chainages(section)
    half_width = _column_half_width(xs)
    fig, ax = plt.subplots(figsize=(11, 6))
    surfaces: List[Optional[float]] = []
    seen = {}
    for x, vb in zip(xs, section.boreholes):
        surfaces.append(vb.surface_mtaw)
        floor = (vb.surface_mtaw or 0.0) - max_depth_m
        for layer in vb.layers:
            if layer.top_mtaw <= floor:
                break
            base = max(layer.base_mtaw, floor)
            ax.add_patch(plt.Rectangle((x - half_width, base), 2 * half_width, layer.top_mtaw - base,
                                       facecolor=layer.color, edgecolor="#555555", lw=0.3))
            seen.setdefault(layer.name, layer.color)
    plot_surfaces = [s if s is not None else float("nan") for s in surfaces]
    if xs:
        # extend the surface line flat to the outer edge of the first/last column, so it spans
        # the full drawn width rather than stopping at the outermost borehole's centre
        line_xs = [xs[0] - half_width] + xs + [xs[-1] + half_width]
        line_ys = [plot_surfaces[0]] + plot_surfaces + [plot_surfaces[-1]]
    else:
        line_xs, line_ys = [], []
    surface_line, = ax.plot(line_xs, line_ys, color="black", lw=1.2, label="maaiveld (G3Dv3)")
    zone = ax.axvspan(section.zone_from_m, section.zone_to_m, color="red", alpha=0.08, label="onderzoekszone")
    for p in section.projected:
        # a test without Z hangs from the modelled surface at its position along the line
        z = p.z_mtaw if p.z_mtaw is not None else _surface_at(p.along_m, xs, surfaces)
        ax.plot([p.along_m, p.along_m], [z, z - (p.depth_m or 0.0)], color="black", lw=1.5)
        ax.text(p.along_m, z + 0.5, p.label, rotation=90, fontsize=6, ha="center", va="bottom")
    left = (min(xs) if xs else 0.0) - half_width
    right = (max(xs) if xs else 0.0) + half_width
    ax.set_xlim(left, right)
    top = max((s for s in surfaces if s is not None), default=0.0)
    bottom = top - max_depth_m
    ax.set_ylim(bottom, top + 5)
    ax.set_xlabel("afstand langs de doorsnedelijn [m]")
    ax.set_ylabel("peil [mTAW]")
    layer_handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor="#555555") for c in seen.values()]
    handles = [surface_line, zone] + layer_handles
    labels = ["maaiveld (G3Dv3)", "onderzoekszone"] + list(seen.keys())
    ax.legend(handles, labels, fontsize=6, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2)
    # vertical exaggeration: how many times taller a metre looks than it is wide, given the
    # rendered figure size and the drawn axis ranges
    fig_w, fig_h = fig.get_size_inches()
    x_range = max(right - left, 1e-9)
    y_range = max((top + 5) - bottom, 1e-9)
    ve = (fig_h / y_range) / (fig_w / x_range)
    title = (f"Geologische doorsnede uit virtuele boringen (DOV G3Dv3) - geen eigen interpretatie - "
             f"verticale overdrijving ≈ {ve:.0f}x")
    if section.failed_points > 0:
        title += f" ({section.failed_points} punt(en) niet beschikbaar)"
    ax.set_title(title, fontsize=9)
    return fig, ax


def plot_section(section: Section, path: Path, max_depth_m: float = 60.0) -> Path:
    fig, _ = _build_section_figure(section, max_depth_m)
    return save(fig, path)
