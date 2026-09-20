"""Builds one multi-page QgsPrintLayout from the core's Report tree.

The core decides *what* the report says (chapters -> MapPage / FigurePage / TablePage / TextPage);
this module decides only where it lands on the paper. A4 portrait, 15 mm margins, one layout page
per report page, a title page in front, and separate legend pages behind every map that asks for
one.

Two things here are less obvious than they look.

*Legends are pictures, not QgsLayoutItemLegend.* That item asks the WMS for its GetLegendGraphic
asynchronously, through the network queue of a running QGIS; in a headless export nothing ever
answers and the page comes out blank. So `prepare_legends` fetches every legend up front with the
core's HttpClient and `legend_pages` places the PNG. A legend taller than a sheet is sliced into
page-sized strips rather than shrunk into an unreadable stamp.

*The page index always comes from the page collection, never from a counter.* A table with
`ExtendToNextPage` appends pages of its own while it re-flows, so any count we keep ourselves is
stale the moment a table overruns, and the next report page lands on top of the last table page.

`build_layout(..., legends=False)` is the real legend switch: those pages are never created, so
the page numbers stay continuous. The layout variable `legendas` is a convenience *inside QGIS* -
set it to 0 and every legend page drops out of the next export - but the footer numbers then skip
the pages that were left out, because the numbering belongs to the layout, not to the export: every
footer carries "pagina n / N" as text, written when the layout is complete (`_number_footers`).
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils,
    QgsFillSymbol,
    QgsLayoutFrame,
    QgsLayoutItemLabel,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutItemTextTable,
    QgsLayoutMultiFrame,
    QgsLayoutObject,
    QgsLayoutTable,
    QgsLayoutTableColumn,
    QgsLayoutUtils,
    QgsMapLayer,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsRectangle,
    QgsTextFormat,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QTransform,
)

from ..core import catalogue, geometry, parallel
from ..core.catalogue import BASE_MAP_ID, MapEntry
from ..core.geometry import BBox
from ..core.model import StudyResult
from ..core.report_content import (
    QUARTAIR_CODE,
    QUARTAIR_ID,
    QUARTAIR_IMAGE,
    Chapter,
    ColourRamp,
    FigurePage,
    LegendPage,
    MapPage,
    Report,
    TablePage,
    TextPage,
    profile_image_key,
    quartair_sheet,
    sheet_image_key,
)
from ..core.services.dov_portal import PNG_MAGIC, content_link
from ..core.services.http import DATA_DIR, HttpClient, HttpError, build_url
from . import layers
from .compat import point_mm, size_mm
from .export import PDF_DPI, refresh_data_defined
from .layers import CRS_AUTHID

LAYOUT_NAME = "DOV Desktopstudie"


def layout_name(project: str) -> str:
    """The layout's name in the layout manager: the plugin's name with the study's behind it,
    so two studies in one project keep two layouts and only a same-named study replaces one."""
    return f"{LAYOUT_NAME} - {project}" if project else LAYOUT_NAME
PAGE_SIZE = "A4"
MARGIN = 15.0
CONTENT_W = 180.0
CONTENT_H = 245.0
CONTENT_TOP = 30.0
CONTENT_RIGHT = MARGIN + CONTENT_W  # 195 mm: the right edge the info boxes are pinned to
# The width lives in the catalogue, because the report text reasons about how many metres a
# sheet covers at a map's own scale; one number, drawn here and reasoned about there.
MAP_W, MAP_H = catalogue.MAP_WIDTH_MM, 200.0
NOTE_Y = 25.5
FOOTER_Y = 285.0
INFO_TOP_Y = 46.0
INFO_W, INFO_H = 55.0, 22.0
INFO_MARGIN_MM = 1.0
ARROW_XY, ARROW_WH = (183.0, 32.0), 12.0
LEGEND_VARIABLE = "legendas"
FOOTER_ID = "voettekst"
LEGEND_DIR = "legendas"
NORTH_ARROW = Path(__file__).resolve().parents[1] / "resources" / "noordpijl.svg"
# Arial is the house face, but the PDF is also produced on the Linux CI images and on machines that
# do not have it. Naming the substitutes keeps the metrics predictable instead of leaving the
# choice to whatever fontconfig happens to pick first.
FONT_FAMILIES = ["Arial", "Liberation Sans", "DejaVu Sans"]
BOX_BACKGROUND = QColor(255, 255, 255)  # opaque: the info boxes sit on top of the map
SCALE_BAR_STYLE = "Single Box"
SCALE_BAR_SEGMENTS = 2
# The ladder a reader expects under a scale bar. A segment of 37 m is arithmetically fine and
# unreadable on paper; 50 m is not.
SCALE_BAR_STEPS = (10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
                   20000.0, 50000.0)
SCALE_BAR_FRACTION = 5.0  # one segment is about a fifth of the mapped width
# The scales a reader expects to see printed above a map: the same 1-2-5 idea as the scale bar,
# one rung per usable map scale. A map that had to be widened lands on the next rung UP - rounding
# down would crop away exactly what the widening was for.
SCALE_STEPS = (1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000)
# A legend graphic is authored at screen resolution (96 dpi logical pixels); blown up to the full
# content width its 7 pt labels turn to mush, so it is never drawn larger than this natural size.
MM_PER_PX = 25.4 / 96.0
MAX_TABLE_REFLOW = 20  # a table still growing after this many passes is a bug, not a long table
# A table of this many columns does not fit a portrait sheet, whatever the widths: the sonderingen
# table has nine, and squeezed into 180 mm its last column falls off the paper.
# How tightly a table may be squeezed before it is laid on its side. Decided on MEASURED widths,
# not on the column count: eight narrow columns fit 180 mm easily, and a landscape sheet for them
# cost a three-row table a sheet of its own that nothing else could join. Measured on the real
# tables (portrait budget ~160-170 mm): the nine-column sounding table wants 169 mm and cannot go
# below 127 mm (0.80 of its budget) - squeezed that hard every cell wraps and the fiche numbers
# are unreadable, so it goes landscape. The four-column signal table wants 240 mm but falls back
# to 75 mm (0.44), because its columns are sentences that are MEANT to wrap - it stays portrait.
TABLE_MAX_SQUEEZE = 0.65
# QGIS' own defaults for a text table, spelled out so the orientation can be decided before a table
# exists. `_new_table` reads them off the table itself and the two must agree; the check below
# fails loudly if a QGIS release ever moves them.
TABLE_CELL_MARGIN = 1.0
TABLE_GRID_WIDTH = 0.3
UNBOUNDED_WIDTH = 10_000.0  # no cap: what the columns WANT, not what they are allowed
# The shortest a figure may be squeezed to in order to share a sheet. Below this a qc diagram over
# thirty-five metres is a smudge, and white paper beats an unreadable drawing.
FIGURE_MIN_H = 120.0
# The key under the overview map: a swatch of this size and a line of this height per symbol.
KEY_SWATCH = 3.0
KEY_ROW_H = 4.2

# QGIS draws a string about seven per cent wider than Qt's own metrics say (measured on a 6 pt
# line: 55.4 mm against 51.9 mm). Column widths are estimated with Qt's metrics, so they carry
# that factor - a column measured too narrow wraps text that had room.
TEXT_WIDTH_FUDGE = 1.07
TABLE_FONT_PT = 7.0
# No single column may claim more than this of the width, however long its longest word is: a URL
# of ninety characters would otherwise leave the other columns a few millimetres each.
MAX_COLUMN_SHARE = 0.4
LEGEND_WORKERS = 4
DEFAULT_EXTENT_FACTOR = 3.0
# What a map page keeps for its map, and what it gives to the legend under it. There were already
# four centimetres of white paper under every map frame (the frame ends at 230 mm, the band at
# 275), so a short zone legend costs the map nothing; a longer one shortens the frame, and never
# past MAP_MIN_H - a map of less than half a sheet has stopped being a map.
MAP_MIN_H = 120.0
# Slack for "does this still fit on the paper" comparisons. Heights are millimetres computed by
# adding and subtracting the same constants in a different order, so an exact fit lands a hair
# either side of zero; below this nothing is drawable anyway.
FIT_TOLERANCE_MM = 0.01
# Between the map frame and what stands under it: the scale bar (12.3 mm measured on 3.40.15)
# plus air. Everything below the frame is placed from here, so the bar and the legend cannot
# collide when the frame moves up.
UNDER_MAP_GAP = 16.0
UNDER_MAP_TITLE_H = 5.0
UNDER_MAP_BLOCK_GAP = 3.0
INFO_BOTTOM_LIFT = 20.0  # the bottom info box, measured up from the foot of the map frame
SCALE_BAR_LIFT = 2.0  # the scale bar, measured down from the foot of the map frame
# The colour strip of a map that has no classes but a continuous scale: half the page wide, with
# its two ends named under it and the zone's own heights below that.
RAMP_STRIP_W, RAMP_STRIP_H = 90.0, 5.0
RAMP_LINE_H = 4.5
RAMP_LABEL_GAP = 1.5  # air between the band and the two numbers under it, so they do not touch
# Marking the zone on the strip. Over a scale of 350 metres a building plot is a millimetre wide,
# so a bracket is only drawn when the two ends are this far apart on paper; below it the mean gets
# one tick with a leader line down to its label.
RAMP_SPAN_MIN_MM = 6.0
RAMP_TICK_W = 0.5
RAMP_TICK_H = 2.5
RAMP_MARK_H = RAMP_TICK_H + 0.5
# The line that names the mark stands AT the mark, not at the margin - a leader pointing right
# with its label away to the left points nowhere. Wide enough for "zone 12.52 - 16.25 mTAW", and
# slid back onto the paper when the mark sits near the right end.
RAMP_MARK_LABEL_W = 48.0
RAMP_TICK_LABEL_W = 10.0
RULE_COLOUR = "#000000"
RAMP_SUFFIX = "_schaal"
# A colour ramp is a solid band against the left edge of its legend graphic. Less than this is a
# swatch, not a ramp, and then no strip is cut at all - see `ramp_rect`.
RAMP_MIN_ROWS = 10
RAMP_MIN_COLUMNS = 4
WHITE_RGB = bytes((255, 255, 255))
# A sheet keeps taking pieces of content while they fit: a sheet holding one four-row table is a
# sheet of white paper, and that was the complaint this whole round started from. One chapter per
# sheet, though - a heading belongs to what stands under it. `compact` lifts that last rule too
# and repeats the new chapter's heading, small, where the sheet changes chapter.
PACK_GAP = 6.0
PACKED_TITLE_H = 6.0
PACKED_CHAPTER_H = 5.0
CAPTION_H = 12.0
NOTE_BLOCK_H = 6.0
TEXT_FONT_PT = 9.0
# A label measured on its stripped text still wraps a little worse than measured: words do not
# break, so the last word of a line moves down. A label a millimetre short clips its last line;
# a millimetre too much costs white paper, so the estimate is deliberately generous.
TEXT_HEIGHT_FUDGE = 1.3
TEXT_HEIGHT_PAD = 8.0
# Halvings to find the shortest frame a table still fits in, and the millimetre of slack on the
# answer. Ten steps over a sheet is a quarter of a millimetre - finer than anything on paper.
TABLE_FIT_STEPS = 10
TABLE_FIT_MARGIN = 1.0
TAGS = re.compile(r"<[^>]+>")
NO_COVERAGE_NOTE = "Deze bron levert geen kaartbeeld op deze locatie (geen dekking)."
MISSING_MAP_NOTE = "Kaartbeeld van deze bron niet opgehaald (zie hoofdstuk Bronnen)."
# One GetMap per map page, fetched up front and in parallel, instead of letting the WMS provider
# pull tiles while each page renders. Asked at exactly the size the page prints it, so nothing is
# up- or downscaled on paper; capped at what a service will hand out in one request.
MAP_IMAGE_DIR = "kaarten"
MAP_IMAGE_DPI = PDF_DPI
MAP_IMAGE_MAX_PX = 4096
MAP_IMAGE_WORKERS = 8
# A full-page GetMap is a hundred times the work of a 64 px probe, so it gets a longer breath than
# a legend - but one retry only: the page can be printed without its background.
MAP_IMAGE_TIMEOUT_S = 30.0
MAP_IMAGE_RETRIES = 1
# A theme that paints a few percent of the sheet is a white rectangle with a red circle on it
# unless something recognisable lies under it. `MapEntry.backdrop` asks for the base map at the
# very same box and pixel size, and the theme is painted over it into the one PNG the page draws -
# at the opacity the catalogue gives that map, so the streets stay readable through it.
# The quartair profile-type drawings land next to the map legends, under their own prefix so a
# second run overwrites the file of the same profile type instead of collecting copies.
ZONE_LEGEND_PREFIX = "quartair_"
# The legend page stacks label + strip per entry. A strip is never given more than a fifth of the
# band: it is a picture of three centimetres, and a page holding two of them blown up to a hand's
# width each is a page that says less than it could.
LEGEND_LABEL_H = 5.0
LEGEND_GAP = 4.0
LEGEND_STRIP_MAX_H = CONTENT_H / 5.0
MISSING_DRAWING = "tekening niet opgehaald - zie hoofdstuk Bronnen"
ZONE_LEGEND_SHEET = "kaartblad_"
HEADER_SUFFIX = "_kop"
# A DOV profile-type drawing starts with the type itself - colour swatch, letter code and one line
# of description - and continues with the units table of the whole map sheet. The two are separated
# by a white band, and the first white row BELOW the swatch is the cut. Above HEADER_MIN_ROWS there
# is another white band (under the word "Profieltype"), which is why the search starts there.
HEADER_MIN_ROWS = 60
HEADER_FALLBACK_ROWS = 110
# How often a drawing is asked for. The download links of the dataset portal answer with HTTP 200
# and the portal's own web page instead of the file now and then (live 2026-09-16, the same URL
# gave the PNG minutes earlier), and that answer is not an error the HTTP client can see - so the
# bytes are checked here and a bad answer is asked again, past the cache.
ZONE_LEGEND_TRIES = 2
# One legend out of fourteen, same reasoning as a fiche in the core: a short breath, because three
# full-minute waits on a service that is down cost the report every legend page behind it.
LEGEND_TIMEOUT_S = 15.0
LEGEND_RETRIES = 1


class PageMetrics(NamedTuple):
    """What is usable on one sheet, per orientation. Everything else on the page - the header, the
    footer, a table frame - is placed from these, so a landscape sheet is not a special case with
    its own numbers scattered through the builder."""
    orientation: int
    content_w: float
    content_h: float
    footer_y: float


PORTRAIT = QgsLayoutItemPage.Orientation.Portrait
LANDSCAPE = QgsLayoutItemPage.Orientation.Landscape
# Portrait keeps the numbers the report was built around; landscape is the same A4 turned over:
# 297 - 2 x 15 mm of width, and a content band that ends above the footer at 210 - 12 mm.
_METRICS = {PORTRAIT: PageMetrics(PORTRAIT, CONTENT_W, CONTENT_H, FOOTER_Y),
            LANDSCAPE: PageMetrics(LANDSCAPE, 267.0, 160.0, 198.0)}


def _page_metrics(orientation=PORTRAIT) -> PageMetrics:
    return _METRICS[orientation]


def _font(size: float, bold: bool = False) -> QFont:
    """A layout font in the house face, with the fallbacks that keep a Linux export readable."""
    font = QFont(FONT_FAMILIES[0], int(size))
    if hasattr(font, "setFamilies"):  # Qt >= 5.13, so every supported QGIS - but cheap to ask
        font.setFamilies(FONT_FAMILIES)
    font.setBold(bold)
    return font


def _text_format(size: float, bold: bool = False) -> QgsTextFormat:
    """The text format for a label, a table or a scale bar.

    `QgsLayoutItemLabel.setFont` and `QgsLayoutTable.setContentFont` are already deprecated in 3.34
    and go away in 4.x; the text format is the spelling that survives. It carries its own size, so
    the size is set twice on purpose - the one on the QFont only decides which face gets loaded.
    """
    text_format = QgsTextFormat()
    text_format.setFont(_font(size, bold))
    text_format.setSize(size)
    text_format.setSizeUnit(Qgis.RenderUnit.Points)
    return text_format


def _segment_length(scale: int) -> float:
    """A scale-bar segment of about a fifth of the mapped width, snapped to the 1-2-5 ladder."""
    target = MAP_W / 1000.0 * scale / SCALE_BAR_FRACTION
    return min(SCALE_BAR_STEPS, key=lambda step: abs(step - target))


def _text_width_mm(strings: Sequence[str], size: float, bold: bool = False) -> float:
    """The width in mm of the widest of `strings`, set in the house face at `size` points.

    Measured against a device with a pinned resolution rather than the screen: the same table has
    to come out the same width on a 96 dpi CI image and on the 144 dpi laptop the plugin runs on,
    and a QFontMetricsF without a device follows whatever the screen says. The result carries
    TEXT_WIDTH_FUDGE, because QGIS lays a string out slightly wider than Qt measures it.
    """
    device = QImage(1, 1, QImage.Format.Format_ARGB32)
    dots_per_metre = int(round(1000.0 / 25.4 * 96.0))  # 96 dpi, the resolution MM_PER_PX assumes
    device.setDotsPerMeterX(dots_per_metre)
    device.setDotsPerMeterY(dots_per_metre)
    metrics = QFontMetricsF(_font(size, bold), device)
    widest = max((metrics.horizontalAdvance(str(text)) for text in strings), default=0.0)
    return widest * MM_PER_PX * TEXT_WIDTH_FUDGE


def _floor_width(heading: str, cells: Sequence[str], available: float, size: float) -> float:
    """The width below which a column starts losing characters instead of lines.

    WrapText breaks on spaces, so the longest word in a column is as narrow as it can honestly
    get: squeeze past it and QGIS cuts the word off - "2026-09-15T22:2" instead of a timestamp,
    "Grondwaterkwetsb" instead of a map name. One greedy column (a URL is a single word of ninety
    characters) must still not swallow the sheet, hence the cap.
    """
    words = [word for cell in cells for word in str(cell).split()] or [""]
    longest = max(_text_width_mm([heading], size, bold=True), _text_width_mm(words, size))
    return min(longest, available * MAX_COLUMN_SHARE)


def column_widths(columns: Sequence[str], rows: Sequence[Sequence[str]], available: float,
                  size: float = TABLE_FONT_PT) -> List[float]:
    """A width in mm per column, together no wider than `available`.

    Left alone, QGIS gives every column the same share of the frame and CLIPS what does not fit -
    which is how the nine-column sonderingen table lost its last column and half of every
    contractor name. So each column asks for what its longest cell needs, never less than its own
    header, and what is left over is shared out in proportion to what each column still wants.
    When even the headers do not fit, everything shrinks proportionally and WrapText breaks the
    rest over two lines: narrow beats invisible.
    """
    if not columns:
        return []
    # A row with one cell too few is a bug in whoever built the table, but not one that may take
    # the whole report down here: the missing cell is simply empty.
    cells = [[row[index] if index < len(row) else "" for row in rows] or [""]
             for index in range(len(columns))]
    wanted = [max(_text_width_mm([column], size, bold=True), _text_width_mm(column_cells, size))
              for column, column_cells in zip(columns, cells)]
    if sum(wanted) <= available:
        return wanted
    floor = [_floor_width(column, column_cells, available, size)
             for column, column_cells in zip(columns, cells)]
    if sum(floor) >= available:
        return [width * available / sum(floor) for width in floor]
    extra = [want - base for want, base in zip(wanted, floor)]
    slack = available - sum(floor)
    if sum(extra) <= 0:
        return floor
    return [base + slack * (want / sum(extra)) for base, want in zip(floor, extra)]


def _fiche_note(links: Sequence[str]) -> str:
    """Where the permkeys in a fiche column can be looked up. The table prints the permkey alone -
    the whole URL is wider than the sheet - so the page says once what goes in front of it."""
    first = next((link for link in links if link), "")
    base = first.rsplit("/", 1)[0]
    return f"DOV-fiches: {base}/<nummer in de laatste kolom>" if base else ""


def _round_scale(scale: float) -> float:
    """The first scale on the ladder that is at least `scale`, or `scale` itself beyond it.

    Only ever zooms out. Past the last rung the map is already at a country-wide scale and one
    more doubling would say less than the odd number does.
    """
    return next((step for step in SCALE_STEPS if step >= scale - 0.5), scale)


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _joined(*parts: Optional[str]) -> str:
    """The parts a study actually knows, separated by dashes. A study without a company name must
    not print a footer that opens with a dangling separator."""
    return " - ".join(part for part in parts if part)


def _fit_box(item: QgsLayoutItemLabel, lines: Sequence[str], max_w: float,
             margin: float) -> Tuple[float, float]:
    """Width and height in mm for a plain-text box, measured by the label itself.

    `adjustSizeToText()` sizes a label to its text but never wraps it, so on its own it makes a box
    one row too short the moment a licence line is longer than the box - and that last row then
    hangs below the frame, right on the attribution. Measuring the lines one at a time answers how
    many rows the text really takes. It is the *label* that measures, not QFontMetricsF: QGIS makes
    the same string about seven per cent wider than Qt's metrics do (6 pt licence line: 55.4 mm
    against 51.9 mm), and that difference is exactly one wrapped row.

    The item is left holding the full text again.
    """
    widths: List[float] = []
    line_h = 2 * margin
    for line in lines:
        item.setText(line)
        item.adjustSizeToText()
        widths.append(item.rect().width())
        line_h = item.rect().height()
    item.setText("\n".join(lines))
    if not widths:
        return max_w, line_h
    width = min(max(widths), max_w)
    inner = max(width - 2 * margin, 1.0)
    rows = sum(max(1, int(math.ceil((one - 2 * margin) / inner))) for one in widths)
    return width, rows * (line_h - 2 * margin) + 2 * margin


def _natural_size(image_path, max_w: float, max_h: float) -> Tuple[float, float]:
    """The picture at its own pixel size (96 dpi logical pixels, as it was authored), capped.

    A strip of three centimetres stretched over a sheet is a blurred banner; its own size is what
    it was drawn for. The cap is not negotiable, though - a drawing wider than the paper is still
    fitted to it, aspect kept.
    """
    size = QImage(str(image_path)).size()
    if size.isEmpty():
        return max_w, max_h
    natural_w, natural_h = size.width() * MM_PER_PX, size.height() * MM_PER_PX
    if natural_w <= max_w and natural_h <= max_h:
        return natural_w, natural_h
    return _drawn_size(image_path, max_w, max_h)


def _drawn_size(image_path, max_w: float, max_h: float) -> Tuple[float, float]:
    """The size in mm at which a picture is really drawn inside max_w x max_h, aspect kept.

    That is what ResizeMode.Zoom does, but QGIS does it while painting and never tells the layout,
    so a caption placed under the *frame* would float a hand's width below a square figure.
    """
    size = QImage(str(image_path)).size()
    if size.isEmpty():
        return max_w, max_h
    scale = min(max_w / size.width(), max_h / size.height())
    return size.width() * scale, size.height() * scale


# --- legend images -------------------------------------------------------------------------------

def wms_legend_url(entry: MapEntry, options: str = "") -> str:
    """The GetLegendGraphic URL for one catalogue entry.

    STYLE travels with it: a legend drawn from the layer default while the map is drawn with a
    named style shows classes the map does not have (gxg is exactly that case). LEGEND_OPTIONS is
    a GeoServer extension that lays the classes out in columns; services that do not know it
    ignore it.
    """
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetLegendGraphic",
              "FORMAT": "image/png", "LAYER": entry.wms_layer, "STYLE": entry.wms_style}
    if options:
        params["LEGEND_OPTIONS"] = options
    return build_url(entry.wms_url, params)


def fetch_legend(entry: MapEntry, out_dir, client: HttpClient, log=None) -> Optional[Path]:
    """Fetch one legend to `out_dir/legendas/<map_id>.png`, or None with a WARNING."""
    url = wms_legend_url(entry, entry.legend_options)
    try:
        data = client.get(url, timeout=LEGEND_TIMEOUT_S, retries=LEGEND_RETRIES)
    except HttpError as exc:
        if log:
            log.warning(f"Legenda van {entry.id} niet opgehaald: {exc}")
        return None
    if not data:
        if log:
            log.warning(f"Legenda van {entry.id} kwam leeg terug")
        return None
    path = Path(out_dir) / LEGEND_DIR / f"{entry.id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def ramp_rect(image: QImage) -> Optional[Tuple[int, int, int, int]]:
    """The colour-ramp band inside a legend graphic: (x, y, width, height), or None.

    A ramp legend is drawn as one solid band against the LEFT edge, its title above it and its
    range printed beside it - that is what the DHMV service answers (102 x 68 px, a band of
    16 x 48, live 2026-09-17). So the rows that BEGIN with a run of one colour are the band, and
    the narrowest of those runs is its width.

    None for a legend shaped any other way, and then the report prints no colours at all: a strip
    whose colours are not the map's is worse than no strip.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, stride = rgba.width(), rgba.height(), rgba.bytesPerLine()
    buffer = rgba.constBits()
    buffer.setsize(height * stride)
    data = bytes(buffer)
    # Per row: where its solid run of one colour starts and how long it is. Not "column zero":
    # the GxG legend leaves a white pixel against the edge, and a search that insists on the very
    # first column finds nothing there and leaves that map without a legend.
    bands: List[Tuple[int, int]] = []
    for y in range(height):
        row = data[y * stride:y * stride + width * 4]
        start, run = 0, 0
        while start < width:
            pixel = row[start * 4:start * 4 + 4]
            if pixel[3] != 0 and pixel[:3] != WHITE_RGB:
                run = 1
                while start + run < width and row[(start + run) * 4:(start + run) * 4 + 4] == pixel:
                    run += 1
                break
            start += 1
        bands.append((start, run) if run >= RAMP_MIN_COLUMNS else (-1, 0))
    best_top, best_rows, best_start = 0, 0, -1
    top = None
    for y, (start, _run) in enumerate(bands + [(-1, 0)]):
        # One band: the rows have to open at the same column, or a stack of legend swatches would
        # read as one long bar.
        if start >= 0 and (top is None or bands[top][0] == start):
            top = y if top is None else top
            continue
        if top is not None and y - top > best_rows:
            best_top, best_rows, best_start = top, y - top, bands[top][0]
        top = y if start >= 0 else None
    if best_rows < RAMP_MIN_ROWS:
        return None
    return (best_start, best_top,
            min(run for _start, run in bands[best_top:best_top + best_rows]), best_rows)


