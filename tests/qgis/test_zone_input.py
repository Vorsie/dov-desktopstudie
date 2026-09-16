"""Wat de dialoog van een adres, een punt, een getekende ring of een geselecteerd object maakt: een
`StudyZone` in Lambert 72. Pure functies, zonder een enkel widget - de vier invoermodi van de plugin
zijn hier te bewijzen zonder QGIS-GUI, en dat is de reden dat ze buiten de dialoog staan."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

GENT = (104326.0, 192506.0)


def _transformed(ring, to_authid):
    """De ring van Lambert 72 naar `to_authid`, met QGIS zelf - de referentie voor de terugweg."""
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsCoordinateTransformContext,
        QgsPointXY,
    )

    transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:31370"),
                                       QgsCoordinateReferenceSystem(to_authid),
                                       QgsCoordinateTransformContext())
    return [(p.x(), p.y()) for p in (transform.transform(QgsPointXY(x, y)) for x, y in ring)]


def _close(ring, other, tolerance):
    return len(ring) == len(other) and all(abs(a[0] - b[0]) < tolerance and abs(a[1] - b[1]) < tolerance
                                           for a, b in zip(ring, other))


def test_a_zone_from_an_address_hit_is_a_circle_named_after_the_address(qgs_app):
    """Adresmodus: de kandidaat van de geocoder wordt een cirkel van `buffer_m` rond het adrespunt,
    met het adres als naam en als adres op het titelblad - zoals de headless runner het al doet."""
    from desktopstudie.core import geometry
    from desktopstudie.core.services.geocoder import GeocodeHit
    from desktopstudie.qgis.zone_input import zone_from_address_hit

    hit = GeocodeHit("Kortrijksesteenweg 100, 9000 Gent", GENT[0], GENT[1], "Gent", "9000",
                     "basisregisters_huisnummer")

    zone = zone_from_address_hit(hit, buffer_m=50.0, radius_m=500.0)

    assert zone.name == hit.address and zone.address == hit.address
    assert zone.radius_m == 500.0
    assert len(zone.ring) >= 32
    assert all(abs(geometry.distance(point, GENT) - 50.0) < 0.01 for point in zone.ring)


def test_a_zone_from_a_point_is_named_after_its_coordinates(qgs_app):
    """X/Y-modus: geen adres, dus de naam is het coördinaat, afgerond op de meter."""
    from desktopstudie.qgis.zone_input import zone_from_point

    zone = zone_from_point(GENT[0], GENT[1], buffer_m=25.0, radius_m=300.0)

    assert zone.name == "104326/192506" and zone.address is None
    assert zone.radius_m == 300.0
    assert zone.centroid == pytest.approx(GENT, abs=0.01)


def test_a_ring_drawn_in_another_crs_arrives_in_lambert_72(qgs_app, gent_zone):
    """Tekenmodus: het canvas kan in WGS 84 staan. De ring komt terug in Lambert 72, op de
    centimeter dezelfde als waar hij vandaan kwam, en het sluitpunt staat er niet dubbel in."""
    from desktopstudie.qgis.zone_input import zone_from_ring

    drawn = _transformed(gent_zone.ring, "EPSG:4326")
    drawn.append(drawn[0])  # zoals een teken-tool afsluit: het eerste punt nog eens

    zone = zone_from_ring(drawn, "EPSG:4326", radius_m=500.0, name="Getekend")

    assert zone.name == "Getekend" and zone.address is None
    assert _close(zone.ring, gent_zone.ring, 0.01)
    # The project's transform context (its chosen datum transforms) can be handed in.
    from qgis.core import QgsCoordinateTransformContext

    same = zone_from_ring(drawn, "EPSG:4326", radius_m=500.0, name="Getekend",
                          context=QgsCoordinateTransformContext())
    assert same.ring == zone.ring


def test_a_selected_feature_gives_its_exterior_ring_in_lambert_72(qgs_app, gent_zone):
    """Laagmodus: het eerste geselecteerde object van een laag in Web Mercator. Alleen de buitenring
    telt - een perceel met een gat wordt de zone zonder dat gat (bekende schuld: één ring)."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    from desktopstudie.core import geometry
    from desktopstudie.qgis.zone_input import zone_from_feature

    layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "percelen", "memory")
    outer = _transformed(gent_zone.ring, "EPSG:3857")
    hole = _transformed(geometry.buffer_point(GENT[0], GENT[1], 10.0, 8), "EPSG:3857")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(*p) for p in outer],
                                                   [QgsPointXY(*p) for p in hole]]))
    assert layer.dataProvider().addFeatures([feature])

    zone = zone_from_feature(next(layer.getFeatures()), layer.crs(), radius_m=500.0, name="percelen #1")

    assert zone.name == "percelen #1"
    assert _close(zone.ring, gent_zone.ring, 0.05)


