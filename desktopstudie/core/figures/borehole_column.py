"""Lithology column with the (raw) DOV description per layer."""
from __future__ import annotations

import textwrap
from pathlib import Path

from ..model import Borehole
from .common import plt, save

FILL = ["#f2e6c9", "#d9d9d9", "#c9dff2", "#e2efda", "#fbe5d6"]


def plot_borehole(bh: Borehole, path: Path) -> Path:
    depth = max((layer.base_m for layer in bh.lithology), default=bh.depth_m or 1.0)
    fig, ax = plt.subplots(figsize=(4.5, max(4.0, min(12.0, depth * 0.25 + 1.5))))
    for i, layer in enumerate(bh.lithology):
        ax.add_patch(plt.Rectangle((0, layer.top_m), 1, layer.base_m - layer.top_m, facecolor=FILL[i % len(FILL)],
                                   edgecolor="black", lw=0.5))
        label = f"{layer.top_m:.1f}-{layer.base_m:.1f} m: {layer.description}"
        ax.text(1.05, (layer.top_m + layer.base_m) / 2, textwrap.shorten(label, 70), va="center", fontsize=7)
    ax.set_xlim(0, 3.5)
    ax.set_ylim(depth, 0)
    ax.set_xticks([])
    ax.set_ylabel("diepte [m-mv]")
    ax.set_title(f"{bh.number} - {bh.date or 'datum onbekend'} - {bh.distance_m:.0f} m van de zone", fontsize=9)
    return save(fig, path)