def ramp_strip(legend_png, target, flip: bool = False) -> Optional[Path]:
    """The colour band of a legend graphic, cut out, laid on its side and saved as `target`.

    The band runs high-to-low downwards (the DTM is brown at 300 mTAW on top, green at -50 at the
    bottom) while a reader expects a horizontal scale to run low on the left. So it is turned a
    quarter clockwise, which puts the top of the band on the right. Turning and stretching change
    no colour - which is the whole point: what lands under the map is the service's own ramp.
    """
    image = QImage(str(legend_png))
    if image.isNull():
        return None
    rect = ramp_rect(image)
    if rect is None:
        return None
    # A quarter clockwise puts the TOP of the band on the right, which is where the height model
    # wants its maximum. A bar whose smallest value sits on top turns the other way, so that both
    # read small-left to large-right (`MapEntry.ramp_low_at_top`).
    band = image.copy(*rect).transformed(QTransform().rotate(-90 if flip else 90))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target if band.save(str(target)) else None


def fetch_ramp(entry: MapEntry, out_dir, client: HttpClient, log=None) -> Optional[Path]:
    """The colour strip of one map, cut from that map's own GetLegendGraphic.

    Report content, not a legend page: the height model's legend is a ramp over the whole of
    Flanders, which fills a sheet with a picture of three centimetres. Under the map, next to the
    three heights measured over the zone, the same picture says everything it has to say.
    """
    legend = fetch_legend(entry, out_dir, client, log)
    if legend is None:
        return None
    strip = ramp_strip(legend, Path(legend).with_name(f"{entry.id}{RAMP_SUFFIX}.png"),
                       flip=entry.ramp_low_at_top)
    if strip is None and log:
        log.warning(f"Kleurschaal van {entry.id}: geen herkenbare kleurbalk in de legenda")
    return strip


