"""QGIS layers for one study: WMS/WCS layers from the catalogue and memory layers from the model.

Nothing here decides *what* a study contains - the catalogue and the core model do. This module
only turns those into QgsMapLayers, gives them the house style and writes them to a GeoPackage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence, Tuple, Union

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsDataSourceUri,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLineSymbol,
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
Investigation = Union[Cpt, Borehole, GwFilter]
POINT_STYLE = {  # kind -> (colour, marker)
    "sondering": ("#1f4e79", "circle"),
    "boring": ("#c00000", "square"),
    "peilput": ("#2e75b6", "triangle"),
}
POINT_NAMES = {"sondering": "Sonderingen", "boring": "Boringen", "peilput": "Peilputten"}
POINT_FIELDS = [("nummer", "string"), ("afstand_m", "double"), ("diepte_m", "double"), ("datum", "string"),
                ("methode", "string"), ("z_mtaw", "double"), ("url", "string")]
SECTION_LABEL = "A-A'"


# --- raster layers from the catalogue ------------------------------------------------------------

def wms_layer(entry: MapEntry) -> QgsRasterLayer:
    """A WMS layer for one catalogue entry. Validity needs a live GetCapabilities, so an offline
    caller gets an invalid layer rather than an exception - the pipeline reports that per map."""
    uri = QgsDataSourceUri()
    uri.setParam("url", entry.wms_url)
    uri.setParam("layers", entry.wms_layer)
    uri.setParam("styles", "")
    uri.setParam("format", entry.image_format)
    uri.setParam("crs", CRS_AUTHID)
    uri.setParam("dpiMode", "7")
    uri.setParam("contextualWMSLegend", "0")
    layer = QgsRasterLayer(str(uri.encodedUri(), "utf-8"), entry.title, "wms")
    if layer.isValid():
        layer.setOpacity(entry.opacity)
    return layer


def wcs_layer(url: str, coverage: str, name: str) -> QgsRasterLayer:
    """A WCS coverage (the DHMV DTM); `dem.relief_of_zone` samples it."""
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("identifier", coverage)
    uri.setParam("crs", CRS_AUTHID)
    uri.setParam("format", "image/tiff")
    return QgsRasterLayer(str(uri.encodedUri(), "utf-8"), name, "wcs")


# --- memory layers from the model ----------------------------------------------------------------

def _memory(geometry_type: str, name: str, fields: Sequence[Tuple[str, str]]) -> QgsVectorLayer:
    spec = "&".join([f"{geometry_type}?crs={CRS_AUTHID}"] + [f"field={field}:{kind}" for field, kind in fields])
    return QgsVectorLayer(spec, name, "memory")


def zone_layer(zone: StudyZone) -> QgsVectorLayer:
    """The study zone itself: one polygon, red outline, lightly filled."""
    layer = _memory("Polygon", "Onderzoekszone", [("naam", "string")])
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in zone.ring]]))
    feature["naam"] = zone.name
    layer.dataProvider().addFeatures([feature])
    layer.updateExtents()
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "255,0,0,30", "outline_color": "#ff0000", "outline_width": "0.8"}))
    return layer


def circle_layer(zone: StudyZone) -> QgsVectorLayer:
    """The search circle: `zone.radius_m` around the zone, measured from its outer edge so the
    circle always encloses the zone (the core searches from the zone, not from its centroid)."""
    from ..core import geometry as g

    layer = _memory("Polygon", f"Straal {zone.radius_m:.0f} m", [("straal_m", "double")])
    cx, cy = zone.centroid
    _, _, maxx, maxy = g.bbox(zone.ring)
    ring = g.buffer_point(cx, cy, zone.radius_m + max(maxx - cx, maxy - cy), n=96)
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]]))
    feature["straal_m"] = zone.radius_m
    layer.dataProvider().addFeatures([feature])
    layer.updateExtents()
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ff0000", "outline_style": "dash", "outline_width": "0.5"}))
    return layer


def line_layer(zone: StudyZone) -> QgsVectorLayer:
    """The section line. Empty but valid when the study has no section line yet, so a map page
    can always add it."""
    layer = _memory("LineString", "Doorsnedelijn", [("naam", "string")])
    if zone.section_line:
        start, end = zone.section_line
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*start), QgsPointXY(*end)]))
        feature["naam"] = SECTION_LABEL
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
    layer.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#000000", "width": "0.6"}))
    return layer


def points_layer(kind: str, items: Iterable[Investigation]) -> QgsVectorLayer:
    """One labelled point layer per investigation kind ("sondering" / "boring" / "peilput").
    A peilput has no single number and no total depth, so it falls back to gw_id/filter_no and
    to the filter base."""
    layer = _memory("Point", POINT_NAMES[kind], POINT_FIELDS)
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
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    colour, marker = POINT_STYLE[kind]
    layer.renderer().setSymbol(QgsMarkerSymbol.createSimple(
        {"name": marker, "color": colour, "size": "2.6", "outline_color": "white", "outline_width": "0.3"}))
    settings = QgsPalLayerSettings()
    settings.fieldName = "nummer"
    text_format = QgsTextFormat()
    text_format.setSize(7)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    return layer


# --- project tree and GeoPackage -----------------------------------------------------------------

def add_group(project: QgsProject, title: str, group_layers: Sequence, visible: bool = True) -> QgsLayerTreeGroup:
    """Add the layers to the project under one group, in the given order. They are registered
    without a tree node (`addMapLayer(layer, False)`) so they appear inside the group only."""
    group = project.layerTreeRoot().addGroup(title)
    for layer in group_layers:
        project.addMapLayer(layer, False)
        group.addLayer(layer).setItemVisibilityChecked(visible)
    return group


def project_transform_context() -> QgsCoordinateTransformContext:
    return QgsProject.instance().transformContext()


def _write_gpkg_layer(layer: QgsVectorLayer, path: Path, first: bool) -> None:
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
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), project_transform_context(), options)
    if result[0] != QgsVectorFileWriter.WriterError.NoError:
        message = next((str(part) for part in result[1:] if part), "onbekende fout")
        raise RuntimeError(f"GeoPackage schrijven mislukt voor {layer.name()}: {message}")


def write_geopackage(gpkg_layers: Sequence[QgsVectorLayer], path: Path) -> None:
    """Write every memory layer into one GeoPackage, the first one creating the file."""
    path = Path(path)
    for index, layer in enumerate(gpkg_layers):
        _write_gpkg_layer(layer, path, first=index == 0)
