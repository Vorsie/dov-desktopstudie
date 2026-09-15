"""Virtual borehole column coloured with DOV layer colours, depth below surface on the axis."""
from __future__ import annotations

from pathlib import Path

from ..model import VirtualBorehole
from .common import plt, save


def plot_virtual_borehole(vb: VirtualBorehole, path: Path, max_depth_m: float = 60.0) -> Path:
    fig, ax = plt.subplots(figsize=(5.0, 8.0))
    for layer in vb.layers:
        top, base = vb.depth_of(layer)
        if top >= max_depth_m:
            break
        base = min(base, max_depth_m)
        ax.add_patch(plt.Rectangle((0, top), 1, base - top, facecolor=layer.color, edgecolor="black", lw=0.5))
        ax.text(1.05, (top + base) / 2, f"{layer.name} ({layer.top_mtaw:.1f} / {layer.base_mtaw:.1f} mTAW)",
                va="center", fontsize=7)
    ax.set_xlim(0, 3.5)
    ax.set_ylim(max_depth_m, 0)
    ax.set_xticks([])
    ax.set_ylabel("diepte [m-mv]")
    title = (f"Virtuele boring {vb.model} - maaiveld {vb.surface_mtaw:.2f} mTAW"
             if vb.surface_mtaw is not None else f"Virtuele boring {vb.model}")
    ax.set_title(title, fontsize=9)
    return save(fig, path)
