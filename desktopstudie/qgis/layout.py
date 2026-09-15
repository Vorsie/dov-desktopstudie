"""Builds one multi-page QgsPrintLayout from the core's Report tree.

The core decides *what* the report says (chapters -> MapPage / FigurePage / TablePage / TextPage);
this module decides only where it lands on the paper. A4 portrait, 15 mm margins, one layout page
per report page, with a title page in front and a separate legend page behind every map that asks
for one.

Two switches govern those legend pages, because "I want them" and "not in this PDF" are different
questions. `build_layout(..., legends=False)` never creates them. When they do exist, the layout
variable `legendas` (Layout > Variables in QGIS) drives a data-defined *exclude from exports* on
each legend page, so the reader can drop them from an export without deleting anything.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Sequence

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils,
    QgsLayoutFrame,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
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
from qgis.PyQt.QtGui import QColor, QFont

from ..core import catalogue, geometry
from ..core.report_content import Chapter, FigurePage, MapPage, Report, TablePage, TextPage
from .compat import point_mm, size_mm

CRS_AUTHID = "EPSG:31370"
LAYOUT_NAME = "DOV Desktopstudie"
PAGE_SIZE = "A4"
MARGIN = 15.0
CONTENT_W = 180.0
MAP_W, MAP_H = 180.0, 200.0
CONTENT_TOP = 30.0
INFO_W = 55.0
INFO_X = 140.0
FOOTER_Y = 285.0
LEGEND_VARIABLE = "legendas"
NORTH_ARROW = Path(__file__).resolve().parents[1] / "resources" / "noordpijl.svg"
# Arial is the house face, but the PDF is also produced on the Linux CI images and on machines that
# do not have it. Naming the substitutes keeps the metrics predictable instead of leaving the
# choice to whatever fontconfig happens to pick first.
FONT_FAMILIES = ["Arial", "Liberation Sans", "DejaVu Sans"]
BOX_BACKGROUND = QColor(255, 255, 255)  # opaque: an info box sits on top of the map
SCALE_BAR_STYLE = "Single Box"
SCALE_BAR_SEGMENTS = 2
SCALE_BAR_STEP = 50.0  # the segment length is rounded to a multiple of this, and never below it


def _font(size: float, bold: bool = False) -> QFont:
    """A layout font in the house face, with the fallbacks that keep a Linux export readable."""
    font = QFont(FONT_FAMILIES[0], int(size))
    if hasattr(font, "setFamilies"):  # Qt >= 5.13, so every supported QGIS - but cheap to ask
        font.setFamilies(FONT_FAMILIES)
    font.setBold(bold)
    return font


def _text_format(size: float, bold: bool = False) -> QgsTextFormat:
    """The text format for a label or a table.

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
    """A round scale-bar segment: about a twentieth of the map width, on a 50 m grid."""
    return max(SCALE_BAR_STEP, round(scale / 20.0 / SCALE_BAR_STEP) * SCALE_BAR_STEP)


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