def prepare_legends(entries: Sequence[MapEntry], out_dir, client: HttpClient,
                    log=None, should_cancel: Optional[Callable[[], bool]] = None
                    ) -> Tuple[Dict[str, Path], List[MapEntry]]:
    """(map_id -> legend PNG, entries that came back without one).

    Fetched here rather than by the layout so that one failing service costs one legend page, not
    the report, and so the shell can run this phase with its own progress and cancellation. The
    fourteen legends are independent downloads from three services, so they go out in parallel;
    each still fails on its own, and the caller gets the misses back to record as failed sources.

    The client comes from the caller, always: one study has one disk cache and one cache mode
    (`http.study_client`), and a client built here would quietly be a second one that ignores the
    mode the user chose.
    """
    out_dir = Path(out_dir)
    wanted = [entry for entry in entries if entry.legend]
    images: Dict[str, Path] = {}

    def fetch(entry: MapEntry) -> None:
        path = fetch_legend(entry, out_dir, client, log)
        if path is not None:
            images[entry.id] = path

    parallel.load_each(wanted, fetch, "legenda", LEGEND_WORKERS, log, should_cancel)
    missing = [entry for entry in wanted if entry.id not in images]
    if log:
        log.info(f"Legendas opgehaald: {len(images)}/{len(wanted)}")
        if missing:
            log.warning(f"Geen legenda voor: {', '.join(entry.id for entry in missing)}")
    return images, missing


# --- the drawings behind the zone legend ----------------------------------------------------------

def zone_legend_targets(result: StudyResult) -> Dict[str, str]:
    """URL -> profile type, one entry per distinct drawing the quartair rows point at.

    The WFS answers with a row per map polygon, so a zone crossing the same profile type twice
    carries the same URL twice; fetching it twice would cost the service two requests for one file.
    """
    targets: Dict[str, str] = {}
    for fact in result.map_facts:
        if fact.map_id != QUARTAIR_ID:
            continue
        for row in fact.rows:
            url, code = str(row.get(QUARTAIR_IMAGE) or ""), str(row.get(QUARTAIR_CODE) or "")
            if url.startswith("http") and code and url not in targets:
                targets[url] = code
    return targets


def _drawing_bytes(client: HttpClient, url: str, code: str, log=None) -> bytes:
    """One profile-type drawing, or an HttpError saying what came back instead.

    The URL ends in "_png" but is a download link into a document portal, and that portal answers
    with its own web page - HTTP 200, text/html - often enough that one answer proves nothing. The
    bytes are therefore checked here. Een pagina wordt niet bewaard en niet klakkeloos herhaald:
    ze draagt de directe link naar het bestand in zich, en die wordt gevolgd.
    """
    # The first try may come straight from the disk cache - which is the point: a web page cached
    # by an earlier run is exactly what has to be noticed. Every try after it goes past the cache,
    # so a bad cached answer costs one request, not none and not two.
    for attempt in range(ZONE_LEGEND_TRIES):
        data = client.get(url, timeout=LEGEND_TIMEOUT_S, retries=LEGEND_RETRIES,
                          cache_mode="refresh" if attempt else None)
        if data.startswith(PNG_MAGIC):
            return data
        # Geen bestand, dus niets om te bewaren: anders dient de cache deze pagina bij elke
        # volgende run zonder netwerk weer op.
        client.forget(url)
        if log:
            log.warning(f"Profieltype {code}: antwoord {attempt + 1}/{ZONE_LEGEND_TRIES} is geen PNG "
                        f"({len(data)} bytes)")
        link = content_link(data, url)
        if link:
            if log:
                log.info(f"Profieltype {code}: de pagina wijst naar het bestand zelf, die link volgen")
            found = client.get(link, timeout=LEGEND_TIMEOUT_S, retries=LEGEND_RETRIES)
            if found.startswith(PNG_MAGIC):
                return found
            client.forget(link)
            if log:
                log.warning(f"Profieltype {code}: ook de link uit de pagina gaf geen PNG "
                            f"({len(found)} bytes)")
    raise HttpError(url, None, f"antwoord voor profieltype {code} is geen PNG")


def header_rows(image: QImage) -> int:
    """How many pixel rows of a profile-type drawing are its header.

    The answer is the first fully white row under the colour swatch: that band is the gap before
    "Eenheden op kaartblad <nn>". A drawing without such a band falls back to a fixed strip, which
    is still a strip rather than a whole sheet of units table.
    """
    flags = _blank_rows(image)
    for row in range(min(HEADER_MIN_ROWS, len(flags)), len(flags)):
        if flags[row]:
            return row
    return min(HEADER_FALLBACK_ROWS, image.height())


def _cropped(path, target: Path, part: Callable[[QImage], Tuple[int, int, int, int]],
             what: str, log=None) -> Optional[Path]:
    """One rectangle out of a profile-type drawing, saved as `target`.

    The two crops below differ in exactly two things - which rectangle and what the failure is
    called - so the reading, the null check and the save live here. `part` gets the image and
    answers (x, y, width, height), because both rectangles need `header_rows` on the loaded image.
    """
    image = QImage(str(path))
    if image.isNull():
        if log:
            log.warning(f"Profieltypetekening niet leesbaar: {path}")
        return None
    if not image.copy(*part(image)).save(str(target)):
        if log:
            log.warning(f"{what} niet weggeschreven: {target}")
        return None
    return target


def crop_sheet_units(path, sheet: str, log=None) -> Optional[Path]:
    """The same drawing WITHOUT its profile-type header, as `quartair_kaartblad_<nn>.png`.

    The units table underneath is valid for every profile type of the sheet. Left on, the header of
    whichever type happened to be fetched first sits above it and the table reads as that one
    type's. The source line under the table is part of the drawing and stays.
    """
    target = Path(path).with_name(f"{ZONE_LEGEND_PREFIX}{ZONE_LEGEND_SHEET}{sheet}.png")
    return _cropped(path, target,
                    lambda image: (0, header_rows(image), image.width(),
                                   image.height() - header_rows(image)),
                    "Eenhedentabel", log)


def crop_profile_header(path, log=None) -> Optional[Path]:
    """Cut the header strip off a profile-type drawing and save it beside it as `<name>_kop.png`.

    What is left out is the units table of the map sheet, which is the same drawing for every
    profile type of that sheet: printed once per type it would be the same page three times over.
    """
    target = Path(path).with_name(Path(path).stem + HEADER_SUFFIX + ".png")
    return _cropped(path, target, lambda image: (0, 0, image.width(), header_rows(image)),
                    "Kopstrook", log)


def _log_rows_without_a_drawing(result: StudyResult, targets: Dict[str, str], log) -> None:
    """Say which profile types carry no usable drawing URL - what was NOT found is a finding too.

    A row with a code but without a legend link leaves the legend page with a line and no picture,
    and without this line nobody could tell that from a download that failed.
    """
    if log is None:
        return
    known = set(targets.values())
    missing = sorted({str(row.get(QUARTAIR_CODE)) for fact in result.map_facts
                      if fact.map_id == QUARTAIR_ID for row in fact.rows
                      if row.get(QUARTAIR_CODE) and str(row.get(QUARTAIR_CODE)) not in known})
    if missing:
        log.warning(f"Profieltype zonder bruikbare tekening-URL: {', '.join(missing)}")


def prepare_zone_legend_images(result: StudyResult, out_dir, client: HttpClient, log=None,
                               should_cancel: Optional[Callable[[], bool]] = None
                               ) -> Dict[str, Path]:
    """The DOV drawings behind the quartair zone legend, by the key `report_content` looks them up
    with: `profieltype:<code>` for the header strip of one type, `kaartblad:<nn>` for the units
    table of a whole map sheet.

    That drawing IS the legend of the quartair map - its GetLegendGraphic is a 20 x 20 stamp
    without a class name - so the shell fetches it here and hands it to `build_report`. The core
    fetches nothing itself.

    One request per distinct profile type; the units table underneath is identical for every type
    of the same sheet, so it is kept once. What does not come back has no entry, and the report
    then leaves that page out rather than promising a drawing that is not there. The URLs end in
    "_png" but are download links that can answer an error page with HTTP 200, so the bytes are
    checked before they are saved as an image.
    """
    targets = zone_legend_targets(result)
    _log_rows_without_a_drawing(result, targets, log)
    drawings: Dict[str, Path] = {}
    out_dir = Path(out_dir)

    def fetch(item: Tuple[str, str]) -> None:
        url, code = item
        data = _drawing_bytes(client, url, code, log)
        path = out_dir / LEGEND_DIR / f"{ZONE_LEGEND_PREFIX}{code}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        drawings[code] = path

    parallel.load_each(list(targets.items()), fetch, "profieltypelegenda", LEGEND_WORKERS, log,
                       should_cancel)
    # The threads only fetch; the cutting and the one-per-sheet choice happen here, in the order
    # the WFS rows first mentioned each profile type, so two runs of the same study keep the same
    # sheet drawing.
    images: Dict[str, Path] = {}
    for code in targets.values():
        drawing = drawings.get(code)
        if drawing is None:
            continue
        header = crop_profile_header(drawing, log)
        if header is None:
            continue
        images[profile_image_key(code)] = header
        sheet = quartair_sheet(code)
        key = sheet_image_key(sheet)
        if key not in images:
            units = crop_sheet_units(drawing, sheet, log)
            if units is not None:
                images[key] = units
    if log and targets:
        log.info(f"Profieltypetekeningen opgehaald: {len(drawings)}/{len(targets)}; "
                 f"{len(images)} bladen in het rapport")
    return images


def overlay_boxes(result: StudyResult) -> Dict[str, List[BBox]]:
    """The boxes a map page widens for, read from the study itself: 'investigations' (every
    point that was found, and the search area around the zone), 'section' (the section line).

    From the study and not from the overlay layers, on purpose. The map images are planned
    where no layer exists - on the worker thread, before the shell touches QGIS - and the page
    that draws them later must arrive at the same box to the metre, or it looks its image up
    under a key that is not there. Two computations from two sources can never promise that; one
    function over one result can. The search area is the zone's box grown by the radius, which
    holds the buffered polygon whole (a GEOS buffer stays inside it by construction).

    Keys are always present; a study without a section line has an empty list under 'section',
    and a page that asks for it widens for nothing.
    """
    zone = result.zone
    investigations: List[BBox] = [geometry.expand_bbox(geometry.bbox(zone.ring), zone.radius_m)]
    points = [(item.x, item.y) for item in (*result.cpts, *result.boreholes, *result.gw_filters)]
    if points:
        investigations.append(geometry.bbox(points))
    section: List[BBox] = [geometry.bbox(zone.section_line)] if zone.section_line else []
    return {"investigations": investigations, "section": section}


def _box_of(item) -> Optional[BBox]:
    """A plain (minx, miny, maxx, maxy) from a layer or from a box that already is one; None for
    a layer without features, which has nothing to widen for."""
    if isinstance(item, QgsMapLayer):
        extent = item.extent()
        if extent.isEmpty():
            return None
        return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())
    minx, miny, maxx, maxy = item
    return (float(minx), float(miny), float(maxx), float(maxy))


def map_extent(zone_ring: Sequence, scale: int, extent_factor: float,
               extra: Sequence = ()) -> QgsRectangle:
    """The extent the map item gets: wide enough for the target scale, for `extent_factor`
    zones, and for everything the page asked to draw on top.

    `MapPage.scale` is a target, not a promise. Drawing a 100 m zone at 1:25000 is fine - the
    zone is simply small on the sheet - but drawing a 2 km zone at 1:2500 would crop it. The
    same holds for the overlays: a page that shows the ground investigations while cutting the
    search radius in half tells the reader nothing was looked for out there.

    Widening for the overlays is the one case where the scale is nobody's choice: it falls out
    of how far the search radius happens to reach, and the info box then reads "1:6 104". So
    that width goes back through the 1-2-5 ladder and the extent is rebuilt from the rounded
    scale. The catalogue scale and the zone factor are deliberate framings and stay as they
    are - and since the ladder only rounds up, nothing that had to fit stops fitting.

    `extra` holds what to widen for: plain boxes (see `overlay_boxes`) or layers, read the same
    way - the planner on the worker thread has boxes, the older tests hand in layers.
    """
    minx, miny, maxx, maxy = geometry.bbox(zone_ring)
    zone_w, zone_h = maxx - minx, maxy - miny
    for item in extra:
        box = _box_of(item)
        if box is None:
            continue
        minx, miny = min(minx, box[0]), min(miny, box[1])
        maxx, maxy = max(maxx, box[2]), max(maxy, box[3])
    ratio = MAP_H / MAP_W
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    width_at_scale = MAP_W / 1000.0 * scale  # metres across the paper width at 1:scale
    width_for_zone = max(zone_w, zone_h / ratio) * max(extent_factor, 1.0)
    width_for_overlays = max(maxx - minx, (maxy - miny) / ratio)
    width = max(width_at_scale, width_for_zone)
    if width_for_overlays > width:
        width = MAP_W / 1000.0 * _round_scale(width_for_overlays / (MAP_W / 1000.0))
    height = width * ratio
    return QgsRectangle(cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)


