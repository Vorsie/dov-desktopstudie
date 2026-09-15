"""Lithology column with the (raw) DOV description per layer, coloured by lithology keyword."""
from __future__ import annotations

from pathlib import Path

from ..model import Borehole
from .common import (
    column_figure_height,
    draw_depth_column,
    draw_no_data,
    lithology_colour,
    new_figure,
    note_skipped_labels,
    save,
)


def _build_borehole_figure(bh: Borehole):
    deepest = max((layer.base_m for layer in bh.lithology), default=bh.depth_m or 1.0)
    drawn_depth = max(5.0, deepest)
    fig, ax = new_figure((5.0, column_figure_height(drawn_depth)))
    if not bh.lithology:
        draw_no_data(ax)
    else:
        bands = [(layer.top_m, layer.base_m, lithology_colour(layer.raw.get("hoofdnaam") or layer.description),
                 f"{layer.top_m:.1f}-{layer.base_m:.1f} m: {layer.description}") for layer in bh.lithology]
        _, skipped = draw_depth_column(ax, bands, drawn_depth)
        note_skipped_labels(ax, skipped)
    ax.set_title(f"{bh.number} - {bh.date or 'datum onbekend'} - {bh.distance_m:.0f} m van de zone", fontsize=9)
    return fig, ax


def plot_borehole(bh: Borehole, path: Path) -> Path:
    fig, _ = _build_borehole_figure(bh)
    return save(fig, path)
