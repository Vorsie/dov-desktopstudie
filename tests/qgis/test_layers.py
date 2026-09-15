"""Lagen van één studie: WMS/WCS uit de catalogus, memory-lagen uit het model, groepen en
GeoPackage. Alles offline: een WMS-laag wordt hier alleen op zijn bron en naam gecontroleerd,
want geldigheid vergt een echte GetCapabilities (zie de live-test onderaan)."""
from __future__ import annotations

import pytest


def test_wms_layer_uri_from_catalogue(qgs_app):
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    lyr = layers.wms_layer(catalogue.by_id("ferraris"))
    src = lyr.source()
    assert "url=https://geo.api.vlaanderen.be/HISTCART/wms" in src and "layers=ferraris" in src
    assert "crs=EPSG:31370" in src and "format=image/png" in src
    assert lyr.name() == "Ferrariskaart (1777)"


def test_wcs_layer_uri(qgs_app):
    from desktopstudie.core.catalogue import DHMV_WCS_COVERAGE, DHMV_WCS_URL
    from desktopstudie.qgis import layers

    lyr = layers.wcs_layer(DHMV_WCS_URL, DHMV_WCS_COVERAGE, "DHMV II DTM 1 m")
    src = lyr.source()
    assert "url=" + DHMV_WCS_URL in src and "identifier=" + DHMV_WCS_COVERAGE in src
    assert "crs=EPSG:31370" in src and lyr.name() == "DHMV II DTM 1 m"


def test_memory_layers_from_zone_and_points(qgs_app, gent_zone):
    from desktopstudie.core.model import Cpt
    from desktopstudie.qgis import layers

    zone_layer = layers.zone_layer(gent_zone)
    assert zone_layer.isValid() and zone_layer.featureCount() == 1
    circle = layers.circle_layer(gent_zone)
    assert circle.featureCount() == 1
    cpts = [Cpt("k1", "S1", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01", "continu elektrisch", None, None, None,
                "https://www.dov.vlaanderen.be/data/sondering/k1", 12.0)]
    pts = layers.points_layer("sondering", cpts)
    assert pts.featureCount() == 1
    f = next(pts.getFeatures())
    assert f["nummer"] == "S1" and f["url"].endswith("/k1") and abs(f["afstand_m"] - 12.0) < 1e-9


def test_line_layer_is_empty_without_a_section_line(qgs_app, gent_zone):
    """`zone.section_line` wordt pas door de kern gevuld; zonder lijn blijft de laag leeg
    maar geldig, zodat de kaartpagina hem altijd kan toevoegen."""
    from desktopstudie.qgis import layers

    assert layers.line_layer(gent_zone).featureCount() == 0
    gent_zone.section_line = ((104276.0, 192506.0), (104376.0, 192506.0))
    line = layers.line_layer(gent_zone)
    assert line.isValid() and line.featureCount() == 1
    assert next(line.getFeatures())["naam"] == "A-A'"


def test_groups_and_geopackage(qgs_app, gent_zone, tmp_path):
    from qgis.core import QgsProject

    from desktopstudie.qgis import layers

    project = QgsProject()
    zl = layers.zone_layer(gent_zone)
    layers.add_group(project, "5 Grondonderzoek", [zl])
    assert project.layerTreeRoot().findGroup("5 Grondonderzoek") is not None
    gpkg = tmp_path / "studie.gpkg"
    layers.write_geopackage([zl], gpkg)
    assert gpkg.exists() and gpkg.stat().st_size > 1000


def test_write_geopackage_reports_a_failure(qgs_app, gent_zone, tmp_path):
    """Schrijven mag nooit stil mislukken: een onbereikbaar pad geeft een RuntimeError met
    de boodschap van de writer erin."""
    from desktopstudie.qgis import layers

    with pytest.raises(RuntimeError) as err:
        layers.write_geopackage([layers.zone_layer(gent_zone)], tmp_path / "geen" / "map" / "studie.gpkg")
    assert "Onderzoekszone" in str(err.value)


@pytest.mark.live
def test_live_wms_layer_is_valid(qgs_app):
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    lyr = layers.wms_layer(catalogue.by_id("ferraris"))
    assert lyr.isValid(), lyr.error().summary()
