"""QGIS layers for one study: WMS/WCS layers from the catalogue and memory layers from the model.

Nothing here decides *what* a study contains - the catalogue and the core model do. This module
only turns those into QgsMapLayers, gives them the house style and writes them to a GeoPackage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple, Union

from qgis.core import (
    Qgis,
    QgsCoordinateTransformContext,
    QgsDataSourceUri,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from ..core.catalogue import MapEntry
from ..core.model import Borehole, Cpt, GwFilter, StudyZone

CRS_AUTHID = "EPSG:31370"
# The WCS coverage format name, not a WMS mime type: DescribeCoverage on the DHMV service offers
# GeoTIFF / HDF / NetCDF, and "image/tiff" yields an invalid layer ("Cannot get test dataset").
WCS_FORMAT = "GeoTIFF"
WCS_VERSION = "1.0.0"
# Segments per quarter circle when buffering the zone into the search area: smooth enough on
# paper, and cheap enough that a wide radius does not turn the GeoPackage into a vertex dump.
BUFFER_SEGMENTS = 12
Investigation = Union[Cpt, Borehole, GwFilter]
POINT_STYLE = {  # kind -> (colour, marker)
    "sondering": ("#1f4e79", "circle"),
    "boring": ("#c00000", "square"),
    "peilput": ("#2e75b6", "triangle"),
}
POINT_NAMES = {"sondering": "Sonderingen", "boring": "Boringen", "peilput": "Peilputten"}
POINT_FIELDS = [("nummer", "string"), ("afstand_m", "double"), ("diepte_m", "double"), ("datum", "string"),
                ("methode", "string"), ("z_mtaw", "double"), ("url", "string")]
DEPTH_ALIAS = "diepte / filterbasis (m)"
SECTION_LABEL = "A-A'"
SEARCH_AREA_NAME = "Zoekstraal"
LOCKED_HINT = "sluit de lagen van een vorige studie in QGIS en probeer opnieuw"


# --- raster layers from the catalogue ------------------------------------------------------------

def wms_layer(entry: MapEntry) -> QgsRasterLayer:
    """A WMS layer for one catalogue entry. Validity needs a live GetCapabilities, so an offline
    caller gets an invalid layer rather than an exception - the pipeline reports that per map."""
    uri = QgsDataSourceUri()
    uri.setParam("url", entry.wms_url)
    uri.setParam("layers", entry.wms_layer)
    uri.setParam("styles", entry.wms_style)  # "" = the layer default
    uri.setParam("format", entry.image_format)
    uri.setParam("crs", CRS_AUTHID)
    uri.setParam("dpiMode", "7")
    uri.setParam("contextualWMSLegend", "0")
    layer = QgsRasterLayer(uri.encodedUri().data().decode("utf-8"), entry.title, "wms")
    if layer.isValid():
        layer.setOpacity(entry.opacity)
    return layer


def wcs_layer(url: str, coverage: str, name: str) -> QgsRasterLayer:
    """A WCS coverage (the DHMV DTM); `dem.relief_of_zone` samples it."""
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("identifier", coverage)
    uri.setParam("crs", CRS_AUTHID)
    uri.setParam("format", WCS_FORMAT)
    uri.setParam("version", WCS_VERSION)
    return QgsRasterLayer(uri.encodedUri().data().decode("utf-8"), name, "wcs")


# --- memory layers from the model ----------------------------------------------------------------

def _memory(geometry_type: str, name: str, fields: Sequence[Tuple[str, str]]) -> QgsVectorLayer:
    spec = "&".join([f"{geometry_type}?crs={CRS_AUTHID}"] + [f"field={field}:{kind}" for field, kind in fields])
    return QgsVectorLayer(spec, name, "memory")


def _add(layer: QgsVectorLayer, features: Sequence[QgsFeature]) -> None:
    """Add features to a memory layer, or say so. The provider returns False on a field mismatch
    and QGIS logs nothing the user sees; an empty layer three pages later is not a diagnosis."""
    if features and not layer.dataProvider().addFeatures(list(features)):
        raise RuntimeError(f"Kon {len(features)} object(en) niet toevoegen aan de laag {layer.name()}")
    layer.updateExtents()


def _zone_polygon(zone: StudyZone) -> QgsGeometry:
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in zone.ring]])


def zone_layer(zone: StudyZone) -> QgsVectorLayer:
    """The study zone itself: one polygon, red outline, lightly filled."""
    layer = _memory("Polygon", "Onderzoekszone", [("naam", "string")])
    feature = QgsFeature(layer.fields())
    feature.setGeometry(_zone_polygon(zone))
    feature["naam"] = zone.name
    _add(layer, [feature])
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "255,0,0,30", "outline_color": "#ff0000", "outline_width": "0.8"}))
    return layer


def circle_layer(zone: StudyZone) -> QgsVectorLayer:
    """The search area: the DWITHIN region the core searched, i.e. the zone polygon buffered by
    `zone.radius_m`. Not a circle around the centroid - for anything but a round zone that both
    misses ground near a far corner and claims ground the core never queried."""
    layer = _memory("Polygon", SEARCH_AREA_NAME, [("straal_m", "double")])
    feature = QgsFeature(layer.fields())
    feature.setGeometry(_zone_polygon(zone).buffer(zone.radius_m, BUFFER_SEGMENTS))
    feature["straal_m"] = zone.radius_m
    _add(layer, [feature])
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ff0000", "outline_style": "dash", "outline_width": "0.5"}))
    return layer


def line_layer(zone: StudyZone) -> QgsVectorLayer:
    """The section line. Empty but valid when the study has no section line yet, so a map page
    can always add it."""
    layer = _memory("LineString", "Doorsnedelijn", [("naam", "string")])
    features = []
    if zone.section_line:
        start, end = zone.section_line
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*start), QgsPointXY(*end)]))
        feature["naam"] = SECTION_LABEL
        features.append(feature)
    _add(layer, features)
    layer.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#000000", "width": "0.6"}))
    return layer


def points_layer(kind: str, items: Iterable[Investigation]) -> QgsVectorLayer:
    """One labelled point layer per investigation kind ("sondering" / "boring" / "peilput").
    A peilput has no single number and no total depth, so it falls back to gw_id/filter_no and
    to the filter base - hence the alias on diepte_m."""
    layer = _memory("Point", POINT_NAMES[kind], POINT_FIELDS)
    layer.setFieldAlias(layer.fields().indexOf("diepte_m"), DEPTH_ALIAS)
    features = []
    for item in items:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(item.x, item.y)))
        gw_id, filter_no = getattr(item, "gw_id", "?"), getattr(item, "filter_no", "")
        number = getattr(item, "number", None) or f"{gw_id}/{filter_no}"
        depth = getattr(item, "depth_m", None) if hasattr(item, "depth_m") else getattr(item, "filter_base_m", None)
        feature.setAttributes([number, float(item.distance_m), depth, getattr(item, "date", None),
                               getattr(item, "method", None), getattr(item, "z_mtaw", None), item.url])
        features.append(feature)
    _add(layer, features)
    colour, marker = POINT_STYLE[kind]
    symbol = QgsMarkerSymbol.createSimple(
        {"name": marker, "color": colour, "size": "2.6", "outline_color": "white", "outline_width": "0.3"})
    # Pin the units: without them a symbol follows whatever the host project happens to use, and
    # the same study prints differently on another machine.
    symbol.setSizeUnit(Qgis.RenderUnit.Millimeters)
    layer.renderer().setSymbol(symbol)
    settings = QgsPalLayerSettings()
    settings.fieldName = "nummer"
    text_format = QgsTextFormat()
    text_format.setSize(7)
    text_format.setSizeUnit(Qgis.RenderUnit.Points)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    return layer


# --- project tree and GeoPackage -----------------------------------------------------------------

def add_group(project: QgsProject, title: str, group_layers: Sequence[QgsMapLayer],
              visible: bool = True) -> QgsLayerTreeGroup:
    """Add the layers to the project under one group, in the given order. They are registered
    without a tree node (`addMapLayer(layer, False)`) so they appear inside the group only."""
    group = project.layerTreeRoot().addGroup(title)
    for layer in group_layers:
        project.addMapLayer(layer, False)
        group.addLayer(layer).setItemVisibilityChecked(visible)
    return group


def gpkg_failure_message(layer_name: str, message: str) -> str:
    """The message for a failed GeoPackage write. A locked or already-present layer is the one
    failure the user can fix themselves - it means the previous study is still open in QGIS - so
    that case gets told what to do instead of only what went wrong."""
    text = f"GeoPackage schrijven mislukt voor {layer_name}: {message}"
    lowered = message.lower()
    if "locked" in lowered or "already exists" in lowered or "being used" in lowered:
        return f"{text} - {LOCKED_HINT}"
    return text


def _write_gpkg_layer(layer: QgsVectorLayer, path: Path, first: bool,
                      transform_context: QgsCoordinateTransformContext) -> None:
    """Write one layer into the GeoPackage; `first` overwrites the file, the rest add a layer.

    `writeAsVectorFormatV3` returns a 4-tuple whose order the generated PyQGIS docstring gets
    wrong: verified on 3.40.15 it is (error, errorMessage, newFilename, newLayer), while the
    docstring lists the message last. Only element 0 is fixed across versions, so the message is
    read as the first non-empty string after it - on a failure the filename and layer slots come
    back empty, so that lands on the real message under either ordering.
    """
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer.name()
    options.fileEncoding = "UTF-8"
    options.actionOnExistingFile = (QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile if first
                                    else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), transform_context, options)
    if result[0] != QgsVectorFileWriter.WriterError.NoError:
        message = next((str(part) for part in result[1:] if part), "onbekende fout")
        raise RuntimeError(gpkg_failure_message(layer.name(), message))


def write_geopackage(gpkg_layers: Sequence[QgsVectorLayer], path: Path,
                     transform_context: Optional[QgsCoordinateTransformContext] = None) -> None:
    """Write every memory layer into one GeoPackage, the first one creating the file.

    Everything is already in EPSG:31370, so the default transform context is an empty one; the
    caller passes `project.transformContext()` when the project carries datum settings. Taking it
    as a parameter keeps this callable from a QgsTask, where `QgsProject.instance()` is the wrong
    project (or none at all).
    """
    if not gpkg_layers:
        raise ValueError("Geen lagen om naar het GeoPackage te schrijven")
    if transform_context is None:
        transform_context = QgsCoordinateTransformContext()
    path = Path(path)
    for index, layer in enumerate(gpkg_layers):
        _write_gpkg_layer(layer, path, index == 0, transform_context)
