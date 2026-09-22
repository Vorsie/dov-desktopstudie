"""QGIS layers for one study: WMS/WCS layers from the catalogue and memory layers from the model.

Nothing here decides *what* a study contains - the catalogue and the core model do. This module
only turns those into QgsMapLayers, gives them the house style and writes them to a GeoPackage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Collection, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
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
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor

from ..core import catalogue
from ..core.catalogue import MapEntry
from ..core.model import Borehole, Cpt, GwFilter, StudyResult, StudyZone, VirtualBorehole
from .compat import drop_colliding_labels, text_format

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
                ("methode", "string"), ("z_mtaw", "double"), ("url", "string"), ("met_figuur", "integer")]
# Which points carry a label on a report map. Two hundred numbers on top of each other make the
# overview page unreadable, and only the handful with a figure in the report can be looked up
# anyway - so on paper those are labelled and the rest are drawn as symbols. In QGIS every point
# keeps its number: there the reader can zoom.
FIGURED_LABEL = 'CASE WHEN "met_figuur" = 1 THEN "nummer" END'
# Only these two kinds ever get a figure in the report, so only for these does "label the ones
# with a figure" mean anything. A peilput would otherwise lose its number on every map page and
# there would be no way left to tie a triangle to the peilputten table - and a zone holds a
# handful of them, not two hundred.
FIGURED_KINDS = ("sondering", "boring")
DEPTH_ALIAS = "diepte / filterbasis (m)"
LABEL_FIELD = "nummer"
LABEL_SIZE_PT = 7.0
# A white ring around every label. Small enough not to fatten the lettering, wide enough that a
# number stays readable over a dark roof or over water.
LABEL_HALO_MM = 0.6
LABEL_HALO_COLOUR = "#ffffff"
POINT_SIZE_MM = "2.6"
# The virtual boreholes: a shape and a colour of their own, because a modelled column must never
# be mistaken for a sounding or a real borehole on the same map. Its fields are its own too - a
# virtual borehole has no number, no contractor and no fiche, it has a model and a ground level.
VB_NAME = "Virtuele boringen"
VB_STYLE = ("#7030a0", "diamond")
# The zone's own outline and the section line, named so the map key under a report map can show
# the same colours the map draws with instead of a second copy that quietly drifts.
ZONE_COLOUR = "#ff0000"
SECTION_LINE_COLOUR = "#000000"
VB_LABEL_FIELD = "model"
VB_FIELDS = [("model", "string"), ("x", "double"), ("y", "double"), ("maaiveld_mtaw", "double"),
             ("aantal_lagen", "integer")]
SECTION_LABEL = "A-A'"
ZONE_NAME = "Onderzoekszone"
SECTION_NAME = "Doorsnedelijn"
SEARCH_AREA_NAME = "Zoekstraal"
# The two groups of the study's own layers, and the GeoPackage layers each one holds. They carry
# no number: the chapter groups do, because each of them IS a chapter of the report, and these two
# are not - the zone and the section line appear in chapters 4 and 6, the investigations in 5 and
# 6. A number here would promise an order the PDF does not have. They come after the numbered
# groups in the panel because they are added after them.
# The pipeline writes exactly these names, so a project rebuilt from the file finds them back by
# name; a layer that is not in the file is reported, never invented.
ZONE_GROUP = "Onderzoekszone en doorsnede"
INVESTIGATION_GROUP = "Grondonderzoek DOV"
GPKG_GROUPS = (
    (ZONE_GROUP, (ZONE_NAME, SECTION_NAME)),
    (INVESTIGATION_GROUP, (POINT_NAMES["sondering"], POINT_NAMES["boring"], POINT_NAMES["peilput"],
                           VB_NAME, SEARCH_AREA_NAME)),
)
LOCKED_HINT = "sluit de lagen van een vorige studie in QGIS en probeer opnieuw"


# --- raster layers from the catalogue ------------------------------------------------------------

def snapshot_layer(path, name: str) -> QgsRasterLayer:
    """A map image already on disk, as a layer the layout can draw.

    The report draws these instead of the live WMS: the provider fetches tile after tile WHILE a
    page renders, one page at a time, and ninety sheets of that is the slowest thing a study does.
    The world file next to the PNG carries the placement; the CRS is set here, because a PNG has
    no way to say it and a layer without one lands wherever the project happens to think.
    """
    layer = QgsRasterLayer(str(path), name, "gdal")
    layer.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
    return layer


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


# --- the house style -----------------------------------------------------------------------------
# One symbol per study layer, applied both to the memory layer a run draws with and to the same
# layer read back from the GeoPackage by `standalone_project`. Two copies of these dictionaries
# would drift, and the drift would only show as a study that looks different in QGIS than on paper.

def style_zone_layer(layer: QgsVectorLayer) -> QgsVectorLayer:
    """The study zone: red outline, lightly filled so the map stays readable underneath."""
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "255,0,0,30", "outline_color": ZONE_COLOUR, "outline_width": "0.8"}))
    return layer


def style_search_area_layer(layer: QgsVectorLayer) -> QgsVectorLayer:
    """The search area: no fill, a dashed red outline - a boundary, not an area of its own."""
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ff0000", "outline_style": "dash", "outline_width": "0.5"}))
    return layer


def style_section_line_layer(layer: QgsVectorLayer) -> QgsVectorLayer:
    layer.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#000000", "width": "0.6"}))
    return layer


def _label_format() -> QgsTextFormat:
    """The lettering every point label on a report map uses: small, with a white halo.

    Without the halo the numbers of the soundings and boreholes run together over dark roofs and
    over water in the middle of the overview map and read as a smudge. The halo costs nothing and
    makes them legible over any backdrop.
    """
    # Via `compat.text_format`, dus met het huisfont: zonder expliciet lettertype kiest Qt er zelf
    # een, en offscreen tekende die "kb12d37w-B19" als "kb12d37-N- B19" - de w en het koppelteken
    # werden losse streepjes. Hetzelfde font als het rapport, zodat een boornummer op de kaart
    # leest zoals in de tabel. De halo hieronder hangt aan DEZE kopie: `text_format` geeft elke
    # oproeper een eigen object, anders droeg elke tabel in het rapport deze halo.
    fmt = text_format(LABEL_SIZE_PT)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(LABEL_HALO_MM)
    buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
    buffer.setColor(QColor(LABEL_HALO_COLOUR))
    fmt.setBuffer(buffer)
    return fmt


def style_points_layer(layer: QgsVectorLayer, kind: str,
                       label_only_figured: bool = False) -> QgsVectorLayer:
    """Marker, colour, size and the number label of one investigation kind.

    The units are pinned on purpose: without them a symbol follows whatever the host project
    happens to use, and the same study prints differently on another machine.

    `label_only_figured` labels only the points that have a figure in the report (see
    FIGURED_LABEL); that is the version the report maps draw. It applies to FIGURED_KINDS only -
    for a kind that never gets a figure it would mean no labels at all.
    """
    colour, marker = POINT_STYLE[kind]
    symbol = QgsMarkerSymbol.createSimple(
        {"name": marker, "color": colour, "size": POINT_SIZE_MM, "outline_color": "white",
         "outline_width": "0.3"})
    symbol.setSizeUnit(Qgis.RenderUnit.Millimeters)
    layer.renderer().setSymbol(symbol)
    settings = QgsPalLayerSettings()
    figured_only = label_only_figured and kind in FIGURED_KINDS
    settings.fieldName = FIGURED_LABEL if figured_only else LABEL_FIELD
    settings.isExpression = figured_only
    settings.setFormat(_label_format())
    drop_colliding_labels(settings)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    index = layer.fields().indexOf("diepte_m")
    if index >= 0:  # a peilput carries its filter base here; the alias says so in the table
        layer.setFieldAlias(index, DEPTH_ALIAS)
    return layer


def style_virtual_boreholes_layer(layer: QgsVectorLayer, labels: bool = True) -> QgsVectorLayer:
    """The virtual boreholes: a purple diamond, labelled with the model it came from.

    Deliberately unlike the three investigation kinds. A reader who cannot tell a modelled column
    from a real sounding at a glance reads the map wrong, and no legend fixes that.

    `labels=False` is the version the report maps draw: a dozen doorprik points along one section
    line all carry the same model name, and a dozen copies of "g3dv3_F" over that line is a grey
    smudge. In QGIS the label stays - there the reader can zoom and click.
    """
    colour, marker = VB_STYLE
    symbol = QgsMarkerSymbol.createSimple(
        {"name": marker, "color": colour, "size": POINT_SIZE_MM, "outline_color": "white",
         "outline_width": "0.3"})
    symbol.setSizeUnit(Qgis.RenderUnit.Millimeters)
    layer.renderer().setSymbol(symbol)
    settings = QgsPalLayerSettings()
    settings.fieldName = VB_LABEL_FIELD
    settings.setFormat(_label_format())
    drop_colliding_labels(settings)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(labels)
    return layer


def style_by_name(layer: QgsVectorLayer, log=None) -> QgsVectorLayer:
    """Give a layer read back from the GeoPackage the style it had during the study. The layer
    name is the only thing that survives the file, so it is what the lookup goes by."""
    name = layer.name()
    kind = next((key for key, title in POINT_NAMES.items() if title == name), None)
    if kind is not None:
        return style_points_layer(layer, kind)
    styles = {ZONE_NAME: style_zone_layer, SEARCH_AREA_NAME: style_search_area_layer,
              SECTION_NAME: style_section_line_layer, VB_NAME: style_virtual_boreholes_layer}
    if name in styles:
        return styles[name](layer)
    if log:
        log.warning(f"Geen huisstijl bekend voor de laag {name}; QGIS kiest zelf")
    return layer


# --- memory layers from the model (continued) ----------------------------------------------------

def zone_layer(zone: StudyZone) -> QgsVectorLayer:
    """The study zone itself: one polygon, red outline, lightly filled."""
    layer = _memory("Polygon", ZONE_NAME, [("naam", "string")])
    feature = QgsFeature(layer.fields())
    feature.setGeometry(_zone_polygon(zone))
    feature["naam"] = zone.name
    _add(layer, [feature])
    return style_zone_layer(layer)


def circle_layer(zone: StudyZone) -> QgsVectorLayer:
    """The search area: the DWITHIN region the core searched, i.e. the zone polygon buffered by
    `zone.radius_m`. Not a circle around the centroid - for anything but a round zone that both
    misses ground near a far corner and claims ground the core never queried."""
    layer = _memory("Polygon", SEARCH_AREA_NAME, [("straal_m", "double")])
    feature = QgsFeature(layer.fields())
    feature.setGeometry(_zone_polygon(zone).buffer(zone.radius_m, BUFFER_SEGMENTS))
    feature["straal_m"] = zone.radius_m
    _add(layer, [feature])
    return style_search_area_layer(layer)


def line_layer(zone: StudyZone) -> QgsVectorLayer:
    """The section line. Empty but valid when the study has no section line yet, so a map page
    can always add it."""
    layer = _memory("LineString", SECTION_NAME, [("naam", "string")])
    features = []
    if zone.section_line:
        start, end = zone.section_line
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*start), QgsPointXY(*end)]))
        feature["naam"] = SECTION_LABEL
        features.append(feature)
    _add(layer, features)
    return style_section_line_layer(layer)


def points_layer(kind: str, items: Iterable[Investigation],
                 figured: Collection[str] = ()) -> QgsVectorLayer:
    """One labelled point layer per investigation kind ("sondering" / "boring" / "peilput").

    A peilput has no single number and no total depth, so it falls back to gw_id/filter_no and
    to the filter base - hence the alias on diepte_m. `figured` holds the permkeys that got a
    figure in the report; those are the points a report map labels.
    """
    layer = _memory("Point", POINT_NAMES[kind], POINT_FIELDS)
    features = []
    for item in items:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(item.x, item.y)))
        gw_id, filter_no = getattr(item, "gw_id", "?"), getattr(item, "filter_no", "")
        number = getattr(item, "number", None) or f"{gw_id}/{filter_no}"
        depth = getattr(item, "depth_m", None) if hasattr(item, "depth_m") else getattr(item, "filter_base_m", None)
        feature.setAttributes([number, float(item.distance_m), depth, getattr(item, "date", None),
                               getattr(item, "method", None), getattr(item, "z_mtaw", None), item.url,
                               1 if getattr(item, "permkey", None) in figured else 0])
        features.append(feature)
    _add(layer, features)
    return style_points_layer(layer, kind)


def virtual_boreholes_layer(result: StudyResult) -> QgsVectorLayer:
    """Every virtual borehole this study took, as one point layer.

    Two kinds in one layer, because they are the same thing asked at different places: the ones at
    the representative point (one per model, so several points on one coordinate) and the doorprik
    points along the section line. A reader of the map has to be able to see WHERE the column in
    chapter 4 and the section in chapter 6 were taken - the report prints the coordinates, this is
    the same fact on the map.

    Always valid, even for a study that got none: the GeoPackage and `studie.qgz` carry the same
    layer names every run, and a name that is sometimes missing is reported as lost.
    """
    layer = _memory("Point", VB_NAME, VB_FIELDS)
    taken: List[VirtualBorehole] = list(result.virtual_boreholes.values())
    if result.section is not None:
        taken += list(result.section.boreholes)
    features = []
    seen = set()
    for borehole in taken:
        # One model at one place is one point. The doorprik that lands on the representative point
        # IS the virtual borehole of chapter 4, and the GeoPackage carried it twice.
        key = (borehole.model, round(float(borehole.x), 2), round(float(borehole.y), 2))
        if key in seen:
            continue
        seen.add(key)
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(borehole.x, borehole.y)))
        feature.setAttributes([borehole.model, float(borehole.x), float(borehole.y),
                               borehole.surface_mtaw, len(borehole.layers)])
        features.append(feature)
    _add(layer, features)
    return style_virtual_boreholes_layer(layer)


# --- project tree and GeoPackage -----------------------------------------------------------------

def drop_group(project: QgsProject, title: str,
               parent: Optional[QgsLayerTreeGroup] = None) -> int:
    """Remove the group called `title` under `parent` (the root by default) and its layers from
    the project; returns how many layers went. Nothing happens when there is no such group.

    Looked up under `parent` only: two studies in one project both hold a "1 Ligging", and the
    one being rebuilt must replace its own, not its neighbour's.
    """
    root = parent if parent is not None else project.layerTreeRoot()
    group = root.findGroup(title)
    if group is None:
        return 0
    ids = group.findLayerIds()
    group.parent().removeChildNode(group)
    if ids:
        project.removeMapLayers(ids)
    return len(ids)


def add_group(project: QgsProject, title: str, group_layers: Sequence[QgsMapLayer],
              visible: bool = True, parent: Optional[QgsLayerTreeGroup] = None) -> QgsLayerTreeGroup:
    """Add the layers to the project under one group, in the given order, at the root or under
    `parent`. They are registered without a tree node (`addMapLayer(layer, False)`) so they
    appear inside the group only.

    A group of the same name under the same parent is replaced, its layers removed from the
    project first: a study run three times in one session must not leave three copies of
    "Grondonderzoek DOV" in the layer panel, two of them stale.
    """
    drop_group(project, title, parent)
    root = parent if parent is not None else project.layerTreeRoot()
    group = root.addGroup(title)
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


# --- the standalone project ----------------------------------------------------------------------

def gpkg_layer(gpkg: Path, name: str) -> QgsVectorLayer:
    """One layer out of the study GeoPackage, by the name it was written under."""
    return QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")


def standalone_project(gpkg: Path, chapter_groups: Dict[str, str], log=None,
                       wms_layers: Optional[Dict[str, QgsMapLayer]] = None,
                       only: Optional[Iterable[str]] = None) -> Tuple[QgsProject, List[MapEntry]]:
    """(project, the entries it had to drop): the catalogue maps as WMS layers and the study's
    own layers read back from `gpkg`.

    This is the deliverable the user opens weeks later, without the plugin and without the
    session that made it - so nothing here may point at a memory layer. `QgsProject.addMapLayer`
    drops an invalid layer, which is exactly right for a WMS that was unreachable while the study
    ran: the project keeps the maps that work instead of failing to open.

    A drop is logged AND handed back, because a log line is not a report: headless the layers are
    built here and nowhere else, so without the list a map can be missing from `studie.qgz` with
    nothing in the sources chapter saying which one or why.

    `wms_layers` (map id -> layer) hands over what the caller has already built; each one is
    CLONED, because a project owns its layers and the caller's belong to its own project. Building
    them again would cost a second GetCapabilities per map - thirty round trips for nothing.

    `only` is the study's map choice (`StudyResult.map_ids`): a map the user unchecked is not in
    the report and must not be in the deliverable project either.
    """
    gpkg = Path(gpkg)
    ready = dict(wms_layers or {})
    dropped: List[MapEntry] = []
    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem(CRS_AUTHID))
    # The study's own layers go in FIRST, so the chapter groups of maps append underneath them.
    # The bottom of a layer tree draws first, so a group added after the maps ends up behind them -
    # which hid the zone outline, the section line and every sounding the moment a map was switched
    # on, in the project a reader opens for exactly those.
    for title, names in GPKG_GROUPS:
        group_layers: List[QgsMapLayer] = []
        for name in names:
            layer = gpkg_layer(gpkg, name)
            if not layer.isValid():
                if log:
                    log.warning(f"Laag {name} staat niet in {gpkg.name}; overgeslagen")
                continue
            group_layers.append(style_by_name(layer, log))
        add_group(project, title, group_layers)
    for chapter, title in chapter_groups.items():
        rasters: List[QgsMapLayer] = []
        for entry in catalogue.entries(chapter, only=only):
            known = ready.get(entry.id)
            layer = known.clone() if known is not None else wms_layer(entry)
            if not layer.isValid():
                if log:
                    log.warning(f"WMS-laag niet geldig, niet in het project: {entry.id}")
                dropped.append(entry)
                continue
            rasters.append(layer)
        add_group(project, title, rasters, visible=False)
        if log:
            log.info(f"{title}: {len(rasters)} WMS-lagen")
    return project, dropped
