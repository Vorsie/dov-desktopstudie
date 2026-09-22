"""Lithology column with the (raw) DOV description per layer, coloured by lithology keyword."""
from __future__ import annotations

from pathlib import Path

from ..model import Borehole
from .common import MIN_COLUMN_DEPTH_M, column_figure, lithology_colour, save


def _build_borehole_figure(bh: Borehole):
    deepest = max((layer.base_m for layer in bh.lithology), default=bh.depth_m or 1.0)
    bands = [(layer.top_m, layer.base_m,
              lithology_colour(layer.raw.get("hoofdnaam") or layer.description),
              f"{layer.top_m:.1f}-{layer.base_m:.1f} m: {layer.description}")
             for layer in bh.lithology]
    title = f"{bh.number} - {bh.date or 'datum onbekend'} - {bh.distance_m:.0f} m van de zone"
    return column_figure(bands, max(MIN_COLUMN_DEPTH_M, deepest), title)


def plot_borehole(bh: Borehole, path: Path) -> Path:
    fig, _ = _build_borehole_figure(bh)
    return save(fig, path)
