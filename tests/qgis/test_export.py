"""De export van een layout: een PDF, een PNG per pagina en een projectbestand.

Alles offline: de "WMS-laag" is een memory-laag en de legenda is een zelfgemaakte PNG. De
layout van drie pagina's (titelblad, kaart, legenda) is klein genoeg om snel te exporteren en
groot genoeg om te laten zien dat elke pagina meekomt.
"""
from __future__ import annotations

import pytest

from tests.qgis.conftest import write_png

MAP_ID = "grb"  # een echte catalogusentry: de layout leest er titel, attributie en licentie uit
HEADER_TOP_MM, HEADER_BOTTOM_MM = 8.0, 24.0  # de band met de hoofdstukkop en de paginatitel
A4_HEIGHT_MM = 297.0
# Gemeten op QGIS 3.40.15 offscreen, 72 dpi: mét QT_QPA_FONTDIR is 0,6 % van de kopband puur
# zwart (alleen de kern van de letters; de rest is antialiasing), zonder 20,2 % - de blokjes zijn
# dicht. De grens ligt daartussen, dicht genoeg bij de echte waarde om de storing te vangen.
BLACK_SHARE = 0.05


def _meta():
    return {"project": "Testproject", "project_number": "T-001", "author": "A. Tester",
            "company": "Testbureau", "address": "Kortrijksesteenweg 100", "municipality": "Gent",
            "zone_name": "Gent test", "created_at": "2026-09-15T10:00:00",
            "disclaimer": "<p>Geen interpretatie.</p>", "logo_path": ""}


def _pdf_pages(path):
    """Het aantal pagina's in een PDF. Elke pagina is een object met /Type /Page; de paginaboom
    zelf draagt /Type /Pages en die telt niet mee."""
    data = path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


@pytest.fixture
def three_pages(project, gent_zone, tmp_path):
    """Titelblad + kaartpagina + legendapagina, zonder ook maar een service aan te raken."""
    from desktopstudie.core.report_content import Chapter, MapPage, Report
    from desktopstudie.qgis import layers, layout

    wms_stand_in = layers.zone_layer(gent_zone)
    wms_stand_in.setName("GRB-basiskaart")
    project.addMapLayer(wms_stand_in, False)
    zone = layers.zone_layer(gent_zone)
    project.addMapLayer(zone, False)
    page = MapPage(MAP_ID, "Ligging op de GRB-basiskaart", legend=True, scale=2500)
    report = Report(title="Desktopstudie testproject", meta={},
                    chapters=[Chapter(1, "Ligging en topografie", [page])])
    return layout.build_layout(project, report, {MAP_ID: [wms_stand_in]}, {"zone": [zone]}, tmp_path,
                               gent_zone.ring, _meta(),
                               legend_images={MAP_ID: write_png(tmp_path / "legendas" / f"{MAP_ID}.png", 120, 300)})


# --- PDF -------------------------------------------------------------------------------------

def test_the_pdf_holds_every_page_of_the_layout(three_pages, tmp_path):
    """Drie bladen in de layout, drie bladen in de PDF - een rapport dat onderweg een pagina
    verliest, verliest ze stil."""
    from desktopstudie.qgis import export

    pdf = export.export_pdf(three_pages, tmp_path / "rapport.pdf")

    assert pdf.exists() and pdf.stat().st_size > 5000
    assert pdf.read_bytes()[:4] == b"%PDF"
    assert _pdf_pages(pdf) == 3


def test_the_legend_switch_is_evaluated_before_the_pdf_is_written(three_pages, tmp_path):
    """`@legendas = 0` sluit de legendapagina's uit, maar alleen als de layout eerst ververst is.
    Zonder die verversing staat de legendapagina gewoon in de PDF en ziet niemand het verschil."""
    from qgis.core import QgsExpressionContextUtils

    from desktopstudie.qgis import export

    QgsExpressionContextUtils.setLayoutVariable(three_pages, "legendas", 0)

    pdf = export.export_pdf(three_pages, tmp_path / "zonder.pdf")

    assert _pdf_pages(pdf) == 2


