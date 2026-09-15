"""Virtual borehole column coloured with DOV layer colours, depth below surface on the axis."""
from __future__ import annotations

from pathlib import Path

from ..model import VirtualBorehole
from .common import (
    column_figure_height,
    draw_depth_column,
    draw_no_data,
    new_figure,
    note_skipped_labels,
    save,
)


def _build_vb_figure(vb: VirtualBorehole, max_depth_m: float = 60.0):
    deepest = max((vb.depth_of(layer)[1] for layer in vb.layers), default=max_depth_m)
    drawn_depth = max(5.0, min(max_depth_m, deepest))
    fig, ax = new_figure((5.0, column_figure_height(drawn_depth)))
    if not vb.layers:
        draw_no_data(ax)
    else:
        bands = [(vb.depth_of(layer)[0], vb.depth_of(layer)[1], layer.color,
                 f"{layer.name} ({layer.top_mtaw:.1f} / {layer.base_mtaw:.1f} mTAW)") for layer in vb.layers]
        _, skipped = draw_depth_column(ax, bands, drawn_depth)
        note_skipped_labels(ax, skipped)
    title = (f"Virtuele boring {vb.model} - maaiveld {vb.surface_mtaw:.2f} mTAW"
             if vb.surface_mtaw is not None else f"Virtuele boring {vb.model}")
    ax.set_title(title, fontsize=9)
    return fig, ax


def plot_virtual_borehole(vb: VirtualBorehole, path: Path, max_depth_m: float = 60.0) -> Path:
    fig, _ = _build_vb_figure(vb, max_depth_m)
    return save(fig, path)
