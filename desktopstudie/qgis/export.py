"""The products of one study: the report as a PDF, every page as a PNG, and the project file.

Three rules hold for everything here.

*Refresh before you export.* A layout carries data-defined properties - the legend switch above
all - that QGIS evaluates on `refresh()`, not on export. Exporting a freshly built layout without
it silently writes the pages the switch was supposed to drop.

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
from typing import List

from qgis.core import QgsLayoutExporter, QgsPrintLayout, QgsProject

from .compat import enum_name

PAGE_STEM = "pagina"  # QGIS writes pagina.png, pagina_2.png, pagina_3.png, ...
PDF_DPI = 150
PNG_DPI = 72
SUCCESS = QgsLayoutExporter.ExportResult.Success


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


def export_pdf(layout: QgsPrintLayout, path, dpi: int = PDF_DPI) -> Path:
    """Write the whole layout to one PDF and return its path.

    `rasterizeWholeImage` stays off: rasterising the sheet would turn every label and table into
    pixels, and a report nobody can select text in is a report nobody can quote from. Individual
    items that need it (a partly transparent WMS) are rasterised by QGIS on their own.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    layout.refresh()
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = dpi
    settings.rasterizeWholeImage = False
    with _quiet_gdal():
        result = QgsLayoutExporter(layout).exportToPdf(str(path), settings)
    _check(result, "PDF-export", path)
    return path


def export_pages_png(layout: QgsPrintLayout, directory, dpi: int = PNG_DPI) -> List[Path]:
    """Write one PNG per page into `directory` and return them in page order.

    The pages of an earlier run are removed first: a study that got shorter would otherwise hand
    back sheets of the previous one, and nothing downstream can tell the two apart.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob(f"{PAGE_STEM}*.png"):
        stale.unlink()
    layout.refresh()
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = dpi
    first = directory / f"{PAGE_STEM}.png"
    with _quiet_gdal():
        result = QgsLayoutExporter(layout).exportToImage(str(first), settings)
    _check(result, "PNG-export", directory)
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
