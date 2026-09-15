"""Reliëf van de zone uit het DHMV II DTM.

De offline tests zetten een piepklein eigen hoogteraster (een ESRI ASCII-grid van 5 x 5 cellen
over de Gent-zone) in de plaats van het WCS. Daarmee is de hele keten offline te volgen: welke
waarden eruit komen, wat er gebeurt als de zonale statistiek faalt, wat annuleren doet en of de
laag van de beller ongemoeid blijft. Dat het échte WCS een bruikbare dekking levert, kan alleen
live."""
from __future__ import annotations

import pytest

# Poort 9 (discard) op de loopback: de verbinding wordt geweigerd in plaats van te wachten, dus
# deze test blijft offline en snel.
DEAD_WCS_URL = "http://127.0.0.1:9/wcs"
# Vijf bij vijf cellen van 25 m rond X 104326 / Y 192506, hoogtes 10.0 tot 14.0 mTAW.
GRID_ROWS = [[10.0 + row * 1.0 for _ in range(5)] for row in range(5)]


def _ascii_dtm(tmp_path):
    """Een echt, geldig hoogteraster op schijf - geen mock: GDAL leest een ESRI ASCII-grid, dus de
    zonale statistiek loopt over dezelfde code als bij het WCS."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer

    path = tmp_path / "dtm.asc"
    header = ["ncols 5", "nrows 5", "xllcorner 104263.5", "yllcorner 192443.5",
              "cellsize 25", "NODATA_value -9999"]
    body = [" ".join(f"{value:.1f}" for value in row) for row in GRID_ROWS]
    path.write_text("\n".join(header + body) + "\n", encoding="ascii")
    layer = QgsRasterLayer(str(path), "test-DTM", "gdal")
    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:31370"))
    assert layer.isValid()
    return layer


@pytest.fixture
def fake_dtm(monkeypatch, tmp_path):
    """Zet het lokale raster in de plaats van het WCS; de laag blijft leven zolang de test duurt."""
    from desktopstudie.qgis import dem

    raster = _ascii_dtm(tmp_path)
    monkeypatch.setattr(dem.layers, "wcs_layer", lambda *args, **kwargs: raster)
    return raster


def _log():
    from desktopstudie.core.logging_util import Log

    lines = []
    return Log("dem", lines.append, scope="qgis"), lines


def test_an_unreachable_dtm_gives_no_relief_and_says_so(qgs_app, gent_zone, monkeypatch):
    """Een bron die faalt, faalt luid: geen reliëf én een WARNING, nooit stil een leeg resultaat."""
    from desktopstudie.qgis import dem, layers

    monkeypatch.setattr(dem, "DHMV_WCS_URL", DEAD_WCS_URL)
    log, lines = _log()

    assert dem.relief_of_zone(layers.zone_layer(gent_zone), log) is None
    assert any("WARNING" in line and "DHMV" in line for line in lines), lines


def test_no_log_is_a_valid_caller(qgs_app, gent_zone, monkeypatch):
    """`log` is optioneel; zonder logger mag het falen geen AttributeError worden."""
    from desktopstudie.qgis import dem, layers

    monkeypatch.setattr(dem, "DHMV_WCS_URL", DEAD_WCS_URL)
    assert dem.relief_of_zone(layers.zone_layer(gent_zone)) is None


def test_the_relief_comes_from_the_raster(qgs_app, gent_zone, fake_dtm):
    """Het raster loopt van 10 tot 14 mTAW; de zone van 50 m raakt de middelste rijen."""
    from desktopstudie.qgis import dem, layers

    relief = dem.relief_of_zone(layers.zone_layer(gent_zone), _log()[0])

    assert relief is not None
    lo, hi, mean = relief
    assert 10.0 <= lo <= mean <= hi <= 14.0


def test_the_callers_zone_layer_keeps_no_statistics_fields(qgs_app, gent_zone, fake_dtm):
    """De zonelaag van de beller gaat naar het GeoPackage en naar de kaartpagina's. Komt ze met
    dhmv_min/-max/-mean terug, dan staan die kolommen ineens in het projectbestand van de
    gebruiker - en bij een tweede meting krijgt hij er dhmv_min_1 bij."""
    from desktopstudie.qgis import dem, layers

    zone = layers.zone_layer(gent_zone)
    before = [field.name() for field in zone.fields()]

    assert dem.relief_of_zone(zone, _log()[0]) is not None
    assert [field.name() for field in zone.fields()] == before


def test_a_failed_statistic_names_its_result_code(qgs_app, fake_dtm):
    """QgsZonalStatistics gooit niet: het geeft een resultaatcode terug en laat de laag leeg. Een
    puntlaag is geen zone, dus dit hoort None op te leveren mét de code in de WARNING - niet
    stilzwijgend 'geen waarden gevonden'."""
    from qgis.core import QgsVectorLayer

    from desktopstudie.qgis import dem

    points = QgsVectorLayer("Point?crs=EPSG:31370", "geen zone", "memory")
    log, lines = _log()

    assert dem.relief_of_zone(points, log) is None
    warnings = [line for line in lines if "WARNING" in line]
    assert warnings, lines
    assert any("LayerTypeWrong" in line for line in warnings), warnings


def test_cancelling_stops_the_measurement(qgs_app, gent_zone, fake_dtm):
    """`should_cancel` is de afbreekknop van de gebruiker: zegt die ja, dan komt er geen reliëf
    terug en wordt dat gemeld - een half gemeten zone is geen meting."""
    from desktopstudie.qgis import dem, layers

    log, lines = _log()

    assert dem.relief_of_zone(layers.zone_layer(gent_zone), log, should_cancel=lambda: True) is None
    assert any("WARNING" in line for line in lines), lines


def test_not_cancelling_measures_as_usual(qgs_app, gent_zone, fake_dtm):
    """De afbreekknop mag de gewone meting niet in de weg zitten."""
    from desktopstudie.qgis import dem, layers

    relief = dem.relief_of_zone(layers.zone_layer(gent_zone), _log()[0], should_cancel=lambda: False)
    assert relief is not None


@pytest.mark.live
def test_live_relief_of_the_gent_zone(qgs_app, gent_zone):
    """Gent ligt rond 9 à 11 mTAW; de zone is 50 m groot, dus het gemiddelde hoort ruim binnen
    8 - 20 mTAW te liggen en tussen het minimum en het maximum."""
    from desktopstudie.qgis import dem, layers

    log, lines = _log()
    relief = dem.relief_of_zone(layers.zone_layer(gent_zone), log)

    assert relief is not None, lines
    lo, hi, mean = relief
    assert all(isinstance(value, float) for value in relief)
    assert 8.0 < mean < 20.0
    assert lo <= mean <= hi


@pytest.mark.live
def test_live_relief_reports_what_it_found(qgs_app, gent_zone):
    """Een gelukte fase logt haar samenvatting: anders is "reliëf ontbreekt" achteraf niet te
    onderscheiden van "reliëf is nooit opgevraagd"."""
    from desktopstudie.qgis import dem, layers

    log, lines = _log()
    dem.relief_of_zone(layers.zone_layer(gent_zone), log)
    assert any("INFO" in line for line in lines), lines
