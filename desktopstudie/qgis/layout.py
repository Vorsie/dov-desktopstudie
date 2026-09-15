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
the pages that were left out, because the numbering belongs to the layout, not to the export.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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
from qgis.PyQt.QtGui import QColor, QFont, QImage

from ..core import catalogue, geometry
from ..core.catalogue import MapEntry
from ..core.report_content import Chapter, FigurePage, MapPage, Report, TablePage, TextPage
from ..core.services.http import HttpClient, HttpError, build_url
from .compat import point_mm, size_mm

CRS_AUTHID = "EPSG:31370"
LAYOUT_NAME = "DOV Desktopstudie"
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
# A legend graphic is authored at screen resolution; blowing it up to the full content width turns
# 7 pt labels into blurry blocks, so it is never drawn larger than its natural size.
LEGEND_MM_PER_PX = 25.4 / 96.0
MAX_TABLE_REFLOW = 20  # a table still growing after this many passes is a bug, not a long table


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


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _joined(*parts: Optional[str]) -> str:
    """The parts a study actually knows, separated by dashes. A study without a company name must
    not print a footer that opens with a dangling separator."""
    return " - ".join(part for part in parts if part)


def _drawn_size(image_path, max_w: float, max_h: float,
                mm_per_px: Optional[float] = None) -> Tuple[float, float]:
    """The size in mm at which a picture is really drawn inside max_w x max_h, aspect kept.

    That is what ResizeMode.Zoom does, but QGIS does it while painting and never tells the layout,
    so a caption placed under the *frame* floats a hand's width below a square figure. With
    `mm_per_px` the picture is additionally capped at its natural size.
    """
    size = QImage(str(image_path)).size()
    if size.isEmpty():
        return max_w, max_h
    scale = min(max_w / size.width(), max_h / size.height())
    if mm_per_px is not None:
        scale = min(scale, mm_per_px)
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
        data = client.get(url)
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


def prepare_legends(entries: Sequence[MapEntry], out_dir, client: Optional[HttpClient] = None,
                    log=None) -> Dict[str, Path]:
    """map_id -> legend PNG, for the entries that ask for a legend.

    Fetched here rather than by the layout so that one failing service costs one legend page, not
    the report, and so the shell can run this phase with its own progress and cancellation.
    """
    out_dir = Path(out_dir)
    if client is None:
        client = HttpClient(cache_dir=out_dir / "data" / "cache", log=log)
    wanted = [entry for entry in entries if entry.legend]
    images: Dict[str, Path] = {}
    for entry in wanted:
        path = fetch_legend(entry, out_dir, client, log)
        if path is not None:
            images[entry.id] = path
    if log:
        missing = [entry.id for entry in wanted if entry.id not in images]
        log.info(f"Legendas opgehaald: {len(images)}/{len(wanted)}")
        if missing:
            log.warning(f"Geen legenda voor: {', '.join(missing)}")
    return images


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
    mm_per_px = min(CONTENT_W / image.width(), LEGEND_MM_PER_PX)
    width_mm = image.width() * mm_per_px
    height_mm = image.height() * mm_per_px
    if height_mm <= CONTENT_H + 0.01:
        return [(Path(image_path), width_mm, height_mm)]
    rows = max(1, int(CONTENT_H / mm_per_px))
    strips: List[Tuple[Path, float, float]] = []
    for number, top in enumerate(range(0, image.height(), rows), start=1):
        height = min(rows, image.height() - top)
        strip = Path(image_path).with_name(f"{map_id}_{number}.png")
        image.copy(0, top, image.width(), height).save(str(strip))
        strips.append((strip, width_mm, height * mm_per_px))
    return strips


