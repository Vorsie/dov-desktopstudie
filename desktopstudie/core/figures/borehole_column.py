"""Lithology column with the (raw) DOV description per layer, coloured by lithology keyword."""
from __future__ import annotations

from pathlib import Path

from ..model import Borehole
from .common import draw_depth_column, lithology_colour, plt, save

NO_DATA_MESSAGE = "geen laaggegevens beschikbaar"


def _build_borehole_figure(bh: Borehole):
    deepest = max((layer.base_m for layer in bh.lithology), default=bh.depth_m or 1.0)
    drawn_depth = max(5.0, deepest)
    fig, ax = plt.subplots(figsize=(5.0, max(4.0, min(11.0, 0.18 * drawn_depth + 2.0))))
    if not bh.lithology:
        ax.text(0.5, 0.5, NO_DATA_MESSAGE, ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        bands = [(layer.top_m, layer.base_m, lithology_colour(layer.raw.get("hoofdnaam") or layer.description),
                 f"{layer.top_m:.1f}-{layer.base_m:.1f} m: {layer.description}") for layer in bh.lithology]
        draw_depth_column(ax, bands, drawn_depth)
    ax.set_title(f"{bh.number} - {bh.date or 'datum onbekend'} - {bh.distance_m:.0f} m van de zone", fontsize=9)
    return fig, ax


def plot_borehole(bh: Borehole, path: Path) -> Path:
    fig, _ = _build_borehole_figure(bh)
    return save(fig, path)