def map_height(needed: float) -> float:
    """The height the map frame keeps when `needed` millimetres have to fit under it.

    Nothing shrinks for the first four centimetres: that band was white paper already. Beyond it
    the frame gives way millimetre for millimetre, down to MAP_MIN_H - what a legend needs past
    that point runs on to the next sheet, because half a page of map is the least a reader can
    still read.
    """
    if needed <= 0.0:
        return MAP_H
    return max(MAP_MIN_H, min(MAP_H, CONTENT_H - UNDER_MAP_GAP - needed))


def crop_extent(extent: QgsRectangle, height_mm: float) -> QgsRectangle:
    """The same box at the same WIDTH, cropped to the paper height the frame really gets.

    The width is what sets the scale and what the fetched image was planned on (`plan_map_images`
    always computes the full-height extent), so it is never touched: a shorter frame shows less
    ground above and below the very same picture. Narrowing instead would change the scale printed
    in the info box and send the page looking for an image nobody fetched.
    """
    if height_mm >= MAP_H:
        return extent
    height = extent.width() * height_mm / MAP_W
    centre = extent.center()
    return QgsRectangle(extent.xMinimum(), centre.y() - height / 2.0,
                        extent.xMaximum(), centre.y() + height / 2.0)


# --- does this service draw anything here? ---------------------------------------------------------

@dataclass(frozen=True)
class MapRequest:
    """One map image to fetch: which map, over which box, at which pixel size."""
    key: str
    map_id: str
    extent: QgsRectangle
    width: int
    height: int


def wms_map_url(entry: MapEntry, extent: QgsRectangle, width: int, height: int) -> str:
    """A GetMap for one box at one pixel size.

    WMS 1.1.1 on purpose: 1.3.0 orders the BBOX by the axis order of the CRS, and getting that
    wrong for EPSG:31370 yields a picture of somewhere else - which would read as an empty map.
    1.1.1 is always minx,miny,maxx,maxy, and every service in the catalogue answers it (checked
    live 2026-09-16 on geopunt, DOV, waterinfo and NGI).
    """
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": entry.wms_layer,
              "STYLES": entry.wms_style, "SRS": CRS_AUTHID, "FORMAT": entry.image_format,
              "TRANSPARENT": "TRUE", "WIDTH": width, "HEIGHT": height,
              "BBOX": f"{extent.xMinimum():.0f},{extent.yMinimum():.0f},"
                      f"{extent.xMaximum():.0f},{extent.yMaximum():.0f}"}
    return build_url(entry.wms_url, params)


def map_image_key(map_id: str, extent: QgsRectangle) -> str:
    """What makes two map pages share one image: the same map over the same box.

    The GRB base map carries four pages of this report at three different framings; keying on the
    box means the two that look alike are fetched once.
    """
    return (f"{map_id}:{extent.xMinimum():.0f}:{extent.yMinimum():.0f}:"
            f"{extent.xMaximum():.0f}:{extent.yMaximum():.0f}")


def _image_name(key: str) -> str:
    """The file-name part that tells two framings of one map apart, stable across runs.

    `hash()` on a str is salted per process (PYTHONHASHSEED), so a headless run reusing the same
    `--out` left a new set of orphans behind every time and two framings could collide on one
    name. A digest of the key does neither.
    """
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _image_pixels() -> Tuple[int, int]:
    """The pixel size a map item is printed at, capped at what a service hands out in one go."""
    width = int(round(MAP_W / 25.4 * MAP_IMAGE_DPI))
    height = int(round(MAP_H / 25.4 * MAP_IMAGE_DPI))
    largest = max(width, height)
    if largest > MAP_IMAGE_MAX_PX:
        width = int(width * MAP_IMAGE_MAX_PX / largest)
        height = int(height * MAP_IMAGE_MAX_PX / largest)
    return width, height


def page_boxes(page: MapPage, boxes: Dict[str, Sequence]) -> List:
    """What one map page widens for, out of `boxes` keyed 'investigations' / 'section': the same
    pick for the planner and for the page, so the two cannot drift apart."""
    extra: List = []
    if page.show_investigations:
        extra += list(boxes.get("investigations", []))
    if page.show_section_line:
        extra += list(boxes.get("section", []))
    return extra


def plan_map_images(report: Report, zone_ring: Sequence,
                    boxes: Dict[str, Sequence]) -> List[MapRequest]:
    """One request per distinct (map, box) in the report, in the order the pages need them.

    The box is computed here exactly as the page will compute it, overlays included - a page that
    widens for the search radius shows a wider picture and must ask for that picture. `boxes` is
    what `overlay_boxes` gives for the study; no layer is needed, so this runs on a worker thread.
    """
    requests: List[MapRequest] = []
    seen = set()
    for chapter in report.chapters:
        for page in chapter.pages:
            if not isinstance(page, MapPage):
                continue
            extent = map_extent(zone_ring, page.scale, page.extent_factor, page_boxes(page, boxes))
            key = map_image_key(page.map_id, extent)
            if key in seen:
                continue
            seen.add(key)
            width, height = _image_pixels()
            requests.append(MapRequest(key, page.map_id, extent, width, height))
    return requests


def _write_world_file(path: Path, request: MapRequest) -> None:
    """The six lines that put a PNG on the map: pixel size, rotation, and the centre of the
    top-left pixel (not its corner - that half pixel is the classic world-file mistake)."""
    x_size = request.extent.width() / request.width
    y_size = request.extent.height() / request.height
    path.write_text("\n".join((f"{x_size:.10f}", "0.0", "0.0", f"{-y_size:.10f}",
                                f"{request.extent.xMinimum() + x_size / 2:.4f}",
                                f"{request.extent.yMaximum() - y_size / 2:.4f}")) + "\n",
                    encoding="utf-8")


def _load_tile(data: bytes) -> Optional[QImage]:
    """The bytes of a GetMap as an image, or None when the service sent something else."""
    image = QImage()
    return image if data and image.loadFromData(data) else None


def _over_backdrop(theme: QImage, backdrop: QImage, opacity: float) -> QImage:
    """The theme painted over the base map, at the opacity the catalogue gives the theme.

    Both come from the same box at the same pixel size, so they line up by construction - the
    page draws ONE picture and nothing has to be registered afterwards.
    """
    canvas = backdrop.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(canvas)
    painter.setOpacity(opacity)
    painter.drawImage(0, 0, theme)
    painter.end()
    return canvas


def _backdrop_for(request: MapRequest, client: HttpClient, log=None) -> Tuple[Optional[QImage], str]:
    """The base map under one theme: (image, why not). A backdrop that does not come back costs
    the theme its background, never its page."""
    base = catalogue.by_id(BASE_MAP_ID)
    url = wms_map_url(base, request.extent, request.width, request.height)
    try:
        image = _load_tile(client.get(url, timeout=MAP_IMAGE_TIMEOUT_S, retries=MAP_IMAGE_RETRIES))
    except HttpError as exc:
        image, reason = None, str(exc)
    else:
        reason = "" if image is not None else "antwoord van de basiskaart is geen afbeelding"
    if image is None and log:
        log.warning(f"Ondergrond voor {request.map_id} niet opgehaald: {reason}")
    return image, reason


def prepare_map_images(requests: Sequence[MapRequest], out_dir, client: HttpClient, log=None,
                       should_cancel: Optional[Callable[[], bool]] = None
                       ) -> Tuple[Dict[str, Path], Set[str], Dict[str, str]]:
    """({key -> PNG}, keys whose service drew nothing here), fetched in parallel.

    This is the phase that used to be spread over ninety sheets of rendering: the WMS provider
    fetches its tiles while a page draws, one page after another, and the whole report waits on
    the network. Here every page's background is one GetMap, they go out together, and the layout
    then draws local files.

    Emptiness comes for free with the picture, so the separate coverage probe is gone. It is only
    trusted for maps WITHOUT facts: the watertoets answers Gent with a fully transparent tile
    because no flood zone lies there - data, not a hole in the mosaic - and its own table says so.

    Emptiness is reported per REQUEST, not per map: one map carries several framings (the GRB base
    map three), and a mosaic that has no sheet for the wide frame may well cover the narrow one.
    Keyed per map, one empty tile would print "geen dekking" on every other sheet of that map.

    The third answer is the backdrops: map id -> "" when the base map went under that theme, or
    the reason it did not. Only for `MapEntry.backdrop` maps, and only ever as an extra request -
    a theme whose backdrop failed is still drawn, on white paper, and says so in the sources.
    """
    out_dir = Path(out_dir)
    images: Dict[str, Path] = {}
    empty: Set[str] = set()
    backdrops: Dict[str, str] = {}

    def fetch(request: MapRequest) -> None:
        entry = catalogue.by_id(request.map_id)
        url = wms_map_url(entry, request.extent, request.width, request.height)
        data = client.get(url, timeout=MAP_IMAGE_TIMEOUT_S, retries=MAP_IMAGE_RETRIES)
        image = _load_tile(data)
        if image is None:
            raise HttpError(url, None, f"antwoord voor {request.map_id} is geen afbeelding "
                                       f"({len(data)} bytes)")
        # Asked of the THEME, before anything is painted under it: a backdrop would answer the
        # coverage question with the base map's own ink. Asked of EVERY map, not only of the ones
        # without facts - a themed map that draws nothing here is the sheet that showed a base map,
        # an empty legend and a guide to a table that was not there. What such a tile costs is
        # decided where the legend is known (`pipeline._pages_without_an_image`), not here.
        blank = _is_empty(image)
        path = out_dir / DATA_DIR / MAP_IMAGE_DIR / f"{request.map_id}_{_image_name(request.key)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry.backdrop:
            under, reason = _backdrop_for(request, client, log)
            # Keyed per MAP while eight threads write it, so two framings of one map race for the
            # same slot. Both framings ask the same base map, so the two answers are the same
            # sentence and the winner does not matter; CPython's dict assignment is atomic, so
            # nothing is lost either. Keep the LOSING one only when it explains a failure that the
            # winner does not, so a reason never silently becomes "fine".
            if reason or request.map_id not in backdrops:
                backdrops[request.map_id] = reason
            if under is not None:
                data = None
                if not _over_backdrop(image, under, entry.opacity).save(str(path)):
                    raise HttpError(url, None, f"beeld van {request.map_id} niet weggeschreven")
        if data is not None:
            path.write_bytes(data)
        _write_world_file(path.with_suffix(".pgw"), request)
        images[request.key] = path
        if blank:
            empty.add(request.key)

    parallel.load_each(list(requests), fetch, "kaartbeeld", MAP_IMAGE_WORKERS, log, should_cancel)
    if log:
        blank = sorted({request.map_id for request in requests if request.key in empty})
        log.info(f"Kaartbeelden opgehaald: {len(images)}/{len(requests)}"
                 + (f"; geen kaartbeeld op deze locatie voor: {', '.join(blank)}" if blank else ""))
        missing = [request.map_id for request in requests if request.key not in images]
        if missing:
            log.warning(f"Geen kaartbeeld voor: {', '.join(sorted(set(missing)))}")
        under = sorted(map_id for map_id, reason in backdrops.items() if not reason)
        if under:
            log.info(f"Basiskaart als ondergrond onder: {', '.join(under)}")
    return images, empty, backdrops


