"""The products of one study: the report as a PDF, every page as a PNG, and the project file.

Four rules hold for everything here.

*Evaluate the data-defined properties before you export.* A layout carries them - the legend
switch above all - and QGIS evaluates them on a refresh, not on export. Exporting a freshly built
layout without one silently writes the pages the switch was supposed to drop. It is a targeted
refresh (`refresh_data_defined`), not `QgsLayout.refresh()`: the full one re-measures every label
and costs seconds per call on a report of a hundred sheets.

*Never hand the exporter the whole report in one go.* Inside one export call every sheet costs
about 7 us times the number of items in the layout times the number of sheets already exported:
a quadratic term that has nothing to do with what is on the sheets. Measured 2026-09-16 on a
synthetic layout of 115 sheets of six plain labels: 38 s in one call, 10 s when the same layout
went through the iterator interface in four runs, 508 s for 230 sheets in one call. The Gent report
(115 sheets, ~800 items) paid 65 of its 95 s to that term. So `export_pdf` feeds the one layout to
`QgsLayoutExporter` a few sheets at a time (`_PageRuns`) and `export_pages_png` exports every sheet
with a fresh exporter; both produce exactly the sheets a single call would.

*A failed export is never a returned path.* `QgsLayoutExporter` reports a result code instead of
raising, and a caller that ignores it hands the user a report that is not there. Every failure
becomes a RuntimeError naming the result ("FileError", not "3").

*GDAL's chatter about PNG update access is not an error.* After writing the images QGIS reopens
them through GDAL to attach the world file / georeference; the PNG driver has no update mode and
says so on stderr for every single page ("The PNG driver does not support update access"). The
pages themselves are written correctly - the georeference is an extra we never asked for - so the
GDAL error handler is quietened for the duration of an export. A real failure still comes back in
the ExportResult, which is checked either way.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import List, Sequence, Set

from qgis.core import (
    Qgis,
    QgsAbstractLayoutIterator,
    QgsLayout,
    QgsLayoutExporter,
    QgsLayoutItem,
    QgsLayoutObject,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
)

from .compat import enum_name

PAGE_STEM = "pagina"  # QGIS writes pagina.png, pagina_2.png, pagina_3.png, ...
PDF_DPI = 150
PNG_DPI = 72
SUCCESS = QgsLayoutExporter.ExportResult.Success
# Sheets per run of the PDF exporter. The quadratic term grows with the square of this number, so
# small is good; below ten the fixed cost of starting a run (a fresh exporter, the printer's page
# setup) starts to show. Ten keeps the term under a second for a report of a hundred sheets.
PDF_PAGES_PER_RUN = 10
EXCLUDE = QgsLayoutObject.DataDefinedProperty.ExcludeFromExports


@contextmanager
def _quiet_gdal():
    """Silence GDAL's own stderr for the duration of an export (see the module docstring).

    The bindings ship with QGIS, but a stripped install without them must not take the export
    down with it - then the message simply stays visible.
    """
    try:
        from osgeo import gdal
    except ImportError:  # pragma: no cover - the QGIS installs we support all carry GDAL
        yield
        return
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        yield
    finally:
        gdal.PopErrorHandler()


def refresh_data_defined(layout: QgsLayout) -> int:
    """Evaluate every data-defined property in `layout`; returns how many objects carried one.

    This is what an export needs from a refresh, and all it needs. `QgsLayout.refresh()` does far
    more: it re-runs every label's expression context (a distance area, an ellipsoid lookup) at
    about 4 ms a label - 451 labels in the Gent report, 3,5 s a call on a quiet machine and four
    times that on a busy one, and it used to run twice per study. The legend switch on the pages
    is the one data-defined property this layout sets; anything added later is caught the same
    way, because the test is "carries a property", not "is a page".
    """
    objects = [item for item in layout.items() if isinstance(item, QgsLayoutItem)]
    objects += list(layout.multiFrames())
    refreshed = 0
    for obj in objects:
        if obj.dataDefinedProperties().hasActiveProperties():
            obj.refresh()
            refreshed += 1
    return refreshed


@contextmanager
def _frozen_exclusions(layout: QgsLayout):
    """Every page's exclusion as a plain flag for the duration, its data-defined rule lifted.

    A flag set on a page that carries a data-defined exclusion does not hold: QGIS re-evaluates
    the rule and the rule wins. The runs steer by the flag, so for the export each rule is
    evaluated once, its outcome written into the flag, and the rule put back afterwards.

    Yields the indices of the pages the export holds, in page order.
    """
    pages = layout.pageCollection()
    lifted = []
    for index in range(pages.pageCount()):
        page = pages.page(index)
        # A copy, made before the rule is lifted: `property()` hands back a reference into the
        # collection's own storage, and `setProperty` below overwrites exactly that storage.
        rule = QgsProperty(page.dataDefinedProperties().property(EXCLUDE))
        if not rule.isActive():
            continue
        # The rule's verdict, evaluated here: from Python `excludeFromExports()` only ever reads
        # the plain flag, whatever the rule says (checked on 3.40.15 with the legend switch at 0).
        excluded, _ok = rule.valueAsBool(page.createExpressionContext(), page.excludeFromExports())
        lifted.append((page, rule, page.excludeFromExports()))
        page.dataDefinedProperties().setProperty(EXCLUDE, QgsProperty())
        page.setExcludeFromExports(bool(excluded))
    try:
        yield [index for index in range(pages.pageCount()) if not pages.page(index).excludeFromExports()]
    finally:
        for page, rule, flag in lifted:
            page.dataDefinedProperties().setProperty(EXCLUDE, rule)
            page.setExcludeFromExports(flag)  # re-evaluates the property, rule included


class _PageRuns(QgsAbstractLayoutIterator):
    """The one layout, handed to the exporter a few pages at a time (see the module docstring).

    QGIS built this interface for atlases and reports, where every iteration is another layout;
    here every iteration is the same layout with the flags set so that only this run's pages are
    exported. The pages the export holds at all (`exported`) are flagged back in at the end, so
    the layout leaves the export as it entered it.
    """

    def __init__(self, layout: QgsLayout, exported: Sequence[int], pages_per_run: int):
        super().__init__()
        self._layout = layout
        self._exported = set(exported)
        self._runs = [set(exported[start:start + pages_per_run])
                      for start in range(0, len(exported), pages_per_run)]
        self._shown: Set[int] = set(exported)
        self._index = -1

    def layout(self):
        return self._layout

    def count(self) -> int:
        return len(self._runs)

    def beginRender(self) -> bool:
        return True

    def endRender(self) -> bool:
        self._show(self._exported)
        return True

    def filePath(self, base_path, extension) -> str:
        return base_path

    def next(self) -> bool:
        self._index += 1
        if self._index >= len(self._runs):
            return False
        self._show(self._runs[self._index])
        return True

    def _show(self, wanted: Set[int]) -> None:
        pages = self._layout.pageCollection()
        for index in self._shown - wanted:
            pages.page(index).setExcludeFromExports(True)
        for index in wanted - self._shown:
            pages.page(index).setExcludeFromExports(False)
        self._shown = set(wanted)


def _check(result, what: str, path: Path) -> None:
    if result != SUCCESS:
        raise RuntimeError(f"{what} mislukt ({enum_name(QgsLayoutExporter, result)}): {path}")


def _page_number(path: Path) -> int:
    """The page a written file belongs to: `pagina.png` is 1, `pagina_7.png` is 7.

    Sorting on the name alone puts pagina_10 before pagina_2, which turns a 60-page report into a
    shuffled stack the moment somebody reads the list as page order.
    """
    _, _, suffix = path.stem.partition("_")
    return int(suffix) if suffix.isdigit() else 1


def export_pdf(layout: QgsPrintLayout, path, dpi: int = PDF_DPI,
               pages_per_run: int = PDF_PAGES_PER_RUN) -> Path:
    """Write the whole layout to one PDF and return its path.

    `rasterizeWholeImage` stays off: rasterising the sheet would turn every label and table into
    pixels, and a report nobody can select text in is a report nobody can quote from. Individual
    items that need it (a partly transparent WMS) are rasterised by QGIS on their own.

    The same reason puts `textRenderFormat` on AlwaysText. The exporter's own default is
    AlwaysOutlines, which turns every glyph into a path: nothing to select, nothing to search, and
    a Gent report of 34 MB where text objects make it 13,5 MB (measured 2026-09-16, 115 sheets).

    The sheets go to the exporter `pages_per_run` at a time, through the iterator interface, into
    the one file - see the module docstring for the quadratic cost this sidesteps.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    refresh_data_defined(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = dpi
    settings.rasterizeWholeImage = False
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    with _frozen_exclusions(layout) as exported:
        if not exported:
            raise RuntimeError(f"PDF-export mislukt: geen enkel blad om te exporteren: {path}")
        runs = _PageRuns(layout, exported, max(1, pages_per_run))
        with _quiet_gdal():
            result, _error = QgsLayoutExporter.exportToPdf(runs, str(path), settings)
    _check(result, "PDF-export", path)
    return path


def export_pages_png(layout: QgsPrintLayout, directory, dpi: int = PNG_DPI) -> List[Path]:
    """Write one PNG per page into `directory` and return them in page order.

    The pages of an earlier run are removed first: a study that got shorter would otherwise hand
    back sheets of the previous one, and nothing downstream can tell the two apart.

    Every page gets its own exporter (`settings.pages`), for the same reason the PDF goes out in
    runs; QGIS names the file after the page index either way, so the names do not change.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob(f"{PAGE_STEM}*.png"):
        stale.unlink()
    refresh_data_defined(layout)
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = dpi
    first = directory / f"{PAGE_STEM}.png"
    with _frozen_exclusions(layout) as exported, _quiet_gdal():
        for index in exported:
            settings.pages = [index]
            _check(QgsLayoutExporter(layout).exportToImage(str(first), settings), "PNG-export", directory)
    return sorted(directory.glob(f"{PAGE_STEM}*.png"), key=_page_number)


def write_project(project: QgsProject, path) -> Path:
    """Write `project` to `path` (a .qgz) and return it.

    For the standalone deliverable the pipeline passes a FRESH QgsProject built from the
    GeoPackage and the WMS entries, never the user's open project - that one keeps its own file
    and its own name, and writing it here would move it into the study folder behind the user's
    back.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not project.write(str(path)):
        raise RuntimeError(f"Project schrijven mislukt: {path} ({project.error()})")
    return path