class LayoutBuilder:
    """One report -> one layout. Build it once; `build()` is not idempotent."""

    def __init__(self, project: QgsProject, report: Report,
                 layers_by_map: Dict[str, List[QgsMapLayer]],
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = True, legend_images: Optional[Dict[str, Path]] = None):
        """layers_by_map: map_id -> [QgsMapLayer, ...] to draw (WMS + basemap); overlays: keys
        'zone', 'investigations', 'section' -> the memory layers a page may ask to draw on top;
        legend_images: map_id -> legend PNG, as `prepare_legends` returns them."""
        self.project, self.report = project, report
        self.layers_by_map, self.overlays = layers_by_map, overlays
        self.out_dir, self.zone_ring, self.meta = Path(out_dir), list(zone_ring), meta
        self.legends = legends
        self.legend_images = dict(legend_images or {})
        self.layout = QgsPrintLayout(project)
        self.layout.initializeDefaults()  # this already gives page 0, in A4 landscape
        self.layout.setName(LAYOUT_NAME)
        QgsExpressionContextUtils.setLayoutVariable(self.layout, LEGEND_VARIABLE, 1 if legends else 0)
        self._first_page_used = False

    # --- page furniture ---------------------------------------------------------------------------

    def new_page(self) -> int:
        """Append a page and return its index - read from the collection, never counted here.

        A table that runs on appends pages of its own, so a counter of ours drifts behind and the
        next report page lands on top of the last table page.
        """
        collection = self.layout.pageCollection()
        if self._first_page_used:
            page = QgsLayoutItemPage(self.layout)
            page.setPageSize(PAGE_SIZE, QgsLayoutItemPage.Orientation.Portrait)
            collection.addPage(page)
        else:
            # initializeDefaults() laid page 0 down in A4 *landscape*. The report is portrait from
            # cover to cover, and on a landscape first page everything below 210 mm - the table of
            # contents, the disclaimer - simply falls off the paper.
            collection.page(0).setPageSize(PAGE_SIZE, QgsLayoutItemPage.Orientation.Portrait)
            self._first_page_used = True
        return collection.pageCount() - 1

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
        item = QgsLayoutItemLabel(self.layout)
        item.setText("\n".join(part for part in lines if part))
        item.setTextFormat(_text_format(size))
        item.setMargin(INFO_MARGIN_MM)
        item.setFrameEnabled(True)
        item.setBackgroundEnabled(True)
        item.setBackgroundColor(BOX_BACKGROUND)
        self.layout.addLayoutItem(item)
        item.attemptMove(point_mm(CONTENT_RIGHT - INFO_W, y), page=page)
        item.attemptResize(size_mm(INFO_W, INFO_H))
        item.adjustSizeToText()
        # Pin the right edge to the margin afterwards. adjustSizeToText shifts the box by its own
        # rules (a reference point of UpperRight still moves it half a step), so the only reliable
        # way to keep a long licence line on the sheet is to place the box once its width is known.
        item.attemptMove(point_mm(CONTENT_RIGHT - item.rect().width(), y), page=page)
        return item

    def header(self, chapter: Chapter, title: str, page: int) -> None:
        self.label(f"{chapter.number}. {chapter.title}", MARGIN, 10, CONTENT_W, 8, page,
                   size=13, bold=True)
        self.label(title, MARGIN, 18, CONTENT_W, 7, page, size=10)

    def footer(self, page: int) -> None:
        text = _joined(self.meta.get("company"), self.meta.get("project"),
                       "pagina [% @layout_page %] / [% @layout_numpages %]")
        self.label(text, MARGIN, FOOTER_Y, CONTENT_W, 6, page, size=7)

    def _date(self) -> str:
        """One date for the whole report: when the study ran, not when a page happened to be drawn.
        Two sources put two different dates on the same sheet as soon as a run crosses midnight or
        a saved layout is reopened a week later."""
        return str(self.meta.get("created_at", ""))[:10]

    # --- map page ---------------------------------------------------------------------------------

    def map_extent(self, scale: int, extent_factor: float,
                   extra_layers: Sequence[QgsMapLayer] = ()) -> QgsRectangle:
        """The extent the map item gets: wide enough for the target scale, for `extent_factor`
        zones, and for everything the page asked to draw on top.

        `MapPage.scale` is a target, not a promise. Drawing a 100 m zone at 1:25000 is fine - the
        zone is simply small on the sheet - but drawing a 2 km zone at 1:2500 would crop it. The
        same holds for the overlays: a page that shows the ground investigations while cutting the
        search radius in half tells the reader nothing was looked for out there.
        """
        minx, miny, maxx, maxy = geometry.bbox(self.zone_ring)
        zone_w, zone_h = maxx - minx, maxy - miny
        for layer in extra_layers:
            extent = layer.extent()
            if extent.isEmpty():
                continue
            minx, miny = min(minx, extent.xMinimum()), min(miny, extent.yMinimum())
            maxx, maxy = max(maxx, extent.xMaximum()), max(maxy, extent.yMaximum())
        ratio = MAP_H / MAP_W
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        width_at_scale = MAP_W / 1000.0 * scale  # metres across the paper width at 1:scale
        width_for_zone = max(zone_w, zone_h / ratio) * max(extent_factor, 1.0)
        width_for_overlays = max(maxx - minx, (maxy - miny) / ratio)
        width = max(width_at_scale, width_for_zone, width_for_overlays)
        height = width * ratio
        return QgsRectangle(cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)

    def _page_overlays(self, page: MapPage) -> List[QgsMapLayer]:
        """The overlays this page asked for, zone excluded - the zone is the ring we start from."""
        extra: List[QgsMapLayer] = []
        if page.show_investigations:
            extra += list(self.overlays.get("investigations", []))
        if page.show_section_line:
            extra += list(self.overlays.get("section", []))
        return extra

    def _map_layers(self, page: MapPage) -> List[QgsMapLayer]:
        """Draw order, topmost first: the zone always, then what the page asked for, then the map."""
        return (list(self.overlays.get("zone", [])) + self._page_overlays(page)
                + list(self.layers_by_map.get(page.map_id, [])))

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
        map_item = QgsLayoutItemMap(self.layout)
        map_item.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
        map_item.setLayers(self._map_layers(page))
        map_item.setFrameEnabled(True)
        self.layout.addLayoutItem(map_item)
        map_item.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        map_item.attemptResize(size_mm(MAP_W, MAP_H))
        map_item.setExtent(self.map_extent(page.scale, page.extent_factor, self._page_overlays(page)))
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
        if page.note:
            self.label(page.note, MARGIN, NOTE_Y, CONTENT_W, 5, index, size=7)
        self.footer(index)
        if page.legend and self.legends:
            self.legend_pages(chapter, page)

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
        index = self.new_page()
        self.header(chapter, page.title, index)
        # StudyResult.figures are forward-slash paths relative to the output directory.
        image = self.out_dir / page.image_path
        width, height = _drawn_size(image, CONTENT_W, CONTENT_H - 12.0)
        picture = QgsLayoutItemPicture(self.layout)
        picture.setPicturePath(str(image))
        picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        self.layout.addLayoutItem(picture)
        picture.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        picture.attemptResize(size_mm(width, height))
        if page.caption:
            self.label(page.caption, MARGIN, CONTENT_TOP + height + 2.0, CONTENT_W, 10, index, size=7)
        self.footer(index)

    def _fit_continuation_frames(self, table: QgsLayoutMultiFrame) -> int:
        """Pull the follow-on frames into the content band; return the last page the table uses.

        QGIS lays every continuation frame of an ExtendToNextPage table over the *whole* sheet,
        header and footer included, so without this the second page of a table starts at the paper
        edge and runs straight through the page number. A shorter frame holds fewer rows and can
        need one more page, so the re-flow repeats until the page count settles.
        """
        collection = self.layout.pageCollection()
        for _ in range(MAX_TABLE_REFLOW):
            before = collection.pageCount()
            for frame in table.frames()[1:]:
                frame.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=frame.page())
                frame.attemptResize(size_mm(CONTENT_W, CONTENT_H))
            table.recalculateFrameSizes()
            if collection.pageCount() == before:
                break
        return max((frame.page() for frame in table.frames()), default=collection.pageCount() - 1)

    def table_page(self, chapter: Chapter, page: TablePage) -> None:
        index = self.new_page()
        self.header(chapter, page.title, index)
        table = QgsLayoutItemTextTable(self.layout)
        self.layout.addMultiFrame(table)
        table.setColumns([QgsLayoutTableColumn(heading) for heading in page.columns])
        table.setContents([[str(cell) for cell in row] for row in page.rows])
        table.setHeaderMode(QgsLayoutTable.HeaderMode.AllFrames)
        # A borehole table easily outgrows one sheet; truncating it silently would lose rows.
        table.setResizeMode(QgsLayoutMultiFrame.ResizeMode.ExtendToNextPage)
        table.setContentTextFormat(_text_format(7))
        table.setHeaderTextFormat(_text_format(7, bold=True))
        frame = QgsLayoutFrame(self.layout, table)
        # Into the layout before it is moved: attemptMove resolves `page` via the page collection.
        self.layout.addLayoutItem(frame)
        frame.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        frame.attemptResize(size_mm(CONTENT_W, CONTENT_H))
        table.addFrame(frame)
        table.recalculateFrameSizes()
        last = self._fit_continuation_frames(table)
        if page.note:
            self.label(page.note, MARGIN, NOTE_Y, CONTENT_W, 5, index, size=7)
        self.footer(index)
        for extra in range(index + 1, last + 1):
            self.header(chapter, f"{page.title} (vervolg)", extra)
            self.footer(extra)

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
        rows = [("Project", self.meta.get("project")),
                ("Projectnummer", self.meta.get("project_number")),
                ("Adres", self.meta.get("address")), ("Gemeente", self.meta.get("municipality")),
                ("Zone", self.meta.get("zone_name")), ("Datum", self._date()),
                ("Auteur", self.meta.get("author")), ("Bedrijf", self.meta.get("company"))]
        cells = "".join(f"<tr><td><b>{key}</b></td><td>{value or '-'}</td></tr>" for key, value in rows)
        self.label(f"<table>{cells}</table>", MARGIN, y + 20, CONTENT_W, 60, index, size=9, html=True)
        chapters = "<br>".join(f"{c.number}. {c.title}" for c in self.report.chapters)
        self.label(f"<b>Inhoud</b><br>{chapters}", MARGIN, y + 85, CONTENT_W, 60, index,
                   size=9, html=True)
        self.label(self.meta.get("disclaimer", ""), MARGIN, 240, CONTENT_W, 30, index,
                   size=7, html=True)
        self.footer(index)

    def build(self) -> QgsPrintLayout:
        self.title_page()
        for chapter in self.report.chapters:
            for page in chapter.pages:
                if isinstance(page, MapPage):
                    self.map_page(chapter, page)
                elif isinstance(page, FigurePage):
                    self.figure_page(chapter, page)
                elif isinstance(page, TablePage):
                    self.table_page(chapter, page)
                else:
                    self.text_page(chapter, page)
        # Without this the data-defined properties - the legend switch above all - are still
        # unevaluated, and the first export silently keeps every page.
        self.layout.refresh()
        return self.layout


def build_layout(project: QgsProject, report: Report, layers_by_map: Dict[str, List[QgsMapLayer]],
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = True,
                 legend_images: Optional[Dict[str, Path]] = None) -> QgsPrintLayout:
    """The whole report as one print layout. See LayoutBuilder for what lands where."""
    return LayoutBuilder(project, report, layers_by_map, overlays, out_dir, zone_ring, meta,
                         legends, legend_images).build()
