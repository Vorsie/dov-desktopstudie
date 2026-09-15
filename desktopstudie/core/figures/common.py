"""matplotlib setup shared by all figures (headless Agg backend); depth-column drawing and
lithology colours shared by the borehole and virtual-borehole columns."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DPI = 150

Band = Tuple[float, float, str, str]  # (top_m, base_m, colour, label)

# Label placement inside draw_depth_column: the minimum vertical gap between two consecutive
# labels, as a fraction of the drawn depth range.
LABEL_STEP_FRACTION = 0.028

FALLBACK_LITHOLOGY_COLOUR = "#e6e6e6"

# Free-text Dutch keyword -> colour, checked in this order (first match in the lowercased text
# wins); a keyword need not be a whole word.
_KEYWORD_COLOURS = [
    ("veen", "#6b4f2a"),
    ("klei", "#9fb8a0"),
    ("leem", "#c9a66b"),
    ("silt", "#d9c9a3"),
    ("grind", "#e8a04c"),
    ("zand", "#f5e07a"),
    ("steen", "#b0b0b0"),
    ("rots", "#b0b0b0"),
    ("krijt", "#b0b0b0"),
]

# DOV coded hoofdnaam -> colour, matched exactly before the keyword scan.
_CODE_COLOURS = {
    "FZ": "#f5e07a", "MZ": "#f5e07a", "GZ": "#f5e07a",  # fijn/midden/grof zand
    "K": "#9fb8a0",   # klei
    "L": "#c9a66b",   # leem
    "V": "#6b4f2a",   # veen
    "G": "#e8a04c",   # grind
}


def save(fig, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def lithology_colour(text: str) -> str:
    """Colour for a lithology description or a DOV coded hoofdnaam. A coded name ('FZ', 'K', ...)
    is matched exactly first; otherwise the first Dutch keyword found in the lowercased text wins;
    unrecognised text gets a neutral grey."""
    if text in _CODE_COLOURS:
        return _CODE_COLOURS[text]
    lower = text.lower()
    for keyword, colour in _KEYWORD_COLOURS:
        if keyword in lower:
            return colour
    return FALLBACK_LITHOLOGY_COLOUR


def draw_depth_column(ax, bands: List[Band], max_depth_m: float, label_chars: int = 55) -> float:
    """Draws stacked `bands` (top_m, base_m, colour, label) as rectangles in x in [0, 1], with a
    label per band at x=1.05. Labels are placed top to bottom without overlapping: each one sits
    at its band's midpoint unless that would collide with the previous label, in which case it is
    pushed down by at least one label-height step; a thin leader line then connects the band to
    its moved label. Bands (and their labels) below `max_depth_m` are skipped. Returns the drawn
    depth range (<= max_depth_m), which the caller uses as the y-axis range."""
    visible = [(top, min(base, max_depth_m), colour, label) for top, base, colour, label in bands
               if top < max_depth_m]
    drawn_depth = min(max_depth_m, max((base for _, base, _, _ in visible), default=max_depth_m))
    for top, base, colour, _ in visible:
        ax.add_patch(plt.Rectangle((0, top), 1, base - top, facecolor=colour, edgecolor="black", lw=0.5))
    step = LABEL_STEP_FRACTION * drawn_depth
    prev_y = None
    for top, base, _, label in visible:
        mid = (top + base) / 2.0
        y = mid if prev_y is None else max(mid, prev_y + step)
        prev_y = y
        ax.text(1.05, y, textwrap.shorten(label, label_chars), va="center", fontsize=7, clip_on=True)
        if y != mid:
            ax.plot([1.0, 1.04], [mid, y], color="grey", lw=0.5)
    ax.set_xlim(0, 3.6)
    ax.set_ylim(drawn_depth, 0)
    ax.set_xticks([])
    ax.set_ylabel("diepte [m-mv]")
    return drawn_depth