def test_a_multipart_feature_takes_its_largest_part(qgs_app, gent_zone):
    """Een multipolygoon levert de buitenring van zijn grootste deel; een snipper ernaast mag de
    studie niet naar de verkeerde plek sturen."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    from desktopstudie.core import geometry
    from desktopstudie.qgis.zone_input import zone_from_feature

    snippet = geometry.buffer_point(GENT[0] + 400.0, GENT[1], 5.0, 8)
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromMultiPolygonXY([[[QgsPointXY(*p) for p in snippet]],
                                                        [[QgsPointXY(*p) for p in gent_zone.ring]]]))

    zone = zone_from_feature(feature, "EPSG:31370", radius_m=500.0)

    assert _close(zone.ring, gent_zone.ring, 0.001)


def test_what_is_not_an_area_is_refused_with_a_reason(qgs_app):
    """Twee punten zijn geen vlak, en een ring zonder oppervlakte ook niet: een fout die zegt wat er
    ontbreekt, geen studie van niets."""
    from desktopstudie.qgis.zone_input import zone_from_ring

    with pytest.raises(ValueError, match="minstens drie"):
        zone_from_ring([(0.0, 0.0), (10.0, 10.0)], "EPSG:31370", radius_m=500.0)
    with pytest.raises(ValueError, match="oppervlakte"):
        zone_from_ring([(0.0, 0.0), (10.0, 10.0), (20.0, 20.0)], "EPSG:31370", radius_m=500.0)


def test_a_section_line_from_points_or_a_feature_keeps_its_two_ends(qgs_app):
    """De doorsnedelijn: van een getekende lijn tellen het eerste en het laatste punt, van een
    geselecteerd lijnobject net zo - allebei in Lambert 72."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    from desktopstudie.qgis.zone_input import section_from_feature, section_from_points

    start, end = (104226.0, 192406.0), (104426.0, 192606.0)
    drawn = _transformed([start, (104300.0, 192450.0), end], "EPSG:4326")

    line = section_from_points(drawn, "EPSG:4326")
    assert line[0] == pytest.approx(start, abs=0.01) and line[1] == pytest.approx(end, abs=0.01)

    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*start), QgsPointXY(*end)]))
    assert section_from_feature(feature, "EPSG:31370") == (start, end)
    with pytest.raises(ValueError, match="twee punten"):
        section_from_points([start], "EPSG:31370")


def test_the_run_folder_carries_the_project_and_the_moment(qgs_app):
    """Elke run schrijft in een eigen map onder de uitvoermap: projectnaam plus datum en tijd, zodat
    een tweede run nooit het GeoPackage van de eerste overschrijft of vergrendeld vindt. Tekens die
    geen bestandsnaam verdragen worden vervangen."""
    from desktopstudie.qgis.zone_input import run_folder

    folder = run_folder(Path("C:/uit"), "Project X/Y: Gent", dt.datetime(2026, 9, 16, 14, 5))

    assert folder == Path("C:/uit") / "Project_X_Y_Gent_20260916_1405"
    assert run_folder(Path("C:/uit"), "   ", dt.datetime(2026, 9, 16, 14, 5)).name == "Desktopstudie_20260916_1405"