def _fits_portrait(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> bool:
    """Whether these columns can be read on a portrait sheet.

    Two questions, in order. Do they simply fit? Then portrait, whatever their number - that is
    the eight narrow columns of the peilput table, 63 mm in a 161 mm budget, which used to earn a
    landscape sheet of their own purely by being eight. Do they not fit? Then how hard would the
    squeeze be: a column can be narrowed to its longest word and no further, so the sum of those
    words against the budget says whether wrapping still leaves a readable table or turns every
    cell into a stack of fragments.

    The table's own furniture - a cell margin either side of every column and a grid line between
    and outside them - comes off the budget first, the same way `_new_table` computes it.
    """
    count = len(columns)
    budget = CONTENT_W - 2 * TABLE_CELL_MARGIN * count - (count + 1) * TABLE_GRID_WIDTH
    cells = [[row[index] if index < len(row) else "" for row in rows] or [""]
             for index in range(count)]
    wanted = sum(max(_text_width_mm([column], TABLE_FONT_PT, bold=True),
                     _text_width_mm(column_cells, TABLE_FONT_PT))
                 for column, column_cells in zip(columns, cells))
    if wanted <= budget:
        return True
    floor = sum(_floor_width(column, column_cells, UNBOUNDED_WIDTH, TABLE_FONT_PT)
                for column, column_cells in zip(columns, cells))
    return floor <= budget * TABLE_MAX_SQUEEZE


def _is_empty(image: QImage) -> bool:
    """True when every pixel is the same, or every pixel is fully transparent.

    That is what a mosaic without a sheet for this place answers: HTTP 200 and nothing drawn.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    buffer = rgba.constBits()
    buffer.setsize(rgba.height() * rgba.bytesPerLine())
    data, stride, row_bytes = bytes(buffer), rgba.bytesPerLine(), rgba.width() * 4
    pixels = b"".join(data[y * stride:y * stride + row_bytes] for y in range(rgba.height()))
    if not pixels:
        return True
    first = pixels[:4]
    return (all(pixels[i:i + 4] == first for i in range(0, len(pixels), 4))
            or all(pixels[i + 3] == 0 for i in range(0, len(pixels), 4)))


def _blank_rows(image: QImage) -> List[bool]:
    """One flag per pixel row: True where the row is entirely white or entirely transparent.

    Those rows are the gaps between legend entries, and they are where a page break belongs. The
    whole mask is built in one pass over the raw buffer: a legend is a few thousand rows and
    reading it pixel by pixel through `pixelColor` takes seconds.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, stride = rgba.width(), rgba.height(), rgba.bytesPerLine()
    buffer = rgba.constBits()
    buffer.setsize(height * stride)
    data = bytes(buffer)
    white, clear = b"\xff" * (width * 4), b"\x00" * (width * 4)
    flags: List[bool] = []
    for y in range(height):
        row = data[y * stride:y * stride + width * 4]
        # The two fast paths cover a solid white row and a fully transparent one, which is what a
        # gap in a GetLegendGraphic image actually is; the loop is only for mixed rows.
        flags.append(row == white or row == clear
                     or all(row[i + 3] == 0 or row[i:i + 3] == b"\xff\xff\xff"
                            for i in range(0, len(row), 4)))
    return flags


def _cut_row(flags: Sequence[bool], top: int, nominal: int) -> int:
    """Where to break a strip that would nominally end at `nominal`: the nearest blank row above
    it, so the break lands in the gap between two legend entries instead of through one.

    Falls back to the nominal break when the slice holds no blank row at all - a legend without
    any gap has nothing to protect, and a break that never happens fits on no page.
    """
    for row in range(nominal, top, -1):
        if flags[row - 1]:
            return row
    return nominal


def _legend_strips(image_path, map_id: str) -> List[Tuple[Path, float, float]]:
    """(path, width_mm, height_mm) per page-sized slice of a legend image.

    A DOV legend is a tall narrow strip. Squeezed into one frame it becomes a thumbnail nobody can
    read, so anything taller than a sheet at its natural size is cut into sheet-high pieces.
    """
    image = QImage(str(image_path))
    if image.isNull():
        return []
    # The scale follows from the WIDTH alone (capped at natural size). Fitting the height too -
    # what ResizeMode.Zoom would do on its own - is exactly the failure mode here: it shrinks a
    # legend of three hundred classes until it fits, and nobody can read it.
    mm_per_px = min(CONTENT_W / image.width(), MM_PER_PX)
    width_mm = image.width() * mm_per_px
    height_mm = image.height() * mm_per_px
    if height_mm <= CONTENT_H + 0.01:
        return [(Path(image_path), width_mm, height_mm)]
    rows = max(1, int(CONTENT_H / mm_per_px))
    flags = _blank_rows(image)
    strips: List[Tuple[Path, float, float]] = []
    top, number = 0, 1
    while top < image.height():
        bottom = min(top + rows, image.height())
        if bottom < image.height():  # the last slice ends where the legend does
            bottom = _cut_row(flags, top, bottom)
        strip = Path(image_path).with_name(f"{map_id}_{number}.png")
        image.copy(0, top, image.width(), bottom - top).save(str(strip))
        strips.append((strip, width_mm, (bottom - top) * mm_per_px))
        top, number = bottom, number + 1
    return strips


class Slot(NamedTuple):
    """Where one piece of content landed: its sheet, the y it starts at, and whether it shares
    that sheet with something above it - a note that stands in the header band on a sheet of its
    own has to move under the title when it does not."""
    page: int
    top: float
    packed: bool


class UnderMap(NamedTuple):
    """What goes below a map frame: how tall it is, and how to draw it once the frame is placed.

    Measured first and drawn later, because the height of the frame follows from the measurement
    and the position of the block follows from the frame. `minimum` is what the FIRST piece needs:
    a legend that does not fit runs on to the next sheet, but a reading guide that does not even
    start under a readable map takes the whole block with it - half a paragraph under a map and
    the other half overleaf reads worse than a block that begins on a sheet of its own.
    """
    height: float
    draw: Callable[[int, float], None]
    minimum: float = 0.0


class LayoutBuilder:
    """One report -> one layout. Build it once; `build()` is not idempotent."""

    def __init__(self, project: QgsProject, report: Report,
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = False, legend_images: Optional[Dict[str, Path]] = None,
                 log=None, should_cancel: Optional[Callable[[], bool]] = None,
                 no_coverage: Optional[Set[str]] = None,
                 map_images: Optional[Dict[str, QgsMapLayer]] = None,
                 overlay_boxes: Optional[Dict[str, List[BBox]]] = None,
                 name: Optional[str] = None, compact: bool = False):
        """overlays: keys 'zone', 'investigations', 'section' -> the memory layers a page may ask
        to draw on top of its map image; name: what the layout is called in the layout manager
        (`layout_name`), the bare plugin name when left empty;
        legend_images: map_id -> legend PNG, as `prepare_legends` returns them; no_coverage: the
        `map_image_key`s whose service drew nothing there - per framing, because one map can carry
        several and a mosaic can cover the narrow one and not the wide one; map_images: the same
        key -> the raster layer of the image fetched for it, which a map page draws instead of the
        live WMS layer; overlay_boxes: what a page widens for, as `overlay_boxes` gives it - the same
        boxes the images were planned on. Without them the page widens for its layers' extents,
        which is fine when nobody planned an image for it (the direct tests);
        compact: put as many pieces of content on one sheet as fit, instead of at most two."""
        self.project, self.report = project, report
        self.overlays = overlays
        self.overlay_boxes = overlay_boxes
        self.out_dir, self.zone_ring, self.meta = Path(out_dir), list(zone_ring), meta
        self.legends = legends
        self.compact = compact
        self.legend_images = dict(legend_images or {})
        self.no_coverage = set(no_coverage or ())
        self.map_images = dict(map_images or {})
        self.log = log
        self.should_cancel = should_cancel or (lambda: False)
        self.layout = QgsPrintLayout(project)
        self.layout.initializeDefaults()  # this already gives page 0, in A4 landscape
        self.layout.setName(name or LAYOUT_NAME)
        QgsExpressionContextUtils.setLayoutVariable(self.layout, LEGEND_VARIABLE, 1 if legends else 0)
        self._first_page_used = False
        # The sheet being filled: which one, how far down it is used, how many pieces stand on it,
        # in which orientation and under which chapter heading. A fresh sheet resets all five
        # (`_start`).
        self._sheet = -1
        self._cursor = CONTENT_TOP
        self._sheet_metrics = _METRICS[PORTRAIT]
        self._sheet_chapter: Optional[int] = None

    # --- which sheet does this piece of content go on? --------------------------------------------

    def _room_left(self, chapter: Chapter, metrics: PageMetrics) -> float:
        """How much height a new piece could still take on the sheet being filled, its heading and
        the gap already subtracted; 0.0 when nothing can join that sheet at all."""
        same = chapter.number == self._sheet_chapter
        if (self._sheet < 0 or not (same or self.compact)
                or metrics.orientation != self._sheet_metrics.orientation):
            return 0.0
        room = CONTENT_TOP + self._sheet_metrics.content_h - self._cursor
        heading = PACKED_TITLE_H + (0.0 if same else PACKED_CHAPTER_H)
        return max(0.0, room - PACK_GAP - heading)

    def _start(self, chapter: Chapter, title: str, content_h: float,
               metrics: PageMetrics = _METRICS[PORTRAIT], packable: bool = True) -> Slot:
        """Room for one piece of content, with its heading written.

        On the sheet being filled for as long as things fit on it - a sheet holding one short
        table is a sheet of white paper - and on a fresh one otherwise. A sheet has one
        orientation, so a portrait piece never joins a landscape one, and one chapter heading, so
        a piece from the next chapter starts its own sheet; `compact` lets it share and repeats
        the new heading, small, where the chapter changes. A map page never shares at all, and
        fills its sheet so that nothing lands behind it either.
        """
        room = CONTENT_TOP + self._sheet_metrics.content_h - self._cursor
        same = chapter.number == self._sheet_chapter
        heading = PACKED_TITLE_H + (0.0 if same else PACKED_CHAPTER_H)
        packed = (packable and self._sheet >= 0
                  and metrics.orientation == self._sheet_metrics.orientation
                  and (same or self.compact)
                  and PACK_GAP + heading + content_h <= room)
        if packed:
            index, top = self._sheet, self._cursor + PACK_GAP
            if not same:
                # The heading belongs to what stands under it; a table of chapter 4 under
                # "3. Geologie en bodem" is read as chapter 3.
                self.label(f"{chapter.number}. {chapter.title}", MARGIN, top, metrics.content_w,
                           PACKED_CHAPTER_H, index, size=9, bold=True)
                top += PACKED_CHAPTER_H
                self._sheet_chapter = chapter.number
            self.label(title, MARGIN, top, metrics.content_w, PACKED_TITLE_H, index, size=10,
                       bold=True)
            top += PACKED_TITLE_H
        else:
            index = self.new_page(metrics.orientation)
            self.header(chapter, title, index, metrics)
            top = CONTENT_TOP
            self._sheet, self._sheet_metrics = index, metrics
            self._sheet_chapter = chapter.number
        self._cursor = top + content_h
        return Slot(index, top, packed)

    def _seal(self, index: int, metrics: PageMetrics = _METRICS[PORTRAIT]) -> None:
        """This sheet is full: whatever comes next starts a new one."""
        self._sheet, self._sheet_metrics = index, metrics
        self._cursor = CONTENT_TOP + metrics.content_h

    # --- page furniture ---------------------------------------------------------------------------

    def new_page(self, orientation=PORTRAIT) -> int:
        """Append a page and return its index - read from the collection, never counted here.

        A table that runs on appends pages of its own, so a counter of ours drifts behind and the
        next report page lands on top of the last table page.

        Portrait unless the content says otherwise: a nine-column table or a figure wider than it
        is tall gets a landscape sheet, because squeezed into 180 mm the one loses its last column
        and the other becomes a strip across the top of an empty page.
        """
        self._raise_if_cancelled()
        collection = self.layout.pageCollection()
        if self._first_page_used:
            page = QgsLayoutItemPage(self.layout)
            page.setPageSize(PAGE_SIZE, orientation)
            collection.addPage(page)
        else:
            # initializeDefaults() laid page 0 down in A4 *landscape*. The report is portrait from
            # cover to cover, and on a landscape first page everything below 210 mm - the table of
            # contents, the disclaimer - simply falls off the paper.
            collection.page(0).setPageSize(PAGE_SIZE, orientation)
            self._first_page_used = True
        return collection.pageCount() - 1

    def _raise_if_cancelled(self) -> None:
        """Between two pages is where a build can stop. Ninety-five sheets take half a minute to
        lay out, and a user who pressed cancel should not wait for the other half."""
        if self.should_cancel():
            raise parallel.Cancelled("afgebroken door de gebruiker")

    def label(self, text: str, x: float, y: float, w: float, h: float, page: int, size: float = 9,
              html: bool = False, frame: bool = False, bold: bool = False) -> QgsLayoutItemLabel:
        item = QgsLayoutItemLabel(self.layout)
        if html:
            item.setMode(QgsLayoutItemLabel.Mode.ModeHtml)
        item.setText(text)
        item.setTextFormat(_text_format(size, bold))
        item.setFrameEnabled(frame)
        self.layout.addLayoutItem(item)
        item.attemptMove(point_mm(x, y), page=page)
        item.attemptResize(size_mm(w, h))
        return item

    def info_box(self, lines: Sequence[str], y: float, page: int, size: float) -> QgsLayoutItemLabel:
        """A box on top of the map: opaque, shrunk to its text and pinned to the right margin.

        Plain text, not HTML, on purpose. `adjustSizeToText()` measures the label's raw string with
        the text renderer, so on an HTML label it would size the box to the width of the markup and
        push it clean off the sheet. Growing leftwards from the right margin keeps a long licence
        line on the paper whatever it says.
        """
        shown = [part for part in lines if part]
        item = QgsLayoutItemLabel(self.layout)
        item.setText("\n".join(shown))
        item.setTextFormat(_text_format(size))
        item.setMargin(INFO_MARGIN_MM)
        item.setFrameEnabled(True)
        item.setBackgroundEnabled(True)
        item.setBackgroundColor(BOX_BACKGROUND)
        self.layout.addLayoutItem(item)
        item.attemptMove(point_mm(CONTENT_RIGHT - INFO_W, y), page=page)
        item.attemptResize(size_mm(INFO_W, INFO_H))
        width, height = _fit_box(item, shown, INFO_W, INFO_MARGIN_MM)
        item.attemptResize(size_mm(width, height))
        # Pin the right edge to the margin only now: adjustSizeToText shifts a box by its own
        # rules (a reference point of UpperRight still moves it half a step), so the one reliable
        # way to keep a long licence line on the sheet is to place it once the width is settled.
        item.attemptMove(point_mm(CONTENT_RIGHT - width, y), page=page)
        return item

    def header(self, chapter: Chapter, title: str, page: int,
               metrics: PageMetrics = _METRICS[PORTRAIT]) -> None:
        self.label(f"{chapter.number}. {chapter.title}", MARGIN, 10, metrics.content_w, 8, page,
                   size=13, bold=True)
        self.label(title, MARGIN, 18, metrics.content_w, 7, page, size=10)

    def footer(self, page: int, metrics: PageMetrics = _METRICS[PORTRAIT]) -> None:
        """The footer of one sheet; its page number is filled in by `_number_footers` at the end.

        Not `@layout_page / @layout_numpages`: the export hands the layout to QGIS a few sheets at
        a time, and inside such a run those variables count the run ("pagina 1 / 1"). The number
        belongs to the sheet, so it is written as text once every sheet exists.
        """
        item = self.label(self._footer_text(0, 0), MARGIN, metrics.footer_y, metrics.content_w, 6,
                          page, size=7)
        item.setId(FOOTER_ID)

    def _footer_every_sheet(self) -> None:
        """One footer per SHEET, written once every sheet exists.

        Per sheet and not per report page: two short pieces of content can share a sheet, and two
        footers on one sheet would read as two page numbers on one piece of paper. The orientation
        comes from the sheet itself - a landscape table sheet puts its footer higher up.
        """
        collection = self.layout.pageCollection()
        for index in range(collection.pageCount()):
            size = collection.page(index).pageSize()
            self.footer(index, _page_metrics(LANDSCAPE if size.width() > size.height()
                                             else PORTRAIT))

    def _footer_text(self, number: int, total: int) -> str:
        return _joined(self.meta.get("company"), self.meta.get("project"), f"pagina {number} / {total}")

    def _number_footers(self) -> None:
        """Write "pagina n / N" into every footer, now that N is known and every sheet has its
        place - the sheets a table added while it ran on included."""
        total = self.layout.pageCollection().pageCount()
        for item in self.layout.items():
            if isinstance(item, QgsLayoutItemLabel) and item.id() == FOOTER_ID:
                item.setText(self._footer_text(item.page() + 1, total))

    def _date(self) -> str:
        """One date for the whole report: when the study ran, not when a page happened to be drawn.
        Two sources put two different dates on the same sheet as soon as a run crosses midnight or
        a saved layout is reopened a week later."""
        return str(self.meta.get("created_at", ""))[:10]

    # --- map page ---------------------------------------------------------------------------------

    def map_extent(self, scale: int, extent_factor: float, extra: Sequence = ()) -> QgsRectangle:
        """The extent of this page's map; see the module-level `map_extent`."""
        return map_extent(self.zone_ring, scale, extent_factor, extra)

    def _page_overlays(self, page: MapPage) -> List[QgsMapLayer]:
        """The overlays this page draws, zone excluded - the zone is the ring we start from."""
        return page_boxes(page, self.overlays)

    def _page_boxes(self, page: MapPage) -> List:
        """What this page widens for: the study's boxes when the builder has them (then the
        planner used the very same), its layers' extents otherwise."""
        return page_boxes(page, self.overlay_boxes if self.overlay_boxes is not None else self.overlays)

    def _map_layers(self, page: MapPage, extent: QgsRectangle) -> List[QgsMapLayer]:
        """Draw order, topmost first: the zone always, then what the page asked for, then the map.

        The map itself is the image fetched up front for exactly this box. Falling back to the live
        WMS layer when that image is missing would trade one empty background for a page that takes
        half a minute to draw, so a missing image simply leaves the background empty and the page
        says so.
        """
        snapshot = self.map_images.get(map_image_key(page.map_id, extent))
        return (list(self.overlays.get("zone", [])) + self._page_overlays(page)
                + ([snapshot] if snapshot is not None else []))

    def _scale_bar(self, map_item: QgsLayoutItemMap, real_scale: int, page: int,
                   y: float) -> QgsLayoutItemScaleBar:
        bar = QgsLayoutItemScaleBar(self.layout)
        self.layout.addLayoutItem(bar)
        bar.setStyle(SCALE_BAR_STYLE)
        bar.setLinkedMap(map_item)
        # applyDefaultSize() derives its own unit label and segment length from the map, so it goes
        # first: called after the explicit settings below, it would silently overwrite them.
        bar.applyDefaultSize(Qgis.DistanceUnit.Meters)
        bar.setUnits(Qgis.DistanceUnit.Meters)
        bar.setUnitLabel("m")
        bar.setTextFormat(_text_format(7))  # the bar prints its own numbers; keep them house-size
        bar.setNumberOfSegments(SCALE_BAR_SEGMENTS)
        bar.setNumberOfSegmentsLeft(0)
        bar.setUnitsPerSegment(_segment_length(real_scale))  # refreshes and re-fits the bar itself
        bar.attemptMove(point_mm(MARGIN, y), page=page)
        return bar

    def map_page(self, chapter: Chapter, page: MapPage) -> None:
        """One map, with what belongs under it on the same sheet.

        The frame is as tall as it can be once the legend of the zone (and a colour ramp, where a
        map has one instead of classes) has its room: that legend used to cost a sheet of its own
        for two rows. The frame only ever loses HEIGHT - the extent keeps its width, so the scale
        printed in the info box and the image fetched for this framing are the same either way.
        """
        slot = self._start(chapter, page.title, CONTENT_H, packable=False)
        index = slot.page
        entry = catalogue.by_id(page.map_id)
        extent = self.map_extent(page.scale, page.extent_factor, self._page_boxes(page))
        block = self._under_map(chapter, page, index)
        height = map_height(block.height)
        # Not even the first piece fits under a map that is still readable: the frame keeps its
        # full height and the whole block starts on the sheet behind it. With room to spare, mind:
        # `map_height` shrinks the frame to exactly what the block asked for, so the two sides of
        # this comparison are the same sum computed twice and differ by 1e-14 mm - which is how
        # the map key ended up alone on a sheet of 0.6 % ink. A hundredth of a millimetre is
        # smaller than anything a printer can draw and larger than any rounding error.
        overleaf = block.minimum > CONTENT_H - height - UNDER_MAP_GAP + FIT_TOLERANCE_MM
        if overleaf:
            height = MAP_H
        map_item = QgsLayoutItemMap(self.layout)
        map_item.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
        map_item.setLayers(self._map_layers(page, extent))
        map_item.setFrameEnabled(True)
        self.layout.addLayoutItem(map_item)
        map_item.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        map_item.attemptResize(size_mm(MAP_W, height))
        map_item.setExtent(crop_extent(extent, height))
        real_scale = int(round(map_item.scale()))
        # What the reader needs to judge the map: which map, of which project, at which scale...
        self.info_box([self.meta.get("project", ""), self._date(), entry.title,
                       f"schaal 1:{_thousands(real_scale)}"], INFO_TOP_Y, index, size=7)
        # ... and where it came from, on the same sheet, so a printed page stays attributable.
        self.info_box([entry.attribution, entry.licence, f"opgehaald {self._date()}"],
                      CONTENT_TOP + height - INFO_BOTTOM_LIFT, index, size=6)
        arrow = QgsLayoutItemPicture(self.layout)
        arrow.setPicturePath(str(NORTH_ARROW))
        arrow.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        # A black arrow on a dark roof in an aerial photo is invisible; it gets its own white field.
        arrow.setBackgroundEnabled(True)
        arrow.setBackgroundColor(BOX_BACKGROUND)
        self.layout.addLayoutItem(arrow)
        arrow.attemptMove(point_mm(*ARROW_XY), page=index)
        arrow.attemptResize(size_mm(ARROW_WH, ARROW_WH))
        self._scale_bar(map_item, real_scale, index, CONTENT_TOP + height + SCALE_BAR_LIFT)
        # The map stays on the sheet even without coverage - the zone circle is what the reader
        # came for - but the note says why the background is empty. A page whose image never
        # arrived is normally left out of the tree altogether (`report_content.build_report`);
        # this is what a caller that did not pass that information still gets to see.
        key = map_image_key(page.map_id, extent)
        empty = key in self.no_coverage
        missing = key not in self.map_images
        note = " ".join(part for part in (page.note, NO_COVERAGE_NOTE if empty else "",
                                          MISSING_MAP_NOTE if missing and not empty else "") if part)
        if note:
            self.label(note, MARGIN, NOTE_Y, CONTENT_W, 5, index, size=7)
        self._seal(index)
        if overleaf:
            index = self.new_page()
            self.header(chapter, f"{page.title} (vervolg)", index)
            self._seal(index)
            block.draw(index, CONTENT_TOP)
        else:
            block.draw(index, CONTENT_TOP + height + UNDER_MAP_GAP)
        if page.legend and self.legends and not empty:
            self.legend_pages(chapter, page)

    # --- what stands under a map frame ------------------------------------------------------------

    def _under_map(self, chapter: Chapter, page: MapPage, index: int) -> UnderMap:
        """Everything that belongs under this map frame, measured and ready to draw.

        In the order the reader needs it: first how to read the map (the leeswijzer), then what it
        says about this zone - the classes inside it, or the colour scale for a map that has one
        instead of classes.
        """
        blocks: List[UnderMap] = []
        if page.show_investigations or page.show_section_line:
            blocks.append(self._symbol_key_block(page))
        if page.guide is not None:
            blocks.append(self._guide_block(page.guide))
        if page.ramp is not None:
            blocks.append(self._ramp_block(page.ramp))
        if page.zone_legend is not None:
            blocks.append(self._zone_legend_block(chapter, page.zone_legend, index))
        if not blocks:
            return UnderMap(0.0, lambda sheet, top: None)
        height = (sum(block.height for block in blocks)
                  + UNDER_MAP_BLOCK_GAP * (len(blocks) - 1))

        def draw(sheet: int, top: float) -> None:
            y = top
            for block in blocks:
                block.draw(sheet, y)
                y += block.height + UNDER_MAP_BLOCK_GAP

        return UnderMap(height, draw, blocks[0].height)

    def _symbol_key_block(self, page: MapPage) -> UnderMap:
        """What the dots and the dashed line on the overview map mean.

        The map drew five kinds of point and a line and named none of them; this round added the
        purple diamonds of the virtual boreholes on top of that. The key goes where every other
        map's legend now goes - under the frame - as a swatch and a word per line.
        """
        rows = [(layers.ZONE_COLOUR, "Onderzoekszone")]
        if page.show_investigations:
            rows += [(layers.POINT_STYLE[kind][0], layers.POINT_NAMES[kind])
                     for kind in ("sondering", "boring", "peilput")]
            rows.append((layers.VB_STYLE[0], layers.VB_NAME))
        if page.show_section_line:
            rows.append((layers.SECTION_LINE_COLOUR, "Doorsnedelijn"))
        height = UNDER_MAP_TITLE_H + len(rows) * KEY_ROW_H

        def draw(sheet: int, top: float) -> None:
            self.label("Legenda bij de kaart", MARGIN, top, CONTENT_W, UNDER_MAP_TITLE_H, sheet,
                       size=8, bold=True)
            y = top + UNDER_MAP_TITLE_H
            for colour, name in rows:
                self._swatch(MARGIN, y + (KEY_ROW_H - KEY_SWATCH) / 2.0, colour, sheet)
                self.label(name, MARGIN + KEY_SWATCH + 1.5, y, CONTENT_W, KEY_ROW_H, sheet, size=7)
                y += KEY_ROW_H

        return UnderMap(height, draw, height)

    def _swatch(self, x: float, y: float, colour: str, page: int) -> None:
        """One coloured square of the map key, drawn the same way the points are coloured."""
        shape = QgsLayoutItemShape(self.layout)
        shape.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
        shape.setSymbol(QgsFillSymbol.createSimple(
            {"color": colour, "outline_color": "#ffffff", "outline_width": "0.2"}))
        self.layout.addLayoutItem(shape)
        shape.attemptMove(point_mm(x, y), page=page)
        shape.attemptResize(size_mm(KEY_SWATCH, KEY_SWATCH))

    def _guide_block(self, page: TextPage) -> UnderMap:
        """How to read this map, under its own frame instead of on a sheet of its own."""
        height = self._text_height(page.html, CONTENT_W)

        def draw(sheet: int, top: float) -> None:
            self.label(page.html, MARGIN, top, CONTENT_W, height, sheet, size=TEXT_FONT_PT,
                       html=True)

        return UnderMap(height, draw, height)

    def _rule(self, x: float, y: float, width: float, height: float, page: int) -> None:
        """A thin black bar: a tick under the colour strip, or the line that joins two of them.

        A shape rather than a label with a background: a rule is a rule, and a label carries a
        margin and a text layout that has nothing to do here.
        """
        shape = QgsLayoutItemShape(self.layout)
        shape.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
        shape.setSymbol(QgsFillSymbol.createSimple({"color": RULE_COLOUR, "outline_style": "no"}))
        self.layout.addLayoutItem(shape)
        shape.attemptMove(point_mm(x, y), page=page)
        shape.attemptResize(size_mm(width, height))

    def _mark_the_zone(self, ramp: ColourRamp, sheet: int, y: float) -> Tuple[str, float]:
        """Put this zone on the colour strip; answer with the line that names it and where it goes.

        A bracket between its lowest and highest value when those are far enough apart to tell
        apart on paper; otherwise one tick at the mean with a leader to the label, because two
        ticks half a millimetre apart are one fat tick that means nothing. The label starts at the
        mark and is slid back onto the paper when the mark sits near the right end.
        """
        if ramp.band is None or ramp.mean_at is None:
            return "", MARGIN
        left = MARGIN + ramp.band[0] * RAMP_STRIP_W
        right = MARGIN + ramp.band[1] * RAMP_STRIP_W
        if right - left >= RAMP_SPAN_MIN_MM:
            self._rule(left, y, RAMP_TICK_W, RAMP_TICK_H, sheet)
            self._rule(right, y, RAMP_TICK_W, RAMP_TICK_H, sheet)
            self._rule(left, y + RAMP_TICK_H - RAMP_TICK_W, right - left + RAMP_TICK_W,
                       RAMP_TICK_W, sheet)
            return ramp.band_label, left
        middle = MARGIN + ramp.mean_at * RAMP_STRIP_W
        self._rule(middle, y, RAMP_TICK_W, RAMP_TICK_H, sheet)
        self._rule(middle, y + RAMP_TICK_H - RAMP_TICK_W, RAMP_TICK_W * 2, RAMP_TICK_W, sheet)
        return ramp.mean_label, middle

    def _ramp_block(self, ramp: ColourRamp) -> UnderMap:
        """A colour scale as a strip: the service's own band, its two ends named under it and the
        zone's own values below that.

        Without the band no colours are drawn at all. A ramp painted from numbers would not match
        the picture right above it, and a legend that disagrees with its map is worse than none.
        """
        image = self.out_dir / ramp.image_path if ramp.image_path else None
        strip_h = RAMP_STRIP_H + RAMP_LABEL_GAP if image is not None else 0.0
        # The zone is only marked where there IS a strip: a tick beside no colours points nowhere.
        marked = image is not None and ramp.band is not None
        ticks = ramp.ticks if image is not None else []
        height = (UNDER_MAP_TITLE_H + strip_h + (RAMP_MARK_H + RAMP_LINE_H if marked else 0.0)
                  + (RAMP_LINE_H if ticks else 0.0)
                  + RAMP_LINE_H * (2 if ramp.note else 1) + RAMP_LINE_H)

        def draw(sheet: int, top: float) -> None:
            y = top
            self.label(ramp.title, MARGIN, y, CONTENT_W, UNDER_MAP_TITLE_H, sheet, size=9,
                       bold=True)
            y += UNDER_MAP_TITLE_H
            if image is not None:
                strip = QgsLayoutItemPicture(self.layout)
                strip.setPicturePath(str(image))
                # Stretch, not Zoom: the band is a gradient of a few pixels and the strip it has to
                # fill is a fixed one, so the aspect of the source says nothing.
                strip.setResizeMode(QgsLayoutItemPicture.ResizeMode.Stretch)
                strip.setFrameEnabled(True)
                self.layout.addLayoutItem(strip)
                strip.attemptMove(point_mm(MARGIN, y), page=sheet)
                strip.attemptResize(size_mm(RAMP_STRIP_W, RAMP_STRIP_H))
                y += strip_h
            if marked:
                # Against the bar, not a gap below it: a pointer that touches nothing points at
                # nothing. `strip_h` carries the air for the LABELS underneath, not for the mark.
                zone, at = self._mark_the_zone(ramp, sheet, y - RAMP_LABEL_GAP)
                y += RAMP_MARK_H
                self.label(zone, min(at, CONTENT_RIGHT - RAMP_MARK_LABEL_W), y,
                           RAMP_MARK_LABEL_W, RAMP_LINE_H, sheet, size=7, bold=True)
                y += RAMP_LINE_H
            for at, label in ticks:
                # A mark ON the bar as well as a number under it. The GxG classes are not evenly
                # spaced in value while the bar draws them at equal width, so numbers alone still
                # read as a linear scale; the tick says where each boundary actually falls.
                if image is not None:
                    self._rule(MARGIN + at * RAMP_STRIP_W - RAMP_TICK_W / 2.0,
                               y - RAMP_LABEL_GAP, RAMP_TICK_W, RAMP_TICK_H, sheet)
                # Centred on the boundary, and never off the paper at either end.
                left = MARGIN + at * RAMP_STRIP_W - RAMP_TICK_LABEL_W / 2.0
                left = min(max(left, MARGIN), CONTENT_RIGHT - RAMP_TICK_LABEL_W)
                centred = self.label(label, left, y, RAMP_TICK_LABEL_W, RAMP_LINE_H, sheet, size=6)
                centred.setHAlign(Qt.AlignmentFlag.AlignHCenter)
            if ticks:
                y += RAMP_LINE_H
            self.label(ramp.low, MARGIN, y, RAMP_STRIP_W, RAMP_LINE_H, sheet, size=7)
            high = self.label(ramp.high, MARGIN, y, RAMP_STRIP_W, RAMP_LINE_H, sheet, size=7)
            high.setHAlign(Qt.AlignmentFlag.AlignRight)
            y += RAMP_LINE_H
            self.label(ramp.summary, MARGIN, y, CONTENT_W, RAMP_LINE_H, sheet, size=8)
            if ramp.note:
                self.label(ramp.note, MARGIN, y + RAMP_LINE_H, CONTENT_W, RAMP_LINE_H, sheet,
                           size=7)

        return UnderMap(height, draw)

    def _zone_legend_block(self, chapter: Chapter, page, index: int) -> UnderMap:
        """The legend of the classes inside the zone, measured for the space under its map."""
        if isinstance(page, LegendPage):
            return self._legend_entries_block(chapter, page)
        return self._legend_table_block(chapter, page, index)

    def _legend_table_block(self, chapter: Chapter, page: TablePage, index: int) -> UnderMap:
        rows = [[str(cell) for cell in row] for row in page.rows]
        metrics = _page_metrics(PORTRAIT)
        if not rows:
            def draw_note(sheet: int, top: float) -> None:
                self._block_title(page.title, sheet, top)
                self.label(page.note, MARGIN, top + UNDER_MAP_TITLE_H, CONTENT_W, NOTE_BLOCK_H,
                           sheet, size=7)

            return UnderMap(UNDER_MAP_TITLE_H + NOTE_BLOCK_H, draw_note)
        table, frame, wanted = self._new_table(page, metrics, rows, index)
        # A note beside a FILLED table is not "why is this empty" but a sentence the table cannot
        # hold - the modelled thickness under the isopach map, the reason no contour is in view -
        # and it used to be dropped without a trace.
        note_h = self._text_height(page.note, CONTENT_W) if page.note else 0.0

        def draw(sheet: int, top: float) -> None:
            self._block_title(page.title, sheet, top)
            body = top + UNDER_MAP_TITLE_H
            if page.note:
                self.label(page.note, MARGIN, body, CONTENT_W, note_h, sheet, size=7)
                body += note_h
            room = CONTENT_TOP + metrics.content_h - body
            last = self._place_table(table, frame, sheet, body, min(wanted, room), metrics)
            for extra in range(sheet + 1, last + 1):
                self.header(chapter, f"{page.title} (vervolg)", extra, metrics)
            self._seal(last, metrics)

        return UnderMap(UNDER_MAP_TITLE_H + note_h + wanted, draw)

    def _legend_entries_block(self, chapter: Chapter, page: LegendPage) -> UnderMap:
        height = UNDER_MAP_TITLE_H + self._legend_entries_height(page)
        if page.note:
            height += NOTE_BLOCK_H

        def draw(sheet: int, top: float) -> None:
            self._block_title(page.title, sheet, top)
            y = top + UNDER_MAP_TITLE_H
            if page.note:
                self.label(page.note, MARGIN, y, CONTENT_W, NOTE_BLOCK_H, sheet, size=7)
                y += NOTE_BLOCK_H
            last = self._draw_legend_entries(chapter, page, sheet, y, CONTENT_TOP + CONTENT_H)
            self._seal(last)

        return UnderMap(height, draw)

    def _block_title(self, title: str, sheet: int, top: float) -> None:
        self.label(title, MARGIN, top, CONTENT_W, UNDER_MAP_TITLE_H, sheet, size=9, bold=True)

    def _legend_strip_size(self, entry) -> Tuple[float, float]:
        """The size the drawing of one legend entry is printed at; (0, 0) when there is none."""
        if not entry.image_path:
            return 0.0, 0.0
        return _natural_size(self.out_dir / entry.image_path, CONTENT_W, LEGEND_STRIP_MAX_H)

    def _legend_entries_height(self, page: LegendPage) -> float:
        """What the labels and strips of a legend page need, before anything is placed."""
        total = 0.0
        for entry in page.entries:
            _width, height = self._legend_strip_size(entry)
            total += LEGEND_LABEL_H + (height or LEGEND_LABEL_H) + LEGEND_GAP
        return total

    def _draw_legend_entries(self, chapter: Chapter, page: LegendPage, index: int, top: float,
                             bottom: float) -> int:
        """A label per entry with its drawing under it, down the sheet from `top`.

        The strips are what the reader looks at, so they are drawn at their own size rather than
        stretched, and they follow one another down. When the next entry no longer fits, the rest
        goes on a continuation sheet - a strip that runs off the paper helps nobody. Returns the
        last sheet used.
        """
        y = top
        for entry in page.entries:
            width, height = self._legend_strip_size(entry)
            needed = LEGEND_LABEL_H + (height or LEGEND_LABEL_H) + LEGEND_GAP
            if y + needed > bottom:
                index = self.new_page()
                self.header(chapter, f"{page.title} (vervolg)", index)
                y, bottom = CONTENT_TOP, CONTENT_TOP + CONTENT_H
            self.label(f"Profieltype {entry.code} - kaartblad {entry.sheet}", MARGIN, y, CONTENT_W,
                       LEGEND_LABEL_H, index, size=9, bold=True)
            y += LEGEND_LABEL_H
            if not entry.image_path:
                self.label(MISSING_DRAWING, MARGIN, y, CONTENT_W, LEGEND_LABEL_H, index, size=8)
                y += LEGEND_LABEL_H + LEGEND_GAP
                continue
            picture = QgsLayoutItemPicture(self.layout)
            picture.setPicturePath(str(self.out_dir / entry.image_path))
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            self.layout.addLayoutItem(picture)
            picture.attemptMove(point_mm(MARGIN, y), page=index)
            picture.attemptResize(size_mm(width, height))
            y += height + LEGEND_GAP
        return index

    def zone_legend_page(self, chapter: Chapter, page: LegendPage) -> None:
        """The classes of one map on a sheet of their own.

        Only reached when the map itself is not in the report - its image never arrived - because
        a legend that has a map to stand under stands under it (`_zone_legend_block`).
        """
        height = self._legend_entries_height(page) + (NOTE_BLOCK_H if page.note else 0.0)
        slot = self._start(chapter, page.title, min(height, CONTENT_H))
        y = slot.top
        if page.note:
            self.label(page.note, MARGIN, y, CONTENT_W, NOTE_BLOCK_H, slot.page, size=7)
            y += NOTE_BLOCK_H
        last = self._draw_legend_entries(chapter, page, slot.page, y, CONTENT_TOP + CONTENT_H)
        if last != slot.page:
            self._seal(last)

    def legend_pages(self, chapter: Chapter, page: MapPage) -> None:
        """The legend of the preceding map page, on sheets of its own.

        Not on the map page itself: a DOV legend runs to dozens of classes, and a map squeezed
        around one is unreadable. Each sheet is excluded from exports when `@legendas = 0`.
        """
        image = self.legend_images.get(page.map_id)
        if image is None:
            return
        strips = _legend_strips(image, page.map_id)
        for number, (path, width, height) in enumerate(strips, start=1):
            index = self.new_page()
            page_item = self.layout.pageCollection().page(index)
            page_item.setId(f"legenda-{page.map_id}" if len(strips) == 1
                            else f"legenda-{page.map_id}-{number}")
            page_item.dataDefinedProperties().setProperty(
                QgsLayoutObject.DataDefinedProperty.ExcludeFromExports,
                QgsProperty.fromExpression(f"@{LEGEND_VARIABLE} = 0"))
            title = page.title if len(strips) == 1 else f"{page.title} ({number}/{len(strips)})"
            self.header(chapter, f"Legenda - {title}", index)
            picture = QgsLayoutItemPicture(self.layout)
            picture.setPicturePath(str(path))
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            self.layout.addLayoutItem(picture)
            picture.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
            picture.attemptResize(size_mm(width, height))
            self._seal(index)

    # --- figure, table and text pages --------------------------------------------------------------

    def figure_page(self, chapter: Chapter, page: FigurePage) -> None:
        # StudyResult.figures are forward-slash paths relative to the output directory.
        image = self.out_dir / page.image_path
        size = QImage(str(image)).size()
        # A figure wider than it is tall (the section) fills a landscape sheet; on a portrait one
        # it shrinks to a strip across the top and leaves two thirds of the paper empty.
        metrics = _page_metrics(LANDSCAPE if size.width() > size.height() else PORTRAIT)
        # Never LARGER than it was drawn: a picture of three centimetres blown up to a hand's
        # width is a blurred banner, and a small figure that keeps its size leaves room for
        # whatever follows it on the same sheet.
        caption_h = CAPTION_H if page.caption else 0.0
        width, height = _natural_size(image, metrics.content_w, metrics.content_h - CAPTION_H)
        # A full-height column diagram after a four-row table used to leave that table alone on
        # 98 % white paper. The figure is already capped at its natural size, so capping it a
        # little further to join the open sheet costs legibility, not content - but only down to
        # FIGURE_MIN_H, below which a sounding diagram is a smudge and deserves its own sheet.
        room = self._room_left(chapter, metrics) - caption_h
        if height > room >= FIGURE_MIN_H:
            width, height = _drawn_size(image, metrics.content_w, room)
        slot = self._start(chapter, page.title, height + caption_h, metrics)
        picture = QgsLayoutItemPicture(self.layout)
        picture.setPicturePath(str(image))
        picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        self.layout.addLayoutItem(picture)
        picture.attemptMove(point_mm(MARGIN, slot.top), page=slot.page)
        picture.attemptResize(size_mm(width, height))
        if page.caption:
            self.label(page.caption, MARGIN, slot.top + height + 2.0, metrics.content_w, 10,
                       slot.page, size=7)

    def _fit_continuation_frames(self, table: QgsLayoutMultiFrame, metrics: PageMetrics) -> int:
        """Pull the follow-on frames into the content band; return the last page the table uses.

        QGIS lays every continuation frame of an ExtendToNextPage table over the *whole* sheet,
        header and footer included, so without this the second page of a table starts at the paper
        edge and runs straight through the page number. A shorter frame holds fewer rows and can
        need one more page, so the re-flow repeats until the page count settles.
        """
        collection = self.layout.pageCollection()
        settled = False
        for _ in range(MAX_TABLE_REFLOW):
            before = collection.pageCount()
            for frame in table.frames()[1:]:
                frame.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=frame.page())
                frame.attemptResize(size_mm(metrics.content_w, metrics.content_h))
            table.recalculateFrameSizes()
            if collection.pageCount() == before:
                settled = True
                break
        if not settled and self.log:
            # Not "a long table" but a table that keeps growing every pass. Saying so beats a
            # report with a tail of stray sheets that nobody can explain afterwards.
            self.log.warning(f"Tabel groeide na {MAX_TABLE_REFLOW} herberekeningen nog; "
                             "paginanummers kunnen verspringen")
        return max((frame.page() for frame in table.frames()), default=collection.pageCount() - 1)

    def _new_table(self, page: TablePage, metrics: PageMetrics, rows: List[List[str]],
                   index: int) -> Tuple[QgsLayoutItemTextTable, QgsLayoutFrame, float]:
        """The table of one TablePage, built and measured but not yet in its final place.

        Every column is given an explicit width measured from its own content, because the default
        (equal shares, clipped) is what cut every contractor name in half. The frame is parked on
        `index` at the full content height only to have somewhere to live while it is measured;
        `_place_table` moves it where it belongs.
        """
        table = QgsLayoutItemTextTable(self.layout)
        self.layout.addMultiFrame(table)
        # What the columns may share is the frame minus what the table spends around them: a cell
        # margin left and right of every column, and a grid line between and outside them. Measured
        # on 3.40.15 `totalWidth()` is exactly the sum of those three, so leaving the grid out of
        # the sum puts the table 2.5 mm over the frame edge.
        count = len(page.columns)
        grid = (count + 1) * table.gridStrokeWidth() if table.showGrid() else 0.0
        available = metrics.content_w - 2 * table.cellMargin() * count - grid
        columns = []
        for heading, width in zip(page.columns, column_widths(list(page.columns), rows, available)):
            column = QgsLayoutTableColumn(heading)
            column.setWidth(width)
            columns.append(column)
        table.setColumns(columns)
        table.setHeaderMode(QgsLayoutTable.HeaderMode.AllFrames)
        # With fixed widths a long sentence has to break inside its column; without this QGIS
        # writes it straight through the next column and off the sheet.
        table.setWrapBehavior(QgsLayoutTable.WrapBehavior.WrapText)
        table.setContentTextFormat(_text_format(TABLE_FONT_PT))
        table.setHeaderTextFormat(_text_format(TABLE_FONT_PT, bold=True))
        # The rows go in last: every setter above re-measures whatever the table holds, and a
        # table of a hundred and thirty rows measured five times over is a second of nothing.
        table.setContents(rows)
        frame = QgsLayoutFrame(self.layout, table)
        # Into the layout before it is moved: attemptMove resolves `page` via the page collection.
        self.layout.addLayoutItem(frame)
        frame.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        frame.attemptResize(size_mm(metrics.content_w, metrics.content_h))
        table.addFrame(frame)  # recalculates the frame sizes itself
        return table, frame, self._table_height(table, len(rows), metrics.content_h)

    def _table_height(self, table: QgsLayoutTable, rows: int, available: float) -> float:
        """The shortest frame that still holds every row, asked of the table itself.

        `totalSize()` is no help here: it never reports less than the frame it was given, so a
        table of two rows in a full-page frame claims a full page (measured on 3.40.15). What does
        answer honestly is `rowsVisible` - how many rows fit in a height - so the height is found
        by halving the interval, with a millimetre of slack on the answer.
        """
        context = QgsLayoutUtils.createRenderContextForLayout(self.layout, None)
        if table.rowsVisible(context, available, 0, True, False) < rows:
            return available  # it does not fit whatever we do; let it run on
        low, high = 0.0, available
        for _ in range(TABLE_FIT_STEPS):
            middle = (low + high) / 2.0
            if table.rowsVisible(context, middle, 0, True, False) >= rows:
                high = middle
            else:
                low = middle
        return min(available, high + TABLE_FIT_MARGIN)

    def _place_table(self, table: QgsLayoutTable, frame: QgsLayoutFrame, index: int, top: float,
                     height: float, metrics: PageMetrics) -> int:
        """Put the measured table where it belongs and let it run on; returns its last sheet."""
        frame.attemptMove(point_mm(MARGIN, top), page=index)
        frame.attemptResize(size_mm(metrics.content_w, height))
        # A borehole table easily outgrows one sheet; truncating it silently would lose rows.
        table.setResizeMode(QgsLayoutMultiFrame.ResizeMode.ExtendToNextPage)
        table.recalculateFrameSizes()
        return self._fit_continuation_frames(table, metrics)

    def table_page(self, chapter: Chapter, page: TablePage) -> None:
        """One table, on as much of a sheet as it needs and as many sheets as it needs.

        A table gets a landscape sheet when its columns do not fit the portrait width - nine wide
        columns in 180 mm cost the last one, which is how the DOV fiche numbers walked off the
        paper - and keeps a portrait one when they do.
        """
        rows = [[str(cell) for cell in row] for row in page.rows]
        metrics = _page_metrics(PORTRAIT if _fits_portrait(page.columns, rows) else LANDSCAPE)
        if not rows:
            # A row of column headings with nothing under it promises a table that never comes; the
            # note ("Geen kaarteenheden binnen de zone.", "Bron niet beschikbaar.") is the answer,
            # and it is all this piece of content costs.
            slot = self._start(chapter, page.title, NOTE_BLOCK_H, metrics)
            self.label(page.note, MARGIN, slot.top if slot.packed else NOTE_Y, metrics.content_w,
                       NOTE_BLOCK_H, slot.page, size=7)
            return
        # A note of its own lines, not a fixed strip: the rule about which soundings are drawn runs
        # to four lines, and a 6 mm band either clipped it or let it run over the first rows.
        note_h = max(NOTE_BLOCK_H, self._text_height(page.note, metrics.content_w))             if page.note else 0.0
        table, frame, wanted = self._new_table(page, metrics, rows, max(self._sheet, 0))
        slot = self._start(chapter, page.title, min(wanted + note_h, metrics.content_h), metrics)
        top = slot.top
        if page.note:
            # Above the table when it shares a sheet; in the header band when it is short enough to
            # live there for free, which is where this note has always stood. A longer one starts
            # the content band instead and pushes the table down - it may not cross its own table.
            in_band = not slot.packed and note_h <= CONTENT_TOP - NOTE_Y
            self.label(page.note, MARGIN, NOTE_Y if in_band else top, metrics.content_w,
                       note_h, slot.page, size=7)
            if not in_band:
                top += note_h
        room = CONTENT_TOP + metrics.content_h - top
        last = self._place_table(table, frame, slot.page, top, min(wanted, room), metrics)
        for extra in range(slot.page + 1, last + 1):
            self.header(chapter, f"{page.title} (vervolg)", extra, metrics)
        if last != slot.page:
            self._seal(last, metrics)
        fiches = _fiche_note(page.links or [])
        if fiches:
            # Under the TABLE, on its last sheet - not at the foot of the paper. A three-row table
            # left the note floating a hand's width below it, reading as a footer of the sheet
            # rather than a line about those three rows.
            frames = [f for f in table.frames() if f.page() == last]
            bottom = (max(f.pos().y() + f.rect().height() for f in frames) if frames
                      else CONTENT_TOP + metrics.content_h)
            bottom = min(bottom, CONTENT_TOP + metrics.content_h)
            self.label(fiches, MARGIN, bottom + 2.0, metrics.content_w, 5, last, size=6)
            self._cursor = max(self._cursor, bottom + 2.0 + 5.0)

    def _text_height(self, html: str, width: float) -> float:
        """How tall a paragraph of HTML needs to be, measured on its plain text.

        An HTML label sized by `adjustSizeToText` measures the width of its MARKUP, so the tags are
        stripped first and the text measured the way an info box is. The answer is deliberately
        generous: a label a millimetre too short clips its last line, one a millimetre too tall
        only costs white paper.
        """
        plain = " ".join(TAGS.sub(" ", html).split())
        probe = QgsLayoutItemLabel(self.layout)
        probe.setTextFormat(_text_format(TEXT_FONT_PT))
        self.layout.addLayoutItem(probe)
        try:
            _width, height = _fit_box(probe, [plain], width, 0.0)
        finally:
            self.layout.removeLayoutItem(probe)
        return min(CONTENT_H, height * TEXT_HEIGHT_FUDGE + TEXT_HEIGHT_PAD)

    def text_page(self, chapter: Chapter, page: TextPage) -> None:
        height = self._text_height(page.html, CONTENT_W)
        slot = self._start(chapter, page.title, height)
        self.label(page.html, MARGIN, slot.top, CONTENT_W, height, slot.page, size=TEXT_FONT_PT,
                   html=True)

    # --- title page --------------------------------------------------------------------------------

    def title_page(self) -> None:
        index = self.new_page()
        logo = self.meta.get("logo_path")
        y = 20.0
        if logo and Path(logo).exists():
            picture = QgsLayoutItemPicture(self.layout)
            picture.setPicturePath(str(logo))
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            self.layout.addLayoutItem(picture)
            picture.attemptMove(point_mm(MARGIN, y), page=index)
            picture.attemptResize(size_mm(60, 30))
            y += 35
        self.label(self.report.title, MARGIN, y, CONTENT_W, 14, index, size=20, bold=True)
        # The zone line is left out when it only repeats the address: a study started from an
        # address names its zone after that address, and the same line twice says nothing twice.
        zone_name = self.meta.get("zone_name")
        rows = [("Project", self.meta.get("project")),
                ("Projectnummer", self.meta.get("project_number")),
                ("Adres", self.meta.get("address")), ("Gemeente", self.meta.get("municipality"))]
        if zone_name and zone_name != self.meta.get("address"):
            rows.append(("Zone", zone_name))
        rows += [("Datum", self._date()), ("Auteur", self.meta.get("author")),
                 ("Bedrijf", self.meta.get("company"))]
        cells = "".join(f"<tr><td><b>{key}</b></td><td>{value or '-'}</td></tr>" for key, value in rows)
        self.label(f"<table>{cells}</table>", MARGIN, y + 20, CONTENT_W, 60, index, size=9, html=True)
        chapters = "<br>".join(f"{c.number}. {c.title}" for c in self.report.chapters)
        self.label(f"<b>Inhoud</b><br>{chapters}", MARGIN, y + 85, CONTENT_W, 60, index,
                   size=9, html=True)
        self.label(self.meta.get("disclaimer", ""), MARGIN, 240, CONTENT_W, 30, index,
                   size=7, html=True)
        self._seal(index)

    def build(self) -> QgsPrintLayout:
        # Nobody will ever undo the building of a report, but QGIS records a command for every
        # page, frame and item added - each one a snapshot of the object as XML, before and after.
        undo = self.layout.undoStack()
        undo.blockCommands(True)
        try:
            self.title_page()
            for chapter in self.report.chapters:
                for page in chapter.pages:
                    self._raise_if_cancelled()
                    if isinstance(page, MapPage):
                        self.map_page(chapter, page)
                    elif isinstance(page, FigurePage):
                        self.figure_page(chapter, page)
                    elif isinstance(page, LegendPage):
                        self.zone_legend_page(chapter, page)
                    elif isinstance(page, TablePage):
                        self.table_page(chapter, page)
                    else:
                        self.text_page(chapter, page)
            self._footer_every_sheet()
            self._number_footers()
        finally:
            undo.blockCommands(False)
        # Without this the data-defined properties - the legend switch above all - are still
        # unevaluated, and the first export silently keeps every page. Only those: a full
        # `refresh()` re-measures every label and costs seconds on a hundred sheets.
        refresh_data_defined(self.layout)
        return self.layout


def build_layout(project: QgsProject, report: Report,
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = False, legend_images: Optional[Dict[str, Path]] = None, log=None,
                 should_cancel: Optional[Callable[[], bool]] = None,
                 no_coverage: Optional[Set[str]] = None,
                 map_images: Optional[Dict[str, QgsMapLayer]] = None,
                 overlay_boxes: Optional[Dict[str, List[BBox]]] = None,
                 name: Optional[str] = None, compact: bool = False) -> QgsPrintLayout:
    """The whole report as one print layout. See LayoutBuilder for what lands where."""
    return LayoutBuilder(project, report, overlays, out_dir, zone_ring, meta,
                         legends, legend_images, log, should_cancel, no_coverage,
                         map_images, overlay_boxes, name, compact).build()
