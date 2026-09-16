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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils,
    QgsLayoutFrame,
    QgsLayoutItemLabel,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemTextTable,
    QgsLayoutMultiFrame,
    QgsLayoutObject,
    QgsLayoutTable,
    QgsLayoutTableColumn,
    QgsMapLayer,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsRectangle,
    QgsTextFormat,
)
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QImage

from ..core import catalogue, geometry, parallel
from ..core.catalogue import MapEntry
from ..core.geometry import BBox
from ..core.model import StudyResult
from ..core.report_content import (
    QUARTAIR_CODE,
    QUARTAIR_ID,
    QUARTAIR_IMAGE,
    Chapter,
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
MAP_W, MAP_H = 180.0, 200.0
NOTE_Y = 25.5
FOOTER_Y = 285.0
INFO_TOP_Y, INFO_BOTTOM_Y = 46.0, 210.0
INFO_W, INFO_H = 55.0, 22.0
INFO_MARGIN_MM = 1.0
ARROW_XY, ARROW_WH = (183.0, 32.0), 12.0
SCALE_BAR_Y = 232.0
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
WIDE_TABLE_COLUMNS = 7
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


def prepare_map_images(requests: Sequence[MapRequest], out_dir, client: HttpClient, log=None,
                       should_cancel: Optional[Callable[[], bool]] = None
                       ) -> Tuple[Dict[str, Path], Set[str]]:
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
    """
    out_dir = Path(out_dir)
    images: Dict[str, Path] = {}
    empty: Set[str] = set()

    def fetch(request: MapRequest) -> None:
        entry = catalogue.by_id(request.map_id)
        url = wms_map_url(entry, request.extent, request.width, request.height)
        data = client.get(url, timeout=MAP_IMAGE_TIMEOUT_S, retries=MAP_IMAGE_RETRIES)
        image = QImage()
        if not data or not image.loadFromData(data):
            raise HttpError(url, None, f"antwoord voor {request.map_id} is geen afbeelding "
                                       f"({len(data)} bytes)")
        path = out_dir / DATA_DIR / MAP_IMAGE_DIR / f"{request.map_id}_{_image_name(request.key)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _write_world_file(path.with_suffix(".pgw"), request)
        images[request.key] = path
        if entry.fact_mode is None and _is_empty(image):
            empty.add(request.key)

    parallel.load_each(list(requests), fetch, "kaartbeeld", MAP_IMAGE_WORKERS, log, should_cancel)
    if log:
        blank = sorted({request.map_id for request in requests if request.key in empty})
        log.info(f"Kaartbeelden opgehaald: {len(images)}/{len(requests)}"
                 + (f"; geen kaartbeeld op deze locatie voor: {', '.join(blank)}" if blank else ""))
        missing = [request.map_id for request in requests if request.key not in images]
        if missing:
            log.warning(f"Geen kaartbeeld voor: {', '.join(sorted(set(missing)))}")
    return images, empty


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


class LayoutBuilder:
    """One report -> one layout. Build it once; `build()` is not idempotent."""

    def __init__(self, project: QgsProject, report: Report,
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = True, legend_images: Optional[Dict[str, Path]] = None,
                 log=None, should_cancel: Optional[Callable[[], bool]] = None,
                 no_coverage: Optional[Set[str]] = None,
                 map_images: Optional[Dict[str, QgsMapLayer]] = None,
                 overlay_boxes: Optional[Dict[str, List[BBox]]] = None,
                 name: Optional[str] = None):
        """overlays: keys 'zone', 'investigations', 'section' -> the memory layers a page may ask
        to draw on top of its map image; name: what the layout is called in the layout manager
        (`layout_name`), the bare plugin name when left empty;
        legend_images: map_id -> legend PNG, as `prepare_legends` returns them; no_coverage: the
        `map_image_key`s whose service drew nothing there - per framing, because one map can carry
        several and a mosaic can cover the narrow one and not the wide one; map_images: the same
        key -> the raster layer of the image fetched for it, which a map page draws instead of the
        live WMS layer; overlay_boxes: what a page widens for, as `overlay_boxes` gives it - the same
        boxes the images were planned on. Without them the page widens for its layers' extents,
        which is fine when nobody planned an image for it (the direct tests)."""
        self.project, self.report = project, report
        self.overlays = overlays
        self.overlay_boxes = overlay_boxes
        self.out_dir, self.zone_ring, self.meta = Path(out_dir), list(zone_ring), meta
        self.legends = legends
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

    def _scale_bar(self, map_item: QgsLayoutItemMap, real_scale: int,
                   page: int) -> QgsLayoutItemScaleBar:
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
        bar.attemptMove(point_mm(MARGIN, SCALE_BAR_Y), page=page)
        return bar

    def map_page(self, chapter: Chapter, page: MapPage) -> None:
        index = self.new_page()
        self.header(chapter, page.title, index)
        entry = catalogue.by_id(page.map_id)
        extent = self.map_extent(page.scale, page.extent_factor, self._page_boxes(page))
        map_item = QgsLayoutItemMap(self.layout)
        map_item.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
        map_item.setLayers(self._map_layers(page, extent))
        map_item.setFrameEnabled(True)
        self.layout.addLayoutItem(map_item)
        map_item.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        map_item.attemptResize(size_mm(MAP_W, MAP_H))
        map_item.setExtent(extent)
        real_scale = int(round(map_item.scale()))
        # What the reader needs to judge the map: which map, of which project, at which scale...
        self.info_box([self.meta.get("project", ""), self._date(), entry.title,
                       f"schaal 1:{_thousands(real_scale)}"], INFO_TOP_Y, index, size=7)
        # ... and where it came from, on the same sheet, so a printed page stays attributable.
        self.info_box([entry.attribution, entry.licence, f"opgehaald {self._date()}"],
                      INFO_BOTTOM_Y, index, size=6)
        arrow = QgsLayoutItemPicture(self.layout)
        arrow.setPicturePath(str(NORTH_ARROW))
        arrow.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        # A black arrow on a dark roof in an aerial photo is invisible; it gets its own white field.
        arrow.setBackgroundEnabled(True)
        arrow.setBackgroundColor(BOX_BACKGROUND)
        self.layout.addLayoutItem(arrow)
        arrow.attemptMove(point_mm(*ARROW_XY), page=index)
        arrow.attemptResize(size_mm(ARROW_WH, ARROW_WH))
        self._scale_bar(map_item, real_scale, index)
        # The map stays on the sheet even without coverage - the zone circle is what the reader
        # came for - but the note says why the background is empty.
        key = map_image_key(page.map_id, extent)
        empty = key in self.no_coverage
        missing = key not in self.map_images
        note = " ".join(part for part in (page.note, NO_COVERAGE_NOTE if empty else "",
                                          MISSING_MAP_NOTE if missing and not empty else "") if part)
        if note:
            self.label(note, MARGIN, NOTE_Y, CONTENT_W, 5, index, size=7)
        self.footer(index)
        if page.legend and self.legends and not empty:
            self.legend_pages(chapter, page)

    def zone_legend_page(self, chapter: Chapter, page: LegendPage) -> None:
        """Every class of one map on a sheet: a label per entry, its drawing under it.

        The strips are what the reader looks at, so they are drawn at their own size rather than
        stretched, and they follow one another down the sheet. When the next entry no longer fits,
        the rest goes on a continuation sheet - a strip that runs off the paper helps nobody.
        """
        index = self.new_page()
        self.header(chapter, page.title, index)
        y = CONTENT_TOP
        if page.note:
            self.label(page.note, MARGIN, NOTE_Y, CONTENT_W, 5, index, size=7)
        for entry in page.entries:
            image = self.out_dir / entry.image_path if entry.image_path else None
            width, height = (_natural_size(image, CONTENT_W, LEGEND_STRIP_MAX_H)
                             if image is not None else (0.0, 0.0))
            needed = LEGEND_LABEL_H + height + LEGEND_GAP
            if y + needed > CONTENT_TOP + CONTENT_H:
                self.footer(index)  # the sheet being left, not the one being started
                index = self.new_page()
                self.header(chapter, f"{page.title} (vervolg)", index)
                y = CONTENT_TOP
            self.label(f"Profieltype {entry.code} - kaartblad {entry.sheet}", MARGIN, y, CONTENT_W,
                       LEGEND_LABEL_H, index, size=9, bold=True)
            y += LEGEND_LABEL_H
            if image is None:
                self.label(MISSING_DRAWING, MARGIN, y, CONTENT_W, LEGEND_LABEL_H, index, size=8)
                y += LEGEND_LABEL_H + LEGEND_GAP
                continue
            picture = QgsLayoutItemPicture(self.layout)
            picture.setPicturePath(str(image))
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            self.layout.addLayoutItem(picture)
            picture.attemptMove(point_mm(MARGIN, y), page=index)
            picture.attemptResize(size_mm(width, height))
            y += height + LEGEND_GAP
        self.footer(index)

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
            self.footer(index)

    # --- figure, table and text pages --------------------------------------------------------------

    def figure_page(self, chapter: Chapter, page: FigurePage) -> None:
        # StudyResult.figures are forward-slash paths relative to the output directory.
        image = self.out_dir / page.image_path
        size = QImage(str(image)).size()
        # A figure wider than it is tall (the section) fills a landscape sheet; on a portrait one
        # it shrinks to a strip across the top and leaves two thirds of the paper empty.
        metrics = _page_metrics(LANDSCAPE if size.width() > size.height() else PORTRAIT)
        index = self.new_page(metrics.orientation)
        self.header(chapter, page.title, index, metrics)
        width, height = _drawn_size(image, metrics.content_w, metrics.content_h - 12.0)
        picture = QgsLayoutItemPicture(self.layout)
        picture.setPicturePath(str(image))
        picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        self.layout.addLayoutItem(picture)
        picture.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        picture.attemptResize(size_mm(width, height))
        if page.caption:
            self.label(page.caption, MARGIN, CONTENT_TOP + height + 2.0, metrics.content_w, 10, index,
                       size=7)
        self.footer(index, metrics)

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

    def table_page(self, chapter: Chapter, page: TablePage) -> None:
        """One table, on as many sheets as it needs.

        Two decisions before anything is drawn. A table of WIDE_TABLE_COLUMNS columns or more gets
        a landscape sheet - nine columns in 180 mm cost the last one, which is how the DOV fiche
        numbers walked off the paper. And every column is given an explicit width measured from
        its own content, because the default (equal shares, clipped) is what cut every contractor
        name in half.
        """
        rows = [[str(cell) for cell in row] for row in page.rows]
        metrics = _page_metrics(LANDSCAPE if len(page.columns) >= WIDE_TABLE_COLUMNS else PORTRAIT)
        index = self.new_page(metrics.orientation)
        self.header(chapter, page.title, index, metrics)
        if not rows:
            # A row of column headings with nothing under it promises a table that never comes; the
            # note ("Geen kaarteenheden binnen de zone.", "Bron niet beschikbaar.") is the answer.
            self.label(page.note, MARGIN, NOTE_Y, metrics.content_w, 5, index, size=7)
            self.footer(index, metrics)
            return
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
        # A borehole table easily outgrows one sheet; truncating it silently would lose rows.
        table.setResizeMode(QgsLayoutMultiFrame.ResizeMode.ExtendToNextPage)
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
        last = self._fit_continuation_frames(table, metrics)
        if page.note:
            self.label(page.note, MARGIN, NOTE_Y, metrics.content_w, 5, index, size=7)
        self.footer(index, metrics)
        for extra in range(index + 1, last + 1):
            self.header(chapter, f"{page.title} (vervolg)", extra, metrics)
            self.footer(extra, metrics)
        fiches = _fiche_note(page.links or [])
        if fiches:
            # Under the table, on its last sheet: that is where the reader has the numbers.
            self.label(fiches, MARGIN, CONTENT_TOP + metrics.content_h + 2.0, metrics.content_w, 5,
                       last, size=6)

    def text_page(self, chapter: Chapter, page: TextPage) -> None:
        index = self.new_page()
        self.header(chapter, page.title, index)
        self.label(page.html, MARGIN, CONTENT_TOP, CONTENT_W, CONTENT_H, index, size=9, html=True)
        self.footer(index)

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
        self.footer(index)

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
                 legends: bool = True, legend_images: Optional[Dict[str, Path]] = None, log=None,
                 should_cancel: Optional[Callable[[], bool]] = None,
                 no_coverage: Optional[Set[str]] = None,
                 map_images: Optional[Dict[str, QgsMapLayer]] = None,
                 overlay_boxes: Optional[Dict[str, List[BBox]]] = None,
                 name: Optional[str] = None) -> QgsPrintLayout:
    """The whole report as one print layout. See LayoutBuilder for what lands where."""
    return LayoutBuilder(project, report, overlays, out_dir, zone_ring, meta,
                         legends, legend_images, log, should_cancel, no_coverage,
                         map_images, overlay_boxes, name).build()
