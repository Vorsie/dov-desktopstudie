"""What the dialog turns into a study: a zone from an address, a point, a drawn ring or a selected
feature; a section line from a drawn line or a selected feature; and the folder a run writes to.

Pure functions on purpose - no widget, no canvas, no iface - so the four input modes of the plugin
are proven in a headless QgsApplication (tests/qgis/test_zone_input.py) and the dialog only has to
read its widgets. Everything leaves here in Lambert 72 (EPSG:31370), which is what the core computes
in; the caller says which CRS its points came in, because a canvas can stand in anything.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCsException,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
)

from ..core import geometry
from ..core.geometry import CRS, Point
from ..core.model import StudyZone, point_name
from ..core.paths import safe_segment
from ..core.services.geocoder import GeocodeHit

DEFAULT_PROJECT_NAME = "Desktopstudie"
MIN_RING_POINTS = 3
Crs = Union[str, QgsCoordinateReferenceSystem]
Line = Tuple[Point, Point]


def _crs(crs: Crs) -> QgsCoordinateReferenceSystem:
    resolved = QgsCoordinateReferenceSystem(crs) if isinstance(crs, str) else crs
    if not resolved.isValid():
        raise ValueError(f"ongeldig coördinatenstelsel: {crs}")
    return resolved


def to_lambert72(points: Sequence[Point], crs: Crs,
                 context: Optional[QgsCoordinateTransformContext] = None) -> List[Point]:
    """`points` given in `crs`, in Lambert 72. Points already in Lambert 72 pass through untouched,
    so a ring the user typed in metres stays the ring the user typed. `context` is the project's
    choice of datum transforms; without one the default transform applies."""
    source, target = _crs(crs), QgsCoordinateReferenceSystem(CRS)
    if source == target:
        return [(float(x), float(y)) for x, y in points]
    transform = QgsCoordinateTransform(source, target, context or QgsCoordinateTransformContext())
    try:
        moved = [transform.transform(QgsPointXY(x, y)) for x, y in points]
    except QgsCsException as exc:
        raise ValueError(f"punten uit {source.authid()} konden niet naar Lambert 72: {exc}") from exc
    return [(point.x(), point.y()) for point in moved]


def _ring(points: Sequence[Point], crs: Crs, context=None) -> List[Point]:
    """The ring in Lambert 72, its closing point dropped, refused when it is not an area."""
    ring = to_lambert72(points, crs, context)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < MIN_RING_POINTS:
        raise ValueError(f"een zone heeft minstens drie hoekpunten nodig ({len(ring)} gegeven)")
    if geometry.area(ring) <= 0.0:
        raise ValueError("de ring heeft geen oppervlakte")
    return ring


def zone_from_address_hit(hit: GeocodeHit, buffer_m: float, radius_m: float) -> StudyZone:
    """Address mode: a circle of `buffer_m` around the geocoder's point, named after the address."""
    return StudyZone.around_point(hit.x, hit.y, buffer_m, radius_m, address=hit.address)


def zone_from_point(x: float, y: float, buffer_m: float, radius_m: float) -> StudyZone:
    """X/Y mode: the same circle around a Lambert 72 coordinate, named after the coordinate."""
    return StudyZone.around_point(x, y, buffer_m, radius_m)


def zone_from_ring(points: Sequence[Point], crs: Crs, radius_m: float,
                   name: Optional[str] = None, context=None) -> StudyZone:
    """Drawing mode: the vertices the map tool collected, in the canvas CRS."""
    ring = _ring(points, crs, context)
    return StudyZone(ring=ring, name=name or f"Polygoon {point_name(*geometry.centroid(ring))}",
                     radius_m=radius_m)


def _geometry_of(feature: QgsFeature, wanted, what: str) -> QgsGeometry:
    """The feature's geometry, when it has one of the wanted kind."""
    geom = feature.geometry()
    if geom is None or geom.isNull() or geom.isEmpty():
        raise ValueError("het geselecteerde object heeft geen geometrie")
    if geom.type() != wanted:
        raise ValueError(f"het geselecteerde object is geen {what}")
    return geom


def zone_from_feature(feature: QgsFeature, crs: Crs, radius_m: float,
                      name: Optional[str] = None, context=None) -> StudyZone:
    """Layer mode: the exterior ring of the largest part of a (multi)polygon feature, in the layer's
    CRS. Holes are dropped - a study zone is one ring (see the debt list in CLAUDE.md) - and a
    sliver next to the real parcel must not steer the study elsewhere, hence the largest part."""
    geom = _geometry_of(feature, Qgis.GeometryType.Polygon, "vlak")
    parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    largest = max(parts, key=lambda rings: QgsGeometry.fromPolygonXY(rings).area())
    return zone_from_ring([(point.x(), point.y()) for point in largest[0]], crs, radius_m, name, context)


def section_from_points(points: Sequence[Point], crs: Crs, context=None) -> Line:
    """A drawn section line: its first and its last vertex, in Lambert 72."""
    line = to_lambert72(points, crs, context)
    if len(line) < 2:
        raise ValueError("een doorsnedelijn heeft twee punten nodig")
    if line[0] == line[-1]:
        raise ValueError("begin en einde van de doorsnedelijn vallen samen")
    return line[0], line[-1]


def section_from_feature(feature: QgsFeature, crs: Crs, context=None) -> Line:
    """A selected line feature: the two ends of its longest part, in Lambert 72."""
    geom = _geometry_of(feature, Qgis.GeometryType.Line, "lijn")
    parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
    longest = max(parts, key=lambda part: QgsGeometry.fromPolylineXY(part).length())
    return section_from_points([(point.x(), point.y()) for point in longest], crs, context)


def safe_name(text: str) -> str:
    """`text` as a folder name; see `core.paths.safe_segment` for what survives.

    With a fallback rather than an error, because this text is typed by a human: a project called
    "///" is a slip, and the dialog may not fall over on it.
    """
    return safe_segment(text, fallback=DEFAULT_PROJECT_NAME)


def run_folder(base: Path, project: str, now: Optional[dt.datetime] = None) -> Path:
    """Where one run writes: `<base>/<project>_<yyyymmdd>_<HHMM>`. A folder per run, so the
    GeoPackage of the previous run - possibly still open in this very QGIS - is never overwritten
    or found locked."""
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d_%H%M")
    return Path(base) / f"{safe_name(project)}_{stamp}"
