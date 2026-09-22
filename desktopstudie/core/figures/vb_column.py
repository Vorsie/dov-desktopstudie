"""Virtual borehole column coloured with DOV layer colours, depth below surface on the axis."""
from __future__ import annotations

from pathlib import Path

from ..model import VirtualBorehole
from .common import MIN_COLUMN_DEPTH_M, column_figure, save


def _build_vb_figure(vb: VirtualBorehole, max_depth_m: float = 60.0):
    deepest = max((vb.depth_of(layer)[1] for layer in vb.layers), default=max_depth_m)
    bands = [(vb.depth_of(layer)[0], vb.depth_of(layer)[1], layer.color,
              f"{layer.name} ({layer.top_mtaw:.1f} / {layer.base_mtaw:.1f} mTAW)")
             for layer in vb.layers]
    title = (f"Virtuele boring {vb.model} - maaiveld {vb.surface_mtaw:.2f} mTAW"
             if vb.surface_mtaw is not None else f"Virtuele boring {vb.model}")
    return column_figure(bands, max(MIN_COLUMN_DEPTH_M, min(max_depth_m, deepest)), title)


def plot_virtual_borehole(vb: VirtualBorehole, path: Path, max_depth_m: float = 60.0) -> Path:
    fig, _ = _build_vb_figure(vb, max_depth_m)
    return save(fig, path)
