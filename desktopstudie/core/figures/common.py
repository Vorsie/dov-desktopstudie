"""matplotlib setup shared by all figures (headless Agg backend); depth-column drawing and
lithology colours shared by the borehole and virtual-borehole columns.

Figures are built through `new_figure`/`new_figure_grid` rather than `pyplot.subplots`: pyplot
parks every figure it creates in a process-global registry and only lets go when someone calls
close(). Inside a long-running QGIS session that is a leak, and from a QgsTask worker thread it is
a race on shared state. A Figure with its own FigureCanvasAgg has neither problem."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")  # also pins the backend for anyone who does import pyplot (tests, notebooks)
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

DPI = 150

Band = Tuple[float, float, str, str]  # (top_m, base_m, colour, label)

# Label placement inside draw_depth_column: the minimum vertical gap between two consecutive
# labels, as a fraction of the drawn depth range.
LABEL_STEP_FRACTION = 0.028

FALLBACK_LITHOLOGY_COLOUR = "#e6e6e6"

# What a column figure says when the fiche carried no layers at all.
NO_DATA_MESSAGE = "geen laaggegevens beschikbaar"

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


def new_figure(figsize: Tuple[float, float]):
    """A figure pyplot knows nothing about, with an Agg canvas attached so savefig and
    canvas.draw() work straight away. Returns (fig, ax) like pyplot.subplots()."""
    fig = Figure(figsize=figsize)
    FigureCanvasAgg(fig)
    return fig, fig.subplots()


def new_figure_grid(ncols: int, figsize: Tuple[float, float], sharey: bool = False):
    """new_figure with `ncols` axes side by side. The axes always come back as a list, also for
    ncols=1, where fig.subplots() would hand back a bare Axes."""
    fig = Figure(figsize=figsize)
    FigureCanvasAgg(fig)
    axes = fig.subplots(1, ncols, sharey=sharey)
    return fig, [axes] if ncols == 1 else list(axes)


def column_figure_height(drawn_depth: float) -> float:
    """Figure height in inches for a depth column: it grows with the drawn depth, but a 2 m
    borehole is not a stamp and a 60 m one still fits on a page. One formula for every column
    figure, so two columns of the same depth print at the same size side by side."""
    return max(4.0, min(11.0, 0.18 * drawn_depth + 2.0))


def draw_no_data(ax, message: str = NO_DATA_MESSAGE) -> None:
    """The placeholder for a figure with nothing to draw: the reason, centred, on bare axes. The
    ticks have to go - an empty frame carrying a depth scale reads as a measurement of zero
    rather than as data that was never there."""
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def save(fig, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    return path  # nothing to close: the figure is not parked in a pyplot registry


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


# How long a band label may get before it is shortened: wider than this and the label column
# eats the drawing beside it.
LABEL_CHARS = 48


def draw_depth_column(ax, bands: List[Band], max_depth_m: float) -> Tuple[float, int]:
    """Draws stacked `bands` (top_m, base_m, colour, label) as rectangles in x in [0, 1], with a
    label per band at x=1.05. Labels are placed top to bottom without overlapping and without
    leaving the axes: each one sits at its band's midpoint unless that would collide with the
    previous label or with the top edge, in which case it is pushed down by at least one
    label-height step; a thin leader line then connects the band to its moved label. A label
    pushed past the bottom edge is pulled back to half a step above it, and dropped altogether
    when that would collide with the label above. Bands (and their labels) below `max_depth_m`
    are skipped. Returns (drawn depth range (<= max_depth_m), which the caller uses as the
    y-axis range; number of labels dropped for lack of room)."""
    visible = [(top, min(base, max_depth_m), colour, label) for top, base, colour, label in bands
               if top < max_depth_m]
    drawn_depth = min(max_depth_m, max((base for _, base, _, _ in visible), default=max_depth_m))
    for top, base, colour, _ in visible:
        ax.add_patch(Rectangle((0, top), 1, base - top, facecolor=colour, edgecolor="black", lw=0.5))
    step = LABEL_STEP_FRACTION * drawn_depth
    lowest = drawn_depth - step / 2.0  # a label centred deeper than this would cross the bottom edge
    prev_y = None
    skipped = 0
    for top, base, _, label in visible:
        mid = (top + base) / 2.0
        y = max(mid, step / 2.0) if prev_y is None else max(mid, prev_y + step)
        if y > lowest:
            if prev_y is not None and lowest < prev_y + step:
                skipped += 1
                continue
            y = lowest
        prev_y = y
        ax.text(1.05, y, textwrap.shorten(label, LABEL_CHARS), va="center", fontsize=7, clip_on=True)
        if y != mid:
            ax.plot([1.0, 1.04], [mid, y], color="grey", lw=0.5)
    ax.set_xlim(0, 3.6)
    ax.set_ylim(drawn_depth, 0)
    ax.set_xticks([])
    ax.set_ylabel("diepte [m-mv]")
    return drawn_depth, skipped


# One depth column on its own figure. Both column figures - a real borehole and a modelled one -
# print at this width, and a column shallower than this is drawn as if it were this deep: a 1,2 m
# borehole on its own scale is a band of colour with no sense of depth beside it.
COLUMN_WIDTH_IN = 5.0
MIN_COLUMN_DEPTH_M = 5.0
COLUMN_TITLE_PT = 9


def column_figure(bands: Sequence[Band], drawn_depth: float, title: str):
    """The drawing both column figures are: the bands, the labels that fit, a note for the labels
    that did not, and a title.

    What differs between a DOV borehole and a virtual one is where the bands come from and what
    the title says; everything from here down was the same fifteen lines twice.
    """
    fig, ax = new_figure((COLUMN_WIDTH_IN, column_figure_height(drawn_depth)))
    if not bands:
        draw_no_data(ax)
    else:
        _drawn, skipped = draw_depth_column(ax, list(bands), drawn_depth)
        note_skipped_labels(ax, skipped)
    ax.set_title(title, fontsize=COLUMN_TITLE_PT)
    return fig, ax


def note_skipped_labels(ax, skipped: int, what: str = "laaglabels") -> None:
    """Say how many labels had to be dropped for lack of room. Without it a column with fewer
    labels than bands reads as a borehole with fewer layers, and a section with fewer labels than
    tests as a section with fewer tests. Placed as a caption just under the axes: inside them every
    spot is taken - the bands fill the column to the bottom and the labels run down the right-hand
    side - so a note in the bottom-right corner lands on top of the deepest label."""
    if skipped <= 0:
        return
    ax.text(1.0, -0.012, f"{skipped} {what} weggelaten", transform=ax.transAxes,
            ha="right", va="top", fontsize=6, color="grey")