class LayoutBuilder:
    """One report -> one layout. Build it once; `build()` is not idempotent."""

    def __init__(self, project: QgsProject, report: Report, layers_by_map: Dict[str, List[QgsMapLayer]],
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = True):
        """layers_by_map: map_id -> [QgsMapLayer, ...] to draw (WMS + basemap); overlays: keys
        'zone', 'investigations', 'section' -> the memory layers a page may ask to draw on top."""
        self.project, self.report = project, report
        self.layers_by_map, self.overlays = layers_by_map, overlays
        self.out_dir, self.zone_ring, self.meta = Path(out_dir), list(zone_ring), meta
        self.legends = legends
        self.layout = QgsPrintLayout(project)
        self.layout.initializeDefaults()  # this already gives page 0; new_page() adds the rest
        self.layout.setName(LAYOUT_NAME)
        QgsExpressionContextUtils.setLayoutVariable(self.layout, LEGEND_VARIABLE, 1 if legends else 0)
        self.page_index = -1

    # --- page furniture ---------------------------------------------------------------------------

    def new_page(self) -> int:
        if self.page_index < 0:
            # initializeDefaults() laid down page 0 in A4 *landscape*. The report is portrait from
            # cover to cover, and on a landscape first page everything below 210 mm - the table of
            # contents, the disclaimer - simply falls off the paper.
            self.layout.pageCollection().page(0).setPageSize(
                PAGE_SIZE, QgsLayoutItemPage.Orientation.Portrait)
        else:
            page = QgsLayoutItemPage(self.layout)
            page.setPageSize(PAGE_SIZE, QgsLayoutItemPage.Orientation.Portrait)
            self.layout.pageCollection().addPage(page)
        self.page_index += 1
        return self.page_index

    def label(self, text: str, x: float, y: float, w: float, h: float, size: float = 9,
              html: bool = False, frame: bool = False, bold: bool = False) -> QgsLayoutItemLabel:
        item = QgsLayoutItemLabel(self.layout)
        if html:
            item.setMode(QgsLayoutItemLabel.Mode.ModeHtml)
        item.setText(text)
        item.setTextFormat(_text_format(size, bold))
        item.setFrameEnabled(frame)
        # A framed label is an info box, and an info box sits on top of the map: without an opaque
        # background its text reads over facades and street names exactly where the scale and the
        # attribution are printed.
        item.setBackgroundEnabled(frame)
        if frame:
            item.setBackgroundColor(BOX_BACKGROUND)
        self.layout.addLayoutItem(item)
        item.attemptMove(point_mm(x, y), page=self.page_index)
        item.attemptResize(size_mm(w, h))
        return item

    def header(self, chapter: Chapter, title: str) -> None:
        self.label(f"{chapter.number}. {chapter.title}", MARGIN, 10, CONTENT_W, 8, size=13, bold=True)
        self.label(title, MARGIN, 18, CONTENT_W, 7, size=10)

    def footer(self) -> None:
        company = self.meta.get("company", "")
        project = self.meta.get("project", "")
        text = f"{company} - {project} - pagina [% @layout_page %] / [% @layout_numpages %]"
        self.label(text, MARGIN, FOOTER_Y, CONTENT_W, 6, size=7)

    # --- map page ---------------------------------------------------------------------------------

    def map_extent(self, scale: int, extent_factor: float) -> QgsRectangle:
        """The extent the map item gets: the wider of the target scale and `extent_factor` zones.

        `MapPage.scale` is a target, not a promise. Drawing a 100 m zone at 1:25000 is fine - the
        zone is simply small on the sheet - but drawing a 2 km zone at 1:2500 would crop it, so the
        zone wins whenever it needs more room than the target scale gives.
        """
        minx, miny, maxx, maxy = geometry.bbox(self.zone_ring)
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        ratio = MAP_H / MAP_W
        width_at_scale = MAP_W / 1000.0 * scale  # metres across the paper width at 1:scale
        width_for_zone = max(maxx - minx, (maxy - miny) / ratio) * max(extent_factor, 1.0)
        width = max(width_at_scale, width_for_zone)
        height = width * ratio
        return QgsRectangle(cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)

    def _map_layers(self, page: MapPage) -> List[QgsMapLayer]:
        """Draw order, topmost first: the zone always, then what the page asked for, then the map."""
        map_layers = list(self.layers_by_map.get(page.map_id, []))
        if page.show_investigations:
            map_layers = list(self.overlays.get("investigations", [])) + map_layers
        if page.show_section_line:
            map_layers = list(self.overlays.get("section", [])) + map_layers
        return list(self.overlays.get("zone", [])) + map_layers

    def _scale_bar(self, map_item: QgsLayoutItemMap, real_scale: int) -> QgsLayoutItemScaleBar:
        bar = QgsLayoutItemScaleBar(self.layout)
        self.layout.addLayoutItem(bar)
        bar.setStyle(SCALE_BAR_STYLE)
        bar.setLinkedMap(map_item)
        # applyDefaultSize() derives its own unit label and segment length from the map, so it goes
        # first: called after the explicit settings below, it would silently overwrite them.
        bar.applyDefaultSize(Qgis.DistanceUnit.Meters)
        bar.setUnits(Qgis.DistanceUnit.Meters)
        bar.setUnitLabel("m")
        bar.setNumberOfSegments(SCALE_BAR_SEGMENTS)
        bar.setNumberOfSegmentsLeft(0)
        bar.setUnitsPerSegment(_segment_length(real_scale))  # refreshes and re-fits the bar itself
        bar.attemptMove(point_mm(MARGIN, 232), page=self.page_index)
        return bar

    def map_page(self, chapter: Chapter, page: MapPage) -> None:
        self.new_page()
        self.header(chapter, page.title)
        entry = catalogue.by_id(page.map_id)
        map_item = QgsLayoutItemMap(self.layout)
        map_item.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
        map_item.setLayers(self._map_layers(page))
        map_item.setFrameEnabled(True)
        self.layout.addLayoutItem(map_item)
        map_item.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=self.page_index)
        map_item.attemptResize(size_mm(MAP_W, MAP_H))
        map_item.setExtent(self.map_extent(page.scale, page.extent_factor))
        real_scale = int(round(map_item.scale()))
        # What the reader needs to judge the map: which map, of which project, at which scale...
        self.label(f"<b>{self.meta.get('project', '')}</b><br>{self.meta.get('created_at', '')[:10]}"
                   f"<br>{entry.title}<br>schaal 1:{_thousands(real_scale)}",
                   INFO_X, 46, INFO_W, 22, size=7, html=True, frame=True)
        # ... and where it came from, on the same sheet, so a printed page stays attributable.
        self.label(f"{entry.attribution}<br>{entry.licence}<br>opgehaald {dt.date.today().isoformat()}",
                   INFO_X, 210, INFO_W, 18, size=6, html=True, frame=True)
        arrow = QgsLayoutItemPicture(self.layout)
        arrow.setPicturePath(str(NORTH_ARROW))
        arrow.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        self.layout.addLayoutItem(arrow)
        arrow.attemptMove(point_mm(183, 32), page=self.page_index)
        arrow.attemptResize(size_mm(12, 12))
        self._scale_bar(map_item, real_scale)
        if page.note:
            self.label(page.note, MARGIN, 24, CONTENT_W, 5, size=7)
        self.footer()
        if page.legend and self.legends and self.layers_by_map.get(page.map_id):
            self.legend_page(chapter, page, map_item)

    def legend_page(self, chapter: Chapter, page: MapPage, map_item: QgsLayoutItemMap) -> None:
        """The legend of the preceding map page, on its own sheet.

        Not on the map page itself: a DOV legend runs to dozens of classes, and a map squeezed
        around one is unreadable. The page is excluded from exports when `@legendas = 0`, so
        turning the legends off costs the reader one variable instead of a delete-and-rebuild.
        """
        index = self.new_page()
        page_item = self.layout.pageCollection().page(index)
        page_item.setId(f"legenda-{page.map_id}")
        page_item.dataDefinedProperties().setProperty(
            QgsLayoutObject.DataDefinedProperty.ExcludeFromExports,
            QgsProperty.fromExpression(f"@{LEGEND_VARIABLE} = 0"))
        self.header(chapter, f"Legenda - {page.title}")
        legend = QgsLayoutItemLegend(self.layout)
        legend.setLinkedMap(map_item)
        # A hand-built model: the automatic one mirrors the whole project tree, which would put
        # every other study layer on this page. setAutoUpdateModel(False) comes before touching it.
        legend.setAutoUpdateModel(False)
        legend.setTitle("")
        root = legend.model().rootGroup()
        root.clear()
        for layer in self.layers_by_map.get(page.map_id, []):
            root.addLayer(layer)
        legend.setResizeToContents(True)
        self.layout.addLayoutItem(legend)
        legend.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=index)
        legend.attemptResize(size_mm(CONTENT_W, 245))
        self.footer()

    # --- figure, table and text pages --------------------------------------------------------------

    def figure_page(self, chapter: Chapter, page: FigurePage) -> None:
        self.new_page()
        self.header(chapter, page.title)
        picture = QgsLayoutItemPicture(self.layout)
        # StudyResult.figures are forward-slash paths relative to the output directory.
        picture.setPicturePath(str(self.out_dir / page.image_path))
        picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        self.layout.addLayoutItem(picture)
        picture.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=self.page_index)
        picture.attemptResize(size_mm(CONTENT_W, 235))
        if page.caption:
            self.label(page.caption, MARGIN, 268, CONTENT_W, 12, size=7)
        self.footer()

    def table_page(self, chapter: Chapter, page: TablePage) -> None:
        self.new_page()
        self.header(chapter, page.title)
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
        frame.attemptMove(point_mm(MARGIN, CONTENT_TOP), page=self.page_index)
        frame.attemptResize(size_mm(CONTENT_W, 245))
        table.addFrame(frame)
        if page.note:
            self.label(page.note, MARGIN, 24, CONTENT_W, 5, size=7)
        self.footer()

    def text_page(self, chapter: Chapter, page: TextPage) -> None:
        self.new_page()
        self.header(chapter, page.title)
        self.label(page.html, MARGIN, CONTENT_TOP, CONTENT_W, 245, size=9, html=True)
        self.footer()

    # --- title page --------------------------------------------------------------------------------

    def title_page(self) -> None:
        self.new_page()
        logo = self.meta.get("logo_path")
        y = 20.0
        if logo and Path(logo).exists():
            picture = QgsLayoutItemPicture(self.layout)
            picture.setPicturePath(str(logo))
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            self.layout.addLayoutItem(picture)
            picture.attemptMove(point_mm(MARGIN, y), page=self.page_index)
            picture.attemptResize(size_mm(60, 30))
            y += 35
        self.label(self.report.title, MARGIN, y, CONTENT_W, 14, size=20, bold=True)
        rows = [("Project", self.meta.get("project")), ("Projectnummer", self.meta.get("project_number")),
                ("Adres", self.meta.get("address")), ("Gemeente", self.meta.get("municipality")),
                ("Zone", self.meta.get("zone_name")), ("Datum", self.meta.get("created_at", "")[:10]),
                ("Auteur", self.meta.get("author")), ("Bedrijf", self.meta.get("company"))]
        cells = "".join(f"<tr><td><b>{key}</b></td><td>{value or '-'}</td></tr>" for key, value in rows)
        self.label(f"<table>{cells}</table>", MARGIN, y + 20, CONTENT_W, 60, size=9, html=True)
        chapters = "<br>".join(f"{c.number}. {c.title}" for c in self.report.chapters)
        self.label(f"<b>Inhoud</b><br>{chapters}", MARGIN, y + 85, CONTENT_W, 60, size=9, html=True)
        self.label(self.meta.get("disclaimer", ""), MARGIN, 240, CONTENT_W, 30, size=7, html=True)

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
        return self.layout


def build_layout(project: QgsProject, report: Report, layers_by_map: Dict[str, List[QgsMapLayer]],
                 overlays: Dict[str, List[QgsMapLayer]], out_dir, zone_ring: Sequence, meta: dict,
                 legends: bool = True) -> QgsPrintLayout:
    """The whole report as one print layout. See LayoutBuilder for what lands where."""
    return LayoutBuilder(project, report, layers_by_map, overlays, out_dir, zone_ring, meta, legends).build()
