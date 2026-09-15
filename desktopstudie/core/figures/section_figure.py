"""Cross-section: virtual boreholes as coloured columns along the line, surface line through
their tops, zone extent shaded, projected investigations as vertical markers."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from ..model import Section
from .common import plt, save


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


def plot_section(section: Section, path: Path, max_depth_m: float = 60.0) -> Path:
    n = len(section.boreholes)
    length = ((section.line[1][0] - section.line[0][0]) ** 2 + (section.line[1][1] - section.line[0][1]) ** 2) ** 0.5
    spacing = length / max(n - 1, 1)
    fig, ax = plt.subplots(figsize=(11, 6))
    surfaces: List[Optional[float]] = []
    seen = {}
    for i, vb in enumerate(section.boreholes):
        x = i * spacing
        surfaces.append(vb.surface_mtaw)
        floor = (vb.surface_mtaw or 0.0) - max_depth_m
        for layer in vb.layers:
            if layer.top_mtaw <= floor:
                break
            base = max(layer.base_mtaw, floor)
            ax.add_patch(plt.Rectangle((x - spacing * 0.45, base), spacing * 0.9, layer.top_mtaw - base,
                                       facecolor=layer.color, edgecolor="#555555", lw=0.3))
            seen.setdefault(layer.name, layer.color)
    xs = [i * spacing for i in range(n)]
    plot_surfaces = [s if s is not None else float("nan") for s in surfaces]
    ax.plot(xs, plot_surfaces, color="black", lw=1.2, label="maaiveld (G3Dv3)")
    ax.axvspan(section.zone_from_m, section.zone_to_m, color="red", alpha=0.08, label="onderzoekszone")
    for p in section.projected:
        # a test without Z hangs from the modelled surface at its position along the line
        z = p.z_mtaw if p.z_mtaw is not None else _surface_at(p.along_m, xs, surfaces)
        ax.plot([p.along_m, p.along_m], [z, z - (p.depth_m or 0.0)], color="black", lw=1.5)
        ax.text(p.along_m, z + 0.5, p.label, rotation=90, fontsize=6, ha="center", va="bottom")
    ax.set_xlim(-spacing * 0.5, length + spacing * 0.5)
    top = max((s for s in surfaces if s is not None), default=0.0)
    ax.set_ylim(top - max_depth_m, top + 5)
    ax.set_xlabel("afstand langs de doorsnedelijn [m]")
    ax.set_ylabel("peil [mTAW]")
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor="#555555") for c in seen.values()]
    ax.legend(handles, list(seen.keys()), fontsize=6, loc="lower left", ncol=2, framealpha=0.9)
    title = "Geologische doorsnede uit virtuele boringen (DOV G3Dv3) - geen eigen interpretatie"
    if section.failed_points > 0:
        title += f" ({section.failed_points} punt(en) niet beschikbaar)"
    ax.set_title(title, fontsize=9)
    return save(fig, path)