def test_a_failed_pdf_export_says_which_result_it_got(three_pages, tmp_path):
    """Een export die mislukt, hoort te knallen met de naam van de fout, niet met een kale 3.
    Schrijven naar een bestaande map kan niet, en dat is precies zo'n geval."""
    from desktopstudie.qgis import export

    with pytest.raises(RuntimeError) as failure:
        export.export_pdf(three_pages, tmp_path)

    assert "FileError" in str(failure.value), str(failure.value)


# --- pagina's als PNG ------------------------------------------------------------------------

def test_every_page_becomes_a_png_in_page_order(three_pages, tmp_path):
    """QGIS noemt de bladen pagina.png, pagina_2.png, pagina_3.png. Alfabetisch gesorteerd komt
    pagina_10 voor pagina_2; de lijst hoort in bladvolgorde terug te komen."""
    from desktopstudie.qgis import export

    pages = export.export_pages_png(three_pages, tmp_path / "paginas")

    assert [path.name for path in pages] == ["pagina.png", "pagina_2.png", "pagina_3.png"]
    assert all(path.exists() and path.stat().st_size > 1000 for path in pages)


def test_pages_of_an_earlier_run_do_not_come_back(three_pages, tmp_path):
    """Een tweede, kortere studie in dezelfde map mag geen bladen van de vorige meeleveren."""
    from desktopstudie.qgis import export

    directory = tmp_path / "paginas"
    directory.mkdir()
    write_png(directory / "pagina_9.png")

    pages = export.export_pages_png(three_pages, directory)

    assert [path.name for path in pages] == ["pagina.png", "pagina_2.png", "pagina_3.png"]
    assert not (directory / "pagina_9.png").exists()


def test_a_rendered_page_shows_letters_not_black_boxes(three_pages, tmp_path):
    """Het offscreen-platform zonder QT_QPA_FONTDIR tekent elke letter als zwart blokje terwijl de
    export Success meldt. De kopband van een blad hoort dus tekst te tonen: donkere pixels, maar
    lang geen dichte balk. Draait deze test rood, kijk dan eerst naar QT_QPA_FONTDIR."""
    from qgis.PyQt.QtGui import QColor, QImage

    from desktopstudie.qgis import export

    pages = export.export_pages_png(three_pages, tmp_path / "paginas")
    image = QImage(str(pages[1]))  # de kaartpagina: hoofdstukkop + paginatitel
    assert not image.isNull()
    top = int(image.height() * HEADER_TOP_MM / A4_HEIGHT_MM)
    bottom = int(image.height() * HEADER_BOTTOM_MM / A4_HEIGHT_MM)
    black = QColor(0, 0, 0)
    dark = sum(1 for y in range(top, bottom) for x in range(image.width())
               if image.pixelColor(x, y) == black)
    band = (bottom - top) * image.width()

    assert dark > 0, "geen enkele donkere pixel: er staat helemaal geen tekst op het blad"
    assert dark / band < BLACK_SHARE, f"{dark / band:.0%} van de kopband is zwart: blokjes, geen letters"


# --- projectbestand --------------------------------------------------------------------------

def test_the_project_is_written_and_can_be_read_back(project, gent_zone, tmp_path):
    """Een .qgz is het tweede product van een studie; hij moet in QGIS weer opengaan."""
    from qgis.core import QgsProject

    from desktopstudie.qgis import export, layers

    layers.add_group(project, "4 Onderzoekszone en doorsnede", [layers.zone_layer(gent_zone)])

    path = export.write_project(project, tmp_path / "studie.qgz")

    assert path.exists() and path.stat().st_size > 1024
    reread = QgsProject()
    assert reread.read(str(path)), reread.error()
    assert [group.name() for group in reread.layerTreeRoot().findGroups()] == \
           ["4 Onderzoekszone en doorsnede"]
    assert [layer.name() for layer in reread.mapLayers().values()] == ["Onderzoekszone"]


def test_a_project_that_cannot_be_written_is_not_reported_as_written(project, tmp_path):
    """Schrijven naar een map is geen schrijven; dat hoort te knallen in plaats van een pad terug
    te geven waar niets staat."""
    from desktopstudie.qgis import export

    with pytest.raises(RuntimeError):
        export.write_project(project, tmp_path)
