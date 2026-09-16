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


def _page_content(path, page):
    """De uitgepakte inhoudsstroom van blad `page` (0-gebaseerd), zoals Qt ze wegschrijft: het
    /Type /Page-object wijst met /Contents naar een object dat een FlateDecode-stroom draagt."""
    import re
    import zlib

    data = path.read_bytes()
    page_objects = [m for m in re.finditer(rb"/Type /Page\b(?!s)", data)]
    contents = re.search(rb"/Contents (\d+) 0 R", data[page_objects[page].start():])
    number = int(contents.group(1))
    start = re.search(rb"(?<!\d)" + str(number).encode() + rb" 0 obj", data).end()
    raw = data[start:data.index(b"endstream", start)]
    stream = raw[raw.index(b"stream") + len(b"stream"):].lstrip(b"\r\n")
    return zlib.decompress(stream)


def _rendered(path, page):
    """Blad `page` (0-gebaseerd) van een PDF als pixels, getekend door de PDF-driver van GDAL."""
    from osgeo import gdal

    gdal.UseExceptions()
    dataset = gdal.Open(f"PDF:{page + 1}:{path}")
    return dataset.ReadAsArray().astype(int)


def _same_picture(first, second):
    """Twee renders van hetzelfde blad: geen pixel meer dan een paar tinten uiteen, en minder dan
    een op de duizend uberhaupt - de rasterizer rondt anders af naargelang het lettertype-subset."""
    difference = abs(first - second)
    return first.shape == second.shape and difference.max() <= 8 and (difference > 0).mean() < 0.001


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
    return layout.build_layout(project, report, {"zone": [zone]}, tmp_path,
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


def test_the_text_in_the_pdf_is_text_a_reader_can_select_not_outlines(three_pages, tmp_path):
    """Een rapport waarin niemand tekst kan selecteren, is een rapport waaruit niemand kan citeren.
    QGIS tekent tekst standaard als omtrekken (paden): dan staat er op de kaartpagina - kop,
    infovakken, schaalbalk, allemaal gewone tekst - geen enkel tekstobject. Tekst hoort als tekst
    in de PDF te staan (een BT ... ET-blok met een lettertype), zodat ze te selecteren, te
    doorzoeken en te kopieren valt; het bestand wordt er ook de helft kleiner van."""
    from desktopstudie.qgis import export

    pdf = export.export_pdf(three_pages, tmp_path / "rapport.pdf")

    content = _page_content(pdf, 1)  # de kaartpagina: geen HTML-labels, alleen gewone tekst
    assert b"BT" in content and b"ET" in content, "geen tekstobject op de kaartpagina: omtrekken"
    assert b"/BaseFont" in pdf.read_bytes(), "geen enkel lettertype ingebed"


def test_the_sheets_go_to_the_exporter_a_few_at_a_time_and_the_pdf_is_the_same(three_pages, tmp_path):
    """Eén exportoproep voor het hele rapport betaalt per blad een prijs die groeit met het aantal
    bladen dat al geëxporteerd is (kwadratisch; 65 van de 95 s voor Gent). De bladen gaan daarom
    in kleine runs naar de exporter, maar de PDF hoort daar niets van te merken: elk blad één keer,
    in volgorde, met dezelfde inhoud als in één oproep - ook met een run van één blad."""
    from qgis.core import Qgis, QgsLayoutExporter

    from desktopstudie.qgis import export

    in_runs = export.export_pdf(three_pages, tmp_path / "runs.pdf", pages_per_run=1)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = export.PDF_DPI
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    at_once = tmp_path / "eens.pdf"
    assert QgsLayoutExporter(three_pages).exportToPdf(str(at_once), settings) == export.SUCCESS

    assert _pdf_pages(in_runs) == _pdf_pages(at_once) == 3
    for page in range(3):
        # Wat op het blad staat, vergeleken als beeld: de inhoudsstromen zelf verschillen in de
        # nummering van de lettertype-subsets (de volgorde waarin Qt glyphs registreert).
        assert _same_picture(_rendered(in_runs, page), _rendered(at_once, page)), f"blad {page + 1} verschilt"
    # De layout verlaat de export zoals ze erin ging: niets uitgesloten, de legendaregel intact.
    pages = three_pages.pageCollection()
    assert not any(pages.page(index).excludeFromExports() for index in range(pages.pageCount()))
    assert pages.page(2).dataDefinedProperties().property(export.EXCLUDE).isActive()


def test_a_cancel_between_two_runs_stops_the_export_and_leaves_no_half_report(three_pages, tmp_path):
    """De bladen gaan in runs naar de exporter, en tussen twee runs mag een gebruiker stoppen: de
    export eindigt binnen die ene run en er blijft geen halve PDF achter die voor een rapport kan
    doorgaan."""
    from desktopstudie.core.study import StudyCancelled
    from desktopstudie.qgis import export

    polled = []

    def stop_after_the_first_run():
        polled.append(True)
        return len(polled) > 1

    with pytest.raises(StudyCancelled):
        export.export_pdf(three_pages, tmp_path / "half.pdf", pages_per_run=1,
                          should_cancel=stop_after_the_first_run)

    assert not (tmp_path / "half.pdf").exists()
    # De layout verlaat de afgebroken export zoals ze erin ging.
    pages = three_pages.pageCollection()
    assert not any(pages.page(index).excludeFromExports() for index in range(pages.pageCount()))


def test_the_export_says_how_many_sheets_are_done_after_every_run(three_pages, tmp_path):
    """Een voortgangsbalk die een halve minuut op "PDF-export" blijft staan zegt niets; na elke
    run hoort de export te melden hoeveel bladen er staan, van hoeveel."""
    from desktopstudie.qgis import export

    done = []

    export.export_pdf(three_pages, tmp_path / "rapport.pdf", pages_per_run=2,
                      progress=lambda sheets, total: done.append((sheets, total)))

    assert done == [(2, 3), (3, 3)]


def test_a_failed_pdf_export_says_which_result_it_got(three_pages, tmp_path):
    """Een export die mislukt, hoort te knallen met de naam van de fout, niet met een kale 3.
    Schrijven naar een bestaande map kan niet, en dat is precies zo'n geval: QGIS noemt dat
    PrintError (de printer gaat niet open op een map) - een naam, geen nummer."""
    import re

    from desktopstudie.qgis import export

    with pytest.raises(RuntimeError) as failure:
        export.export_pdf(three_pages, tmp_path)

    assert re.search(r"\((\w+Error)\)", str(failure.value)), str(failure.value)


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
