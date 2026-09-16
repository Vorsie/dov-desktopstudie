"""De layout uit de rapportboom: een pagina per rapportpagina, aparte legendapagina's achter elke
kaart die er een vraagt, de extentregel van een kaartpagina en wat er gebeurt als een tabel niet
op een blad past.

Bijna alles offline: de "WMS-laag" is een memory-laag en de legenda is een zelfgemaakte PNG, zodat
de test niets van een service verwacht. Alleen de legenda-ophaler heeft een live variant, want
alleen de echte GeoServer bewijst dat de GetLegendGraphic-URL klopt."""
from __future__ import annotations

import pytest

from tests.qgis.conftest import report_meta as _meta
from tests.qgis.conftest import write_png as _png

MAP_ID = "grb"  # een echte catalogusentry: de layout leest er titel, attributie en licentie uit
ZONE_WIDTH_M = 100.0  # de Gent-zone is een cirkel van 50 m straal
MARGIN = 15.0
TABLE_COLUMNS = ["Eenheid", "Top (mTAW)", "Basis (mTAW)"]
FIGURE_REL = "figuren/sondering.png"


def _report(pages):
    from desktopstudie.core.report_content import Chapter, Report

    return Report(title="Desktopstudie testproject", meta={}, chapters=[Chapter(1, "Test", pages)])


def _standard_pages():
    from desktopstudie.core.report_content import FigurePage, MapPage, TablePage, TextPage

    return [
        MapPage(MAP_ID, "Ligging op de GRB-basiskaart", legend=True, scale=2500, extent_factor=3.0),
        FigurePage("Sondering GEO-01", FIGURE_REL, caption="Sondering nabij de zone"),
        TablePage("Lagen", list(TABLE_COLUMNS),
                  [[f"laag {i}", f"{10 - i}.00", f"{9 - i}.00"] for i in range(4)],
                  note="Modelwaarden, geen terreinmeting."),
        TextPage("Bronnen", "<p>DOV en geopunt, opgehaald op 2026-09-15.</p>"),
    ]


@pytest.fixture
def make_layout(project, gent_zone, tmp_path):
    """Bouwt een layout uit opgegeven rapportpagina's, met een memory-laag als "WMS-laag"."""
    from desktopstudie.qgis import layers, layout

    _png(tmp_path / FIGURE_REL)
    wms_stand_in = layers.zone_layer(gent_zone)
    wms_stand_in.setName("GRB-basiskaart")
    project.addMapLayer(wms_stand_in, False)
    zone = layers.zone_layer(gent_zone)
    project.addMapLayer(zone, False)

    def build(pages=None, legends=True, legend_images=None, overlays=None, no_coverage=None):
        if legend_images is None:
            legend_images = {MAP_ID: _png(tmp_path / "legendas" / f"{MAP_ID}.png", 120, 300)}
        merged = {"zone": [zone]}
        merged.update(overlays or {})
        return layout.build_layout(project, _report(_standard_pages() if pages is None else pages),
                                   merged, tmp_path, gent_zone.ring,
                                   _meta(), legends=legends, legend_images=legend_images,
                                   no_coverage=no_coverage)

    return build


def _items_of(lay, index, cls):
    return [item for item in lay.pageCollection().itemsOnPage(index) if isinstance(item, cls)]


def _footers_on(lay, index):
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    return [lbl for lbl in _items_of(lay, index, QgsLayoutItemLabel) if lbl.id() == layout.FOOTER_ID]


# --- paginastructuur -------------------------------------------------------------------------

def test_a_page_per_report_page_plus_a_title_page_and_a_legend_page(make_layout):
    """Titelblad + vier rapportpagina's + een legendapagina, want de kaart vraagt een legenda."""
    lay = make_layout()
    assert lay.pageCollection().pageCount() == 1 + 4 + 1


def test_without_legends_no_legend_pages_are_made(make_layout):
    """De schakelaar van de plugin/CLI: geen legendapagina's, de rest ongewijzigd."""
    lay = make_layout(legends=False)
    assert lay.pageCollection().pageCount() == 1 + 4


def test_a_map_without_a_fetched_legend_gets_no_legend_page(make_layout):
    """Een legenda die niet opgehaald raakte, levert geen lege pagina op - dat zou de lezer een
    legenda beloven die er niet is."""
    lay = make_layout(legend_images={})
    assert lay.pageCollection().pageCount() == 1 + 4


def test_every_page_is_a4_portrait(make_layout):
    """Van kaft tot kaft staand A4. `QgsPrintLayout.initializeDefaults()` legt zijn eerste pagina
    liggend neer, en op een liggend titelblad valt alles onder 210 mm - de inhoudsopgave, de
    disclaimer - gewoon van het papier af."""
    from desktopstudie.qgis import compat

    lay = make_layout()
    collection = lay.pageCollection()
    for index in range(collection.pageCount()):
        size = collection.page(index).pageSize()
        assert size.units() == compat.MM
        assert size.width() == pytest.approx(210.0, abs=0.5), f"pagina {index} is niet 210 mm breed"
        assert size.height() == pytest.approx(297.0, abs=0.5), f"pagina {index} is niet 297 mm hoog"


def test_every_page_carries_exactly_one_footer(make_layout):
    """Elke pagina draagt haar eigen voettekst met het paginanummer. Twee voetteksten betekent dat
    twee rapportpagina's op hetzelfde blad zijn beland; nul betekent een blad dat uit het niets
    opdook - allebei gaten die je pas in de PDF ziet."""
    lay = make_layout()
    for index in range(lay.pageCollection().pageCount()):
        assert len(_footers_on(lay, index)) == 1, f"pagina {index}"


# --- overlopende tabel -----------------------------------------------------------------------

def _long_table_report():
    from desktopstudie.core.report_content import TablePage, TextPage

    return [TablePage("Lange tabel", list(TABLE_COLUMNS),
                      [[f"laag {i}", f"{i}.00", f"{i + 1}.00"] for i in range(200)],
                      note="Tweehonderd rijen passen op geen enkel blad."),
            TextPage("Bronnen", "<p>Na de tabel.</p>")]


def test_every_footer_carries_its_own_sheet_number_and_the_total_as_text(make_layout):
    """"pagina 23 / 115" hoort letterlijk in de voettekst te staan, niet als expressie. De bladen
    gaan in runs naar de exporter, en in een run telt QGIS' @layout_numpages alleen de bladen van
    die run: "pagina 1 / 1" op elk blad. De nummering hoort bij de layout, niet bij de export, dus
    ze wordt geschreven zodra de layout compleet is - ook op de vervolgbladen van een tabel."""
    lay = make_layout(pages=_long_table_report())
    total = lay.pageCollection().pageCount()

    assert total > 3
    for index in range(total):
        footer = _footers_on(lay, index)
        assert len(footer) == 1, f"blad {index + 1}"
        assert footer[0].text().endswith(f"pagina {index + 1} / {total}"), footer[0].text()
        assert "[%" not in footer[0].text(), "de voettekst hoort tekst te zijn, geen expressie"


def test_a_table_that_runs_on_does_not_land_on_the_next_report_page(make_layout):
    """Een tabel van 200 rijen maakt zelf pagina's bij. Wie daarna verder telt met een eigen
    teller, zet de volgende rapportpagina bovenop de laatste tabelpagina: tekst dwars door de
    tabel heen. De volgende rapportpagina hoort na alles van de tabel te beginnen."""
    from qgis.core import QgsLayoutFrame, QgsLayoutItemLabel

    lay = make_layout(pages=_long_table_report())
    collection = lay.pageCollection()
    text_pages = []
    for index in range(collection.pageCount()):
        on_page = [lbl.text() for lbl in _items_of(lay, index, QgsLayoutItemLabel)]
        if any("Na de tabel" in text for text in on_page):
            text_pages.append(index)
            assert not _items_of(lay, index, QgsLayoutFrame), f"de tekstpagina deelt blad {index}"
    assert len(text_pages) == 1
    assert text_pages[0] == collection.pageCount() - 1, "de tekstpagina hoort de laatste te zijn"


def test_a_table_that_runs_on_keeps_a_header_and_a_footer_on_every_page(make_layout):
    """Een vervolgblad zonder kop is een losse brok cijfers: de lezer weet niet meer waar hij is.
    Elk vervolgblad krijgt dezelfde kop met "(vervolg)" en een eigen voettekst."""
    from qgis.core import QgsLayoutFrame, QgsLayoutItemLabel

    lay = make_layout(pages=_long_table_report())
    collection = lay.pageCollection()
    continued = []
    for index in range(collection.pageCount()):
        if not _items_of(lay, index, QgsLayoutFrame):
            continue
        texts = [lbl.text() for lbl in _items_of(lay, index, QgsLayoutItemLabel)]
        assert len(_footers_on(lay, index)) == 1, f"pagina {index} mist een voettekst"
        if any("(vervolg)" in text for text in texts):
            continued.append(index)
        else:
            assert any("Lange tabel" in text for text in texts), f"pagina {index} mist een kop"
    assert continued, "een tabel van 200 rijen hoort vervolgbladen te maken"


# --- kaartpagina -----------------------------------------------------------------------------

def test_the_map_page_carries_the_map_scale_bar_arrow_and_info_boxes_but_no_legend(make_layout):
    from qgis.core import (
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
    )

    lay = make_layout()
    maps = _items_of(lay, 1, QgsLayoutItemMap)
    bars = _items_of(lay, 1, QgsLayoutItemScaleBar)
    assert len(maps) == 1 and len(bars) == 1
    assert bars[0].linkedMap().uuid() == maps[0].uuid()
    assert len(_items_of(lay, 1, QgsLayoutItemPicture)) == 1  # de noordpijl
    framed = [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]
    assert len(framed) == 2  # bron/schaal rechtsboven en attributie/licentie rechtsonder
    # De legenda staat op haar eigen pagina: op de kaartpagina hoort ze niet.
    assert _items_of(lay, 1, QgsLayoutItemLegend) == []


def test_the_info_boxes_are_readable_over_the_map(make_layout):
    """Een infovak staat bovenop de kaart. Zonder eigen achtergrond leest de tekst over gevels en
    straatnamen heen, en zonder marge plakt ze tegen het kader."""
    from qgis.core import QgsLayoutItemLabel

    lay = make_layout()
    framed = [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]
    assert framed
    for box in framed:
        assert box.hasBackground(), f"infovak zonder achtergrond: {box.text()[:40]!r}"
        assert box.backgroundColor().alpha() == 255
        assert box.marginX() > 0 and box.marginY() > 0


def test_the_info_boxes_stay_inside_the_right_margin(make_layout):
    """De vakjes krimpen naar hun inhoud en groeien daarbij naar links, niet over de bladrand: een
    bronvermelding die half buiten het papier valt, is geen bronvermelding."""
    from qgis.core import QgsLayoutItemLabel

    lay = make_layout()
    for box in [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]:
        # pos()/rect() geven de echte hoeken; pagina's liggen onder elkaar op x=0, dus de x van de
        # scene is ook de x op het blad. pagePositionWithUnits() zou het referentiepunt geven.
        right = box.pos().x() + box.rect().width()
        assert right == pytest.approx(195.0, abs=1.0), f"{box.text()[:30]!r} loopt tot {right} mm"
        assert box.pos().x() > MARGIN, "een infovak hoort rechts op de kaart te staan"


def test_a_long_source_line_makes_its_info_box_taller(project, gent_zone, tmp_path):
    """Een lange bronregel breekt binnen het vakje af. Wie alleen de losse regels meet en het
    afbreken vergeet, maakt het vakje een regel te kort en laat de laatste regel onder het kader
    uithangen - precies op de bronvermelding."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layout

    def source_box_height(map_id):
        lay = layout.build_layout(project, _report([MapPage(map_id, "Kaart", legend=False)]),
                                  {}, tmp_path, gent_zone.ring, _meta())
        boxes = [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]
        source = max(boxes, key=lambda box: box.pos().y())  # het bronvak staat onderaan de kaart
        return source.rect().height()

    # ortho draagt de langste bronvermelding van de catalogus, grb een van de kortste
    assert source_box_height("ortho") > source_box_height("grb")


def test_the_north_arrow_is_readable_over_the_map(make_layout):
    """Een zwarte pijl op een donker luchtfotodak is onzichtbaar; hij krijgt een eigen wit vlak."""
    from qgis.core import QgsLayoutItemPicture

    lay = make_layout()
    arrow = _items_of(lay, 1, QgsLayoutItemPicture)[0]
    assert arrow.hasBackground()
    assert arrow.backgroundColor().alpha() == 255


def test_the_extent_is_the_wider_of_the_target_scale_and_the_zone(project, gent_zone, tmp_path):
    """`MapPage.scale` is een doelschaal. Bij 1:2500 toont het kaartitem van 180 mm 450 m; drie
    keer een zone van 100 m is minder, dus de schaal wint. Tien keer die zone is 1000 m en die
    wint, want anders valt de zone buiten beeld."""
    from desktopstudie.qgis import layout

    builder = layout.LayoutBuilder(project, _report([]), {}, tmp_path, gent_zone.ring, _meta())
    assert builder.map_extent(2500, 3.0).width() == pytest.approx(layout.MAP_W / 1000.0 * 2500, abs=0.5)
    assert builder.map_extent(2500, 3.0).width() == pytest.approx(450.0, abs=0.5)
    assert builder.map_extent(2500, 10.0).width() == pytest.approx(ZONE_WIDTH_M * 10.0, abs=0.5)
    assert builder.map_extent(2500, 10.0).width() == pytest.approx(1000.0, abs=0.5)
    # het kaartitem is hoger dan breed, dus de extent ook
    wide = builder.map_extent(2500, 10.0)
    assert wide.height() == pytest.approx(wide.width() * layout.MAP_H / layout.MAP_W, abs=0.5)


def test_the_extent_also_holds_what_the_page_asked_to_draw(project, gent_zone, tmp_path):
    """Vraagt een pagina om het grondonderzoek, dan hoort de Zoekstraal er helemaal op te staan.
    Een kaart die de zoekcirkel afsnijdt, laat de lezer denken dat er verderop niets gezocht is."""
    from desktopstudie.qgis import layers, layout

    search_area = layers.circle_layer(gent_zone)  # 500 m rond de zone van 50 m
    builder = layout.LayoutBuilder(project, _report([]), {}, tmp_path, gent_zone.ring, _meta())

    tight = builder.map_extent(2500, 3.0)
    wide = builder.map_extent(2500, 3.0, [search_area])

    assert not tight.contains(search_area.extent()), "zonder overlays past de zoekcirkel niet"
    assert wide.contains(search_area.extent())


def test_a_map_widened_for_its_overlays_lands_on_a_round_scale(project, gent_zone, tmp_path):
    """Rekt een kaart open tot de zoekstraal erop past, dan rolt daar een willekeurige schaal uit
    (1:6 104). De lezer hoort een schaal van de 1-2-5-ladder te zien, naar boven afgerond zodat de
    kaart alleen ruimer wordt - de zoekcirkel staat er daarna nog altijd volledig op."""
    from desktopstudie.qgis import layers, layout

    search_area = layers.circle_layer(gent_zone)  # 500 m rond de zone van 50 m
    builder = layout.LayoutBuilder(project, _report([]), {}, tmp_path, gent_zone.ring, _meta())

    extent = builder.map_extent(5000, 1.0, [search_area])  # de overzichtspagina van hoofdstuk 5

    assert extent.width() / (layout.MAP_W / 1000.0) == pytest.approx(10000, abs=1)
    assert extent.contains(search_area.extent())


def test_a_map_that_was_not_widened_keeps_the_catalogue_scale(project, gent_zone, tmp_path):
    """Past alles op de doelschaal, dan blijft die staan: de catalogusschaal is een keuze, geen
    tussenstap die naar de ladder mag worden getrokken."""
    from desktopstudie.qgis import layout

    builder = layout.LayoutBuilder(project, _report([]), {}, tmp_path, gent_zone.ring, _meta())

    assert builder.map_extent(2500, 3.0).width() == pytest.approx(450.0, abs=0.5)


def test_the_info_box_prints_the_rounded_scale(project, gent_zone, tmp_path):
    """Wat de lezer op het blad ziet: 1:10 000, niet 1:6 104."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layers, layout

    page = MapPage(MAP_ID, "Overzicht beschikbaar grondonderzoek", legend=False, scale=5000,
                   extent_factor=1.0, show_investigations=True)
    overlays = {"zone": [layers.zone_layer(gent_zone)],
                "investigations": [layers.circle_layer(gent_zone)]}
    lay = layout.build_layout(project, _report([page]), overlays, tmp_path, gent_zone.ring, _meta())

    texts = [lbl.text() for lbl in _items_of(lay, 1, QgsLayoutItemLabel)]
    assert any("schaal 1:10 000" in text for text in texts), texts


# --- legendapagina's -------------------------------------------------------------------------

def test_the_legend_page_shows_the_fetched_image_and_is_switchable(make_layout):
    from qgis.core import QgsLayoutItemLegend, QgsLayoutItemPicture, QgsLayoutObject

    lay = make_layout()
    page_item = lay.pageCollection().page(2)
    assert page_item.id() == f"legenda-{MAP_ID}"
    # Geen QgsLayoutItemLegend: die haalt een WMS-legenda asynchroon op en blijft headless leeg.
    assert _items_of(lay, 2, QgsLayoutItemLegend) == []
    pictures = _items_of(lay, 2, QgsLayoutItemPicture)
    assert len(pictures) == 1 and pictures[0].picturePath().endswith(f"{MAP_ID}.png")
    prop = page_item.dataDefinedProperties().property(QgsLayoutObject.DataDefinedProperty.ExcludeFromExports)
    assert prop.expressionString() == "@legendas = 0"


def test_a_legend_taller_than_a_page_is_cut_into_page_sized_strips(make_layout, tmp_path):
    """Een legenda van honderden klassen is een lange smalle strook. In een kader geperst wordt ze
    onleesbaar klein; ze hoort in bladhoge stroken op opeenvolgende pagina's."""
    from qgis.core import QgsLayoutItemPicture, QgsLayoutObject

    tall = _png(tmp_path / "legendas" / f"{MAP_ID}.png", 200, 3000)
    lay = make_layout(legend_images={MAP_ID: tall})
    collection = lay.pageCollection()
    legend_pages = [index for index in range(collection.pageCount())
                    if collection.page(index).id().startswith(f"legenda-{MAP_ID}")]

    assert len(legend_pages) >= 2, "een strook van 3000 px hoort niet op een blad te passen"
    for number, index in enumerate(legend_pages, start=1):
        assert collection.page(index).id() == f"legenda-{MAP_ID}-{number}"
        assert len(_items_of(lay, index, QgsLayoutItemPicture)) == 1
        prop = collection.page(index).dataDefinedProperties().property(
            QgsLayoutObject.DataDefinedProperty.ExcludeFromExports)
        assert prop.expressionString() == "@legendas = 0", f"blad {index} volgt de schakelaar niet"


def _striped_png(path, width=200, blocks=100, block_h=30, gap_h=6):
    """Een legenda zoals een GeoServer ze tekent: gekleurde regels van 30 px, telkens gescheiden
    door een witte tussenruimte van 6 px. Elke gekleurde regel is een legenda-item."""
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    image = QImage(width, blocks * (block_h + gap_h), QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    for number in range(blocks):
        painter.fillRect(0, number * (block_h + gap_h), width, block_h, QColor(20, 90 + number % 150, 160))
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def _row_is_white(image, y):
    from qgis.PyQt.QtGui import QColor

    return all(image.pixelColor(x, y) == QColor(255, 255, 255) for x in range(image.width()))


def test_a_strip_boundary_never_runs_through_a_legend_item(qgs_app, tmp_path):
    """Een snede mag geen legenda-item halveren: waar het blad vol is, hoort ze in de witte
    tussenruimte boven dat item te vallen, niet dwars door de gekleurde regel die daar ligt."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import layout

    source = _striped_png(tmp_path / "legendas" / "gxg_ghg.png")
    strips = layout._legend_strips(source, "gxg_ghg")

    assert len(strips) >= 2, "een strook van 3600 px hoort niet op een blad te passen"
    heights = []
    for number, (strip_path, _width, _height) in enumerate(strips, start=1):
        image = QImage(str(strip_path))
        heights.append(image.height())
        if number < len(strips):
            assert _row_is_white(image, image.height() - 1), f"strook {number} eindigt in een item"
    assert sum(heights) == QImage(str(source)).height(), "de stroken samen zijn de hele legenda"


def test_a_legend_without_any_blank_row_is_still_cut(qgs_app, tmp_path):
    """Geen witte rij te vinden? Dan wint het blad: snijden op de nominale hoogte, want een strook
    die nergens wordt afgebroken past op geen enkele pagina."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import layout

    solid = _striped_png(tmp_path / "legendas" / "vol.png", blocks=1, block_h=3600, gap_h=0)
    strips = layout._legend_strips(solid, "vol")

    assert len(strips) >= 2
    assert sum(QImage(str(path)).height() for path, _w, _h in strips) == 3600


def test_the_legend_switch_drops_the_pages_from_a_real_export(make_layout, tmp_path):
    """De schakelaar moet in de echte export gelden, niet alleen in de expressie: zet `legendas`
    op 0 en er komt precies een pagina minder uit."""
    from qgis.core import QgsExpressionContextUtils, QgsLayoutExporter

    lay = make_layout()
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 48

    out_on = tmp_path / "aan"
    out_on.mkdir()
    assert QgsLayoutExporter(lay).exportToImage(str(out_on / "p.png"), settings) == QgsLayoutExporter.Success
    with_legends = len(list(out_on.glob("p*.png")))

    QgsExpressionContextUtils.setLayoutVariable(lay, "legendas", 0)
    lay.refresh()
    out_off = tmp_path / "uit"
    out_off.mkdir()
    assert QgsLayoutExporter(lay).exportToImage(str(out_off / "p.png"), settings) == QgsLayoutExporter.Success
    without_legends = len(list(out_off.glob("p*.png")))

    assert with_legends == 6
    assert without_legends == with_legends - 1


# --- legenda-URL en ophalen ------------------------------------------------------------------

def test_the_legend_url_asks_for_the_style_and_the_column_layout():
    """Een legenda hoort bij een laag en bij een stijl: gxg zonder stijl tekent een andere legenda
    dan de kaart. LEGEND_OPTIONS houdt de klassen in kolommen in plaats van in een strook."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layout

    entry = catalogue.by_id("gxg_ghg")
    url = layout.wms_legend_url(entry, entry.legend_options)

    assert "REQUEST=GetLegendGraphic" in url and "VERSION=1.3.0" in url
    # the workspace service, on which the layer goes by its bare name; the style keeps its prefix
    assert url.startswith("https://www.dov.vlaanderen.be/geoserver/gxg/wms?")
    assert "LAYER=ghg_mmv_main&" in url
    assert "STYLE=gxg%3Agxg" in url or "STYLE=gxg:gxg" in url
    assert "LEGEND_OPTIONS=" in url and "columns" in url
    assert "LEGEND_OPTIONS" not in layout.wms_legend_url(entry, "")


def test_a_legend_that_cannot_be_fetched_is_reported_not_swallowed(qgs_app, tmp_path):
    """Een bron die faalt, faalt luid: geen pad terug en een WARNING."""
    from dataclasses import replace

    from desktopstudie.core import catalogue
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    entry = replace(catalogue.by_id("gxg_ghg"), wms_url="http://127.0.0.1:9/wms")
    lines = []
    client = HttpClient(cache_dir=None, timeout=1.0, retries=0, sleep=lambda _s: None)

    assert layout.fetch_legend(entry, tmp_path, client, Log("layout", lines.append, scope="qgis")) is None
    assert any("WARNING" in line for line in lines), lines


def test_prepare_legends_skips_maps_without_a_legend(qgs_app, tmp_path):
    """Kaarten met legend=False worden niet opgehaald - de bodemkaart alleen al zou een strook van
    duizenden pixels binnenhalen die nergens op past."""
    from desktopstudie.core import catalogue
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    asked = []
    blob = _png(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            return blob

    entries = [catalogue.by_id("bodemkaart"), catalogue.by_id("gxg_ghg")]
    images, missing = layout.prepare_legends(entries, tmp_path, _Client(cache_dir=None))

    assert list(images) == ["gxg_ghg"]
    assert missing == []
    assert len(asked) == 1 and "ghg_mmv_main" in asked[0][0]
    # Een legenda is één plaatje van veertien: een korte adem, net als een fiche. Drie keer een
    # volle minuut wachten op een dienst die plat ligt, kost het rapport zijn legendapagina's.
    assert asked[0][1:] == (layout.LEGEND_TIMEOUT_S, layout.LEGEND_RETRIES)


@pytest.mark.live
def test_live_the_gxg_legend_is_a_real_png(qgs_app, tmp_path):
    from desktopstudie.core import catalogue
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    path = layout.fetch_legend(catalogue.by_id("gxg_ghg"), tmp_path, HttpClient(cache_dir=None))

    assert path is not None and path.exists()
    assert path.stat().st_size > 1024
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --- legenda's van de zone (profieltypes van het Quartair) ------------------------------------

def _quartair_result(gent_zone, codes):
    from desktopstudie.core.model import StudyResult
    from tests import quartair

    result = StudyResult(zone=gent_zone, created_at="2026-09-15T10:00:00")
    result.map_facts = [quartair.map_fact(codes)]
    return result


def _profile_drawing(path, width=980, header_h=103, gap_h=14, body_h=586):
    """Een profieltypetekening zoals DOV ze levert: bovenaan het profieltype zelf (kleurvlak, code
    en een regel uitleg), dan een witte tussenruimte, dan de eenhedentabel van het kaartblad."""
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    image = QImage(width, header_h + gap_h + body_h, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.fillRect(0, 0, 120, 24, QColor(0, 0, 0))            # "Profieltype"
    painter.fillRect(0, 34, 130, header_h - 34, QColor(200, 198, 170))  # kleurvlak + omschrijving
    painter.fillRect(0, header_h + gap_h, width, body_h, QColor(40, 40, 40))  # eenhedentabel
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def test_the_profile_type_drawings_are_fetched_once_per_type(qgs_app, tmp_path, gent_zone):
    """De echte legenda van de Quartairkaart is een tekening per profieltype. Twee kaartvlakken van
    hetzelfde type vragen om een tekening, en een tekening die de dienst niet levert, levert geen
    bestand op - een lege figuurpagina belooft de lezer een legenda die er niet is."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.report_content import profile_image_key, sheet_image_key
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import layout

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            if url.endswith("22098_png"):
                raise HttpError(url, 500, "dienst plat")
            return blob

    lines = []
    result = _quartair_result(gent_zone, ["22026", "22010", "22026", "22098"])

    images = layout.prepare_zone_legend_images(result, tmp_path, _Client(cache_dir=None),
                                               Log("layout", lines.append, scope="qgis"))

    # Een kopstrook per profieltype, en de eenhedentabel een keer voor het hele kaartblad.
    assert set(images) == {profile_image_key("22026"), profile_image_key("22010"),
                           sheet_image_key("22")}
    assert images[profile_image_key("22026")].name == "quartair_22026_kop.png"
    assert images[sheet_image_key("22")].name == "quartair_kaartblad_22.png"
    # De eenhedentabel van het blad houdt alles behalve de kop van het profieltype waarmee ze
    # binnenkwam; die kop staat al op de legendapagina.
    assert images[sheet_image_key("22")].read_bytes() != blob
    assert len(asked) == 3, "hetzelfde profieltype wordt niet twee keer opgehaald"
    # Dezelfde korte adem als een gewone legenda: een dienst die plat ligt mag het rapport geen
    # drie volle minuten kosten.
    assert asked[0][1:] == (layout.LEGEND_TIMEOUT_S, layout.LEGEND_RETRIES)
    assert any("WARNING" in line for line in lines), lines


def test_the_header_strip_is_cut_above_the_units_table(qgs_app, tmp_path, gent_zone):
    """De kopstrook is het deel dat per profieltype verschilt; de eenhedentabel eronder is voor elk
    type van hetzelfde kaartblad dezelfde. De snede valt in de witte band ertussen, dus de strook
    is korter dan de tekening en breder dan hoog."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    images = layout.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    header = QImage(str(images[profile_image_key("22026")]))
    whole = QImage(str(tmp_path / "bron.png"))
    assert header.width() == whole.width()
    assert header.height() < whole.height() / 2, "de eenhedentabel hoort er niet meer op te staan"
    assert header.height() > 60, "het kleurvlak en de omschrijving horen er wel op te staan"
    assert header.width() > header.height()


def test_the_sheet_drawing_loses_the_profile_header(qgs_app, tmp_path, gent_zone):
    """De eenhedentabel geldt voor elk profieltype van het blad. Stond de kop van profieltype 22010
    er nog boven, dan leest ze als de tabel van dat ene type - dus die kop gaat eraf, en de bronregel
    onder de tabel blijft staan."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.core.report_content import profile_image_key, sheet_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    images = layout.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    whole = QImage(str(tmp_path / "bron.png"))
    header = QImage(str(images[profile_image_key("22026")]))
    units = QImage(str(images[sheet_image_key("22")]))
    assert units.width() == whole.width()
    assert units.height() == whole.height() - header.height(), "precies de kop eraf"
    assert units.height() > whole.height() / 2, "de tabel zelf staat er nog helemaal op"


def test_an_answer_that_is_no_image_is_asked_again_past_the_cache(qgs_app, tmp_path, gent_zone):
    """De legenda-URL's van DOV zijn downloadlinks die soms met HTTP 200 de webpagina van de dienst
    teruggeven in plaats van het bestand (live gezien op 2026-09-16). Die pagina als PNG
    wegschrijven levert een figuurpagina met een leeg kader, en in de schijfcache zou ze elke
    volgende run bederven - dus wordt er nog een keer gevraagd, langs de cache heen."""
    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append(cache_mode)
            return b"<html><body>DSpace</body></html>" if len(asked) == 1 else blob

    images = layout.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert profile_image_key("22026") in images
    assert asked == [None, "refresh"], "de herkansing hoort de cache over te slaan"


def test_an_answer_that_is_never_an_image_is_not_saved_as_one(qgs_app, tmp_path, gent_zone):
    """Blijft de dienst haar webpagina geven, dan komt er geen bestand en geen figuurpagina - een
    mislukte bron, geen leeg kader."""
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return b"<html><body>Service unavailable</body></html>"

    images = layout.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert images == {}
    assert not (tmp_path / "legendas" / "quartair_22026.png").exists()


def test_a_study_without_quartair_rows_asks_for_nothing(qgs_app, tmp_path, gent_zone):
    from desktopstudie.core.model import StudyResult
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            raise AssertionError(f"niets op te halen, en toch gevraagd: {url}")

    assert layout.prepare_zone_legend_images(
        StudyResult(zone=gent_zone, created_at="t"), tmp_path, _Client(cache_dir=None)) == {}


# --- overige pagina's ------------------------------------------------------------------------

def test_the_table_page_has_a_frame_the_columns_and_runs_on(make_layout):
    from qgis.core import QgsLayoutFrame, QgsLayoutMultiFrame

    lay = make_layout()
    frames = _items_of(lay, 4, QgsLayoutFrame)
    assert frames, "geen tabelframe op de tabelpagina"
    table = frames[0].multiFrame()
    assert table.frameCount() >= 1
    assert [column.heading() for column in table.columns()] == TABLE_COLUMNS
    # Een tabel die niet op een pagina past, moet doorlopen in plaats van afgekapt te worden.
    assert table.resizeMode() == QgsLayoutMultiFrame.ResizeMode.ExtendToNextPage


def test_the_figure_page_shows_the_png_and_captions_it_underneath(make_layout, tmp_path):
    """Het onderschrift hoort tegen de figuur aan te staan, niet onderaan het blad: een vierkante
    figuur vult maar de helft van het kader en laat anders een gat van tien centimeter."""
    from qgis.core import QgsLayoutItemLabel, QgsLayoutItemPicture

    lay = make_layout()
    pictures = _items_of(lay, 3, QgsLayoutItemPicture)
    assert len(pictures) == 1
    assert pictures[0].picturePath() == str(tmp_path / FIGURE_REL)
    bottom = pictures[0].pagePositionWithUnits().y() + pictures[0].sizeWithUnits().height()
    caption = next(lbl for lbl in _items_of(lay, 3, QgsLayoutItemLabel)
                   if "Sondering nabij" in lbl.text())
    assert bottom < caption.pagePositionWithUnits().y() < bottom + 6


def test_the_title_page_names_the_report_and_lists_the_chapters(make_layout):
    from qgis.core import QgsLayoutItemLabel

    lay = make_layout()
    texts = [lbl.text() for lbl in _items_of(lay, 0, QgsLayoutItemLabel)]
    assert any("Desktopstudie testproject" in text for text in texts)
    assert any("1. Test" in text for text in texts)
    assert any("Testbureau" in text for text in texts)


def test_the_footer_leaves_out_what_the_study_does_not_know(project, gent_zone, tmp_path):
    """Een studie zonder bedrijfsnaam hoort geen voettekst te krijgen die met een streepje begint."""

    from desktopstudie.qgis import layout

    lay = layout.build_layout(project, _report([]), {}, tmp_path, gent_zone.ring,
                              {"project": "", "company": "", "created_at": "2026-09-15T10:00:00"})
    footer = _footers_on(lay, 0)[0]
    assert footer.text().startswith("pagina ")


# --- brede tabellen --------------------------------------------------------------------------

def _sonderingen_page():
    """De echte sonderingentabel: negen kolommen, gevuld met opgeslagen DOV-antwoorden. De lange
    uitvoerdersnaam ("Rijksinstituut voor Grondmechanica (RIG)") is wat de tabel van het blad
    duwde."""
    from desktopstudie.core.model import Cpt, StudyResult, StudyZone
    from desktopstudie.core.report_content import ReportMeta, TablePage, build_report
    from tests.core.conftest import fixture_json

    features = fixture_json("wfs_sonderingen_dwithin.json")["features"]
    cpts = []
    for number, feature in enumerate(features):
        p = feature["properties"]
        url = p["fiche"]
        cpts.append(Cpt(permkey=url.rsplit("/", 1)[-1], number=p["sondeernummer"], x=p["X_mL72"], y=p["Y_mL72"],
                        z_mtaw=p.get("Z_mTAW"), depth_m=p.get("diepte_tot_m"), date=p.get("datum_aanvang"),
                        method=p.get("sondeermethode"), cone=p.get("conus"), contractor=p.get("uitvoerder"),
                        project=p.get("opdrachten"), url=url, distance_m=float(number * 37)))
    zone = StudyZone(ring=[(104226.0, 192406.0), (104426.0, 192406.0), (104426.0, 192606.0)], name="z")
    result = StudyResult(zone=zone, created_at="2026-09-15T10:00:00", cpts=cpts)
    report = build_report(result, ReportMeta(project="T", author="A", company="B"))
    pages = [p for chapter in report.chapters for p in chapter.pages if isinstance(p, TablePage)]
    return next(p for p in pages if p.title.startswith("Sonderingen"))


def _signaleringen_page():
    """De signaleringentabel: vier kolommen met hele zinnen erin, letterlijk uit een echte studie
    (Gent, 2026-09-15). Die moeten afbreken binnen hun kolom in plaats van eruit te lopen."""
    from desktopstudie.core.report_content import TablePage

    return TablePage("Signaleringen", ["Feit", "Bron", "Aandachtspunt", "Ernst"], [
        ["Maaiveld varieert van 12.5 tot 16.2 mTAW in de zone.", "DHMV II",
         "Aandachtspunt voor het grondonderzoek: reliefverschil; niveaus van proeven nauwkeurig inmeten.",
         "aandacht"],
        ["Krimp-zwelgevoelige grond binnen de zone: Formatie van Kortrijk (klei).",
         "DOV - plastische gronden",
         "Funderingsniveau en vochthuishouding beoordelen; zettingen door krimp en zwel mogelijk.",
         "aandacht"],
        ["3 sondering(en) binnen 50 m van de zone.", "DOV",
         "Bestaande data bruikbaar als referentie voor het onderzoeksprogramma.", "info"]])


def _table_of(lay):
    from qgis.core import QgsLayoutItemTextTable

    return [frame for frame in lay.multiFrames() if isinstance(frame, QgsLayoutItemTextTable)][0]


def test_a_wide_table_lands_on_a_landscape_sheet_with_every_column_on_it(project, gent_zone, tmp_path):
    """Negen kolommen passen niet op een staand blad: de laatste ("DOV-fiche") viel eraf en de
    uitvoerder werd halverwege afgekapt. Zo'n tabel hoort liggend, met expliciete kolombreedtes
    die samen binnen de bladbreedte blijven, en met alle negen koppen erop."""
    from qgis.core import QgsLayoutItemPage

    from desktopstudie.qgis import layout

    page = _sonderingen_page()
    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    sheet = lay.pageCollection().page(1)
    metrics = layout._page_metrics(QgsLayoutItemPage.Orientation.Landscape)
    assert sheet.pageSize().width() > sheet.pageSize().height(), "brede tabel hoort liggend"
    table = _table_of(lay)
    assert [column.heading() for column in table.columns()] == page.columns
    assert all(column.width() > 0 for column in table.columns()), "elke kolom krijgt een eigen breedte"
    assert table.totalWidth() <= metrics.content_w + 0.5, f"{table.totalWidth()} mm past niet"
    assert table.frames()[0].rect().width() <= metrics.content_w + 0.5


def test_a_narrow_table_stays_portrait_and_wraps_its_long_sentences(project, gent_zone, tmp_path):
    """Vier kolommen met hele zinnen: die horen binnen hun kolom af te breken, niet buiten het
    blad door te lopen - en het blad blijft staand."""
    from qgis.core import QgsLayoutItemPage, QgsLayoutTable

    from desktopstudie.qgis import layout

    page = _signaleringen_page()
    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    sheet = lay.pageCollection().page(1)
    metrics = layout._page_metrics(QgsLayoutItemPage.Orientation.Portrait)
    assert sheet.pageSize().height() > sheet.pageSize().width(), "vier kolommen passen staand"
    table = _table_of(lay)
    assert table.wrapBehavior() == QgsLayoutTable.WrapBehavior.WrapText
    assert [column.heading() for column in table.columns()] == page.columns
    assert table.totalWidth() <= metrics.content_w + 0.5, f"{table.totalWidth()} mm past niet"


def test_a_table_of_fiches_says_where_the_fiches_live(project, gent_zone, tmp_path):
    """De tabel toont de permkey, niet de hele URL - anders is de kolom breder dan het blad. Waar
    die permkey op te zoeken valt, hoort dan wel op het blad te staan."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    page = _sonderingen_page()
    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    texts = [item.text() for item in lay.items() if isinstance(item, QgsLayoutItemLabel)]
    assert any("https://www.dov.vlaanderen.be/data/sondering/" in text for text in texts), texts


def test_a_figure_wider_than_tall_gets_a_landscape_sheet(project, gent_zone, tmp_path):
    """De doorsnede is breder dan hoog. Op een staand blad wordt ze tot een strook op de
    bovenhelft geperst; liggend gebruikt ze het blad."""
    from desktopstudie.core.report_content import FigurePage
    from desktopstudie.qgis import layout

    _png(tmp_path / "figuren" / "breed.png", 1400, 1142)
    lay = layout.build_layout(project, _report([FigurePage("Doorsnede", "figuren/breed.png")]), {},
                              tmp_path, gent_zone.ring, _meta())

    sheet = lay.pageCollection().page(1)
    assert sheet.pageSize().width() > sheet.pageSize().height()


def test_a_legend_page_puts_a_label_and_a_strip_per_entry_on_one_sheet(project, gent_zone, tmp_path):
    """De legendapagina draagt per eenheid haar eigen regel en haar eigen strook: code en kaartblad
    in tekst, de tekening van DOV eronder. Een strook van 980 x 98 px is een reepje van 26 x 3 cm -
    dat blijft een reepje, het wordt niet over een blad uitgerekt."""
    from qgis.core import QgsLayoutItemLabel, QgsLayoutItemPicture

    from desktopstudie.core.report_content import LegendEntry, LegendPage
    from desktopstudie.qgis import layout

    _png(tmp_path / "legendas" / "quartair_22010_kop.png", 980, 98)
    _png(tmp_path / "legendas" / "quartair_22026_kop.png", 980, 98)
    page = LegendPage("Legenda voor de zone - Quartair", [
        LegendEntry("22010", "22", "legendas/quartair_22010_kop.png"),
        LegendEntry("22026", "22", "legendas/quartair_22026_kop.png")])

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    assert lay.pageCollection().pageCount() == 1 + 1, "een blad, geen strookje per blad"
    sheet = lay.pageCollection().page(1)
    assert sheet.pageSize().height() > sheet.pageSize().width(), "staand"
    texts = [item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel)]
    assert "Profieltype 22010 - kaartblad 22" in texts
    assert "Profieltype 22026 - kaartblad 22" in texts
    pictures = _items_of(lay, 1, QgsLayoutItemPicture)
    assert len(pictures) == 2
    # 980 px op 96 dpi is 259 mm; dat past niet op 180 mm, dus de strook krimpt mee met de breedte
    # en houdt haar verhouding - nooit uitgerekt tot een banner van een half blad.
    for picture in pictures:
        size = picture.sizeWithUnits()
        assert size.width() <= layout.CONTENT_W + 0.01
        assert size.height() == pytest.approx(size.width() * 98 / 980, abs=0.5)


def test_a_legend_entry_without_a_drawing_says_so(project, gent_zone, tmp_path):
    """Een tekening die niet binnenkwam, mag geen leeg kader worden: de regel blijft staan en zegt
    dat de tekening ontbreekt."""
    from qgis.core import QgsLayoutItemLabel, QgsLayoutItemPicture

    from desktopstudie.core.report_content import LegendEntry, LegendPage
    from desktopstudie.qgis import layout

    page = LegendPage("Legenda voor de zone - Quartair", [LegendEntry("22098", "22", "")])

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert "Profieltype 22098 - kaartblad 22" in texts
    assert layout.MISSING_DRAWING in texts
    assert _items_of(lay, 1, QgsLayoutItemPicture) == []


def test_a_legend_page_that_is_full_continues_on_the_next_sheet(project, gent_zone, tmp_path):
    """Tien eenheden passen niet op een blad. Dan hoort er een tweede te komen met "(vervolg)" in
    de kop, niet een rij stroken die van het papier af loopt."""
    from desktopstudie.core.report_content import LegendEntry, LegendPage
    from desktopstudie.qgis import layout

    entries = []
    for number in range(12):
        code = f"220{number:02d}"
        _png(tmp_path / "legendas" / f"quartair_{code}_kop.png", 980, 98)
        entries.append(LegendEntry(code, "22", f"legendas/quartair_{code}_kop.png"))

    lay = layout.build_layout(project, _report([LegendPage("Legenda voor de zone - Quartair",
                                                           entries)]),
                              {}, tmp_path, gent_zone.ring, _meta())

    assert lay.pageCollection().pageCount() > 2, "twaalf stroken passen niet op een blad"
    from qgis.core import QgsLayoutItemLabel
    headers = [item.text() for index in range(1, lay.pageCollection().pageCount())
               for item in _items_of(lay, index, QgsLayoutItemLabel)]
    assert any("(vervolg)" in text for text in headers), headers
    # Elk blad draagt zijn voettekst, ook het eerste: het paginanummer hoort niet pas op het
    # vervolgblad te beginnen.
    for index in range(1, lay.pageCollection().pageCount()):
        assert _footers_on(lay, index), f"blad {index} zonder voettekst"


def test_an_empty_legend_page_prints_its_note(project, gent_zone, tmp_path):
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import LegendPage
    from desktopstudie.qgis import layout

    page = LegendPage("Legenda voor de zone - Quartair", [], note="Bron niet beschikbaar.")

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert "Bron niet beschikbaar." in texts


def test_a_tall_figure_stays_on_a_portrait_sheet(project, gent_zone, tmp_path):
    from desktopstudie.core.report_content import FigurePage
    from desktopstudie.qgis import layout

    _png(tmp_path / "figuren" / "hoog.png", 535, 985)
    lay = layout.build_layout(project, _report([FigurePage("Sondering", "figuren/hoog.png")]), {},
                              tmp_path, gent_zone.ring, _meta())

    sheet = lay.pageCollection().page(1)
    assert sheet.pageSize().height() > sheet.pageSize().width()


def test_building_a_layout_stops_when_the_user_cancels(project, gent_zone, tmp_path):
    """Een rapport van vijfennegentig bladen bouwen duurt een halve minuut; afbreken hoort niet op
    het einde daarvan te wachten."""
    from desktopstudie.core.parallel import Cancelled
    from desktopstudie.core.report_content import TextPage
    from desktopstudie.qgis import layout

    pages = [TextPage(f"Blad {number}", "<p>tekst</p>") for number in range(20)]

    with pytest.raises(Cancelled):
        layout.build_layout(project, _report(pages), {}, tmp_path, gent_zone.ring, _meta(),
                            should_cancel=lambda: True)


SOURCES_COLUMNS = ["Bron", "URL", "Opgehaald", "Status"]
SOURCES_ROWS = [
    ["Sonderingen", "https://www.dov.vlaanderen.be/geoserver/wfs", "2026-09-15",
     "fout: HttpError: netwerkfout voor https://www.dov.vlaanderen.be/geoserver/wfs "
     "(DescribeFeatureType dov-pub:Sonderingen): RemoteDisconnected: Remote end closed "
     "connection without response"],
    ["Grondwaterkwetsbaarheidskaart (feiten)", "https://www.dov.vlaanderen.be/geoserver/wfs",
     "2026-09-15", "ok"]]


def _honest_width(columns, rows):
    """De breedte waarop elke kolom haar langste onbreekbare woord nog kan krijgen, hier gemeten.

    Niet als getal in de test: dezelfde tekst is in de QGIS-containers breder dan op deze machine
    (andere lettertypes), en een tabel die daar niet meer past valt terug op de andere regel -
    "past zelfs de ondergrens niet, dan krimpt alles evenredig" - waar deze test niet over gaat.
    Ruim gemeten, zodat de kap van MAX_COLUMN_SHARE niet meespeelt.
    """
    from desktopstudie.qgis import layout

    roomy = 10_000.0
    cells = [[row[index] for row in rows] for index in range(len(columns))]
    return sum(layout._floor_width(column, column_cells, roomy, layout.TABLE_FONT_PT)
               for column, column_cells in zip(columns, cells))


def test_a_column_of_unbreakable_words_keeps_its_own_width(qgs_app):
    """WrapText breekt op spaties. Een datum of een permkey heeft er geen, dus die kolom moet haar
    hele woord krijgen - anders leest de bronnentabel "2026-09-15T22:2" en denkt de lezer dat de
    studie op een halve seconde is gemaakt. Gemeten op de echte bronnentabel van een studie waarin
    elke DOV-dienst plat lag."""
    from desktopstudie.qgis import layout

    available = _honest_width(SOURCES_COLUMNS, SOURCES_ROWS) + 1.0

    widths = layout.column_widths(SOURCES_COLUMNS, SOURCES_ROWS, available)

    assert sum(widths) <= available + 0.01
    for index, word in ((2, "2026-09-15"), (0, "Grondwaterkwetsbaarheidskaart")):
        assert widths[index] >= layout._text_width_mm([word], layout.TABLE_FONT_PT), \
            SOURCES_COLUMNS[index]


def test_a_table_that_does_not_fit_at_all_shrinks_instead_of_clipping(qgs_app):
    """Past zelfs de ondergrens niet, dan krimpt alles evenredig: smal is beter dan onzichtbaar.

    Dit is de andere helft van dezelfde regel en de reden dat de test hierboven haar breedte meet
    in plaats van aanneemt - op een machine met bredere lettertypes belandt dezelfde tabel op
    169,5 mm in dit geval."""
    from desktopstudie.qgis import layout

    cramped = _honest_width(SOURCES_COLUMNS, SOURCES_ROWS) / 2.0

    widths = layout.column_widths(SOURCES_COLUMNS, SOURCES_ROWS, cramped)

    assert sum(widths) <= cramped + 0.01
    assert all(width > 0 for width in widths), widths
    # evenredig: de verhouding tussen twee kolommen blijft die van hun ondergrenzen
    assert widths[1] > widths[2], "de URL-kolom blijft breder dan de datumkolom"


def test_one_greedy_column_cannot_eat_the_whole_sheet(qgs_app):
    """Een kolom met één heel lang woord erin (een URL) mag niet alle ruimte opeisen; de andere
    kolommen moeten leesbaar blijven."""
    from desktopstudie.qgis import layout

    columns = ["Naam", "URL"]
    rows = [["Sonderingen", "https://services.dov.vlaanderen.be/virtueleboringserver/base/"
                            "virtueleprofielen/doorprik/g3dv3_F"]]

    widths = layout.column_widths(columns, rows, 169.5)

    assert sum(widths) <= 169.5 + 0.01
    assert widths[0] >= layout._text_width_mm(["Sonderingen"], layout.TABLE_FONT_PT)


def test_a_row_shorter_than_its_headers_does_not_take_the_report_down(qgs_app):
    """Een rij met een kolom te weinig hoort een leeg vakje op te leveren, geen IndexError die het
    hele rapport meeneemt: de tabel komt uit de kern en die mag hier niets kunnen breken."""
    from desktopstudie.qgis import layout

    widths = layout.column_widths(["A", "B", "C"], [["een", "twee"], ["een", "twee", "drie"]], 100.0)

    assert len(widths) == 3 and all(width > 0 for width in widths)


def test_a_table_without_rows_prints_its_reason_and_no_empty_header(project, gent_zone, tmp_path):
    """"Geen kaarteenheden binnen de zone." gevolgd door een lege kolomkop is een tabel die doet
    alsof er iets komt. De reden volstaat."""
    from qgis.core import QgsLayoutFrame, QgsLayoutItemLabel

    from desktopstudie.core.report_content import TablePage
    from desktopstudie.qgis import layout

    page = TablePage("Legenda voor de zone - Erosie", ["Erosieklasse", "Totale erosie"], [],
                     note="Geen kaarteenheden binnen de zone.")

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert "Geen kaarteenheden binnen de zone." in texts
    assert _items_of(lay, 1, QgsLayoutFrame) == [], "geen tabelkader zonder rijen"


def test_a_table_with_rows_keeps_its_header(project, gent_zone, tmp_path):
    from qgis.core import QgsLayoutFrame

    from desktopstudie.core.report_content import TablePage
    from desktopstudie.qgis import layout

    page = TablePage("Legenda", ["Klasse"], [["C - kleine kans [2]"]])

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta())

    assert len(_items_of(lay, 1, QgsLayoutFrame)) == 1


def test_the_title_page_leaves_out_a_zone_line_that_repeats_the_address(project, gent_zone,
                                                                        tmp_path):
    """Bij een studie uit een adres is de zonenaam datzelfde adres; twee keer dezelfde regel op het
    titelblad zegt de tweede keer niets."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    meta = dict(_meta(), address="Kortrijksesteenweg 100", zone_name="Kortrijksesteenweg 100")

    lay = layout.build_layout(project, _report([]), {}, tmp_path, gent_zone.ring, meta)

    texts = " ".join(item.text() for item in _items_of(lay, 0, QgsLayoutItemLabel))
    assert "Adres" in texts and "Kortrijksesteenweg 100" in texts
    assert "<b>Zone</b>" not in texts


def test_the_title_page_keeps_a_zone_line_that_says_something_else(project, gent_zone, tmp_path):
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    meta = dict(_meta(), address="Kortrijksesteenweg 100", zone_name="Getekende polygoon")

    lay = layout.build_layout(project, _report([]), {}, tmp_path, gent_zone.ring, meta)

    texts = " ".join(item.text() for item in _items_of(lay, 0, QgsLayoutItemLabel))
    assert "Getekende polygoon" in texts


# --- dekking: levert de dienst hier wel een kaartbeeld? ---------------------------------------

def _solid_png(path, width=64, height=64, rgba=(255, 255, 255, 0)):
    """Een tegel zonder tekening: één kleur, of volledig doorzichtig."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(*rgba))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def _drawn_png(path, width=64, height=64):
    """Een tegel met iets erop: twee kleuren, zoals elke kaart die hier wel dekking heeft."""
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(240, 240, 230))
    painter = QPainter(image)
    painter.fillRect(4, 4, width // 2, height // 2, QColor(120, 40, 40))
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def test_a_map_without_coverage_says_so_and_keeps_no_legend_page(make_layout, gent_zone):
    """De kaart blijft staan - de zonecirkel hoort zichtbaar te zijn - maar het blad zegt dat de
    bron hier geen beeld levert, en een legenda bij een leeg beeld is een belofte te veel."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    empty = layout.map_image_key(MAP_ID, layout.map_extent(gent_zone.ring, 2500, 3.0))
    lay = make_layout(no_coverage={empty})

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert layout_module().NO_COVERAGE_NOTE in texts
    assert lay.pageCollection().pageCount() == 1 + 4, "geen legendapagina bij een leeg beeld"


def test_an_empty_framing_leaves_the_other_framings_of_that_map_alone(make_layout, gent_zone):
    """Geen dekking hoort bij een kader, niet bij een kaart.

    Dezelfde kaart staat op meer dan een blad, elk op zijn eigen uitsnede. Levert de dienst op het
    ene kader een lege tegel, dan zegt dat niets over het andere - en een tweede blad dat ten
    onrechte "geen dekking" draagt, laat de lezer denken dat de kaart daar niet bestaat.
    """
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layout

    pages = [MapPage(MAP_ID, "Ligging", legend=False, scale=2500, extent_factor=3.0),
             MapPage(MAP_ID, "Overzicht", legend=False, scale=5000, extent_factor=1.0)]
    empty = layout.map_image_key(MAP_ID, layout.map_extent(gent_zone.ring, 2500, 3.0))

    lay = make_layout(pages=pages, no_coverage={empty})

    first = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    second = " ".join(item.text() for item in _items_of(lay, 2, QgsLayoutItemLabel))
    assert layout.NO_COVERAGE_NOTE in first
    assert layout.NO_COVERAGE_NOTE not in second, second


def test_a_map_with_coverage_is_unchanged(make_layout):
    from qgis.core import QgsLayoutItemLabel

    lay = make_layout()

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert layout_module().NO_COVERAGE_NOTE not in texts
    assert lay.pageCollection().pageCount() == 1 + 4 + 1


def layout_module():
    from desktopstudie.qgis import layout

    return layout


def test_a_row_without_a_drawing_url_is_named_in_the_log(qgs_app, tmp_path, gent_zone):
    """Een profieltype zonder bruikbare legenda-URL levert een regel zonder tekening op. Zonder
    logregel is dat niet te onderscheiden van een download die mislukte - en wat NIET gevonden is,
    hoort in het log."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.model import MapFact, StudyResult
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout
    from tests import quartair

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    result = StudyResult(zone=gent_zone, created_at="t")
    result.map_facts = [MapFact("quartair", "Quartair", [
        quartair.rows(["22026"])[0], {"profieltype": "22099", "legende": None}])]
    lines = []

    layout.prepare_zone_legend_images(result, tmp_path, _Client(cache_dir=None),
                                      Log("layout", lines.append, scope="qgis"))

    assert any("22099" in line and "WARNING" in line for line in lines), lines
    assert not any("22026" in line and "WARNING" in line for line in lines), lines


def test_a_drawing_that_cannot_be_read_gives_no_strip(qgs_app, tmp_path):
    """Een bestand dat geen afbeelding is, levert geen kopstrook en zegt dat in het log - het mag
    geen leeg kader op de legendapagina worden."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import layout

    kapot = tmp_path / "legendas" / "quartair_22026.png"
    kapot.parent.mkdir(parents=True, exist_ok=True)
    kapot.write_bytes(b"dit is geen png")
    lines = []

    assert layout.crop_profile_header(kapot, Log("layout", lines.append, scope="qgis")) is None
    assert layout.crop_sheet_units(kapot, "22", Log("layout", lines.append, scope="qgis")) is None
    assert sum("WARNING" in line for line in lines) == 2, lines


def test_a_drawing_without_a_white_band_falls_back_to_a_fixed_strip(qgs_app, tmp_path):
    """Zonder witte band is er geen natuurlijke snede. Dan wint een vaste strook: nog altijd een
    strook, en niet een heel blad eenhedentabel."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import layout

    vol = _drawn_png(tmp_path / "vol.png", 980, 703)

    assert layout.header_rows(QImage(str(vol))) == layout.HEADER_FALLBACK_ROWS


def test_a_drawing_shorter_than_the_fallback_keeps_its_own_height(qgs_app, tmp_path):
    """Een tekening die korter is dan de vaste strook wordt niet langer gemaakt dan ze is."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import layout

    klein = _drawn_png(tmp_path / "klein.png", 200, 40)

    assert layout.header_rows(QImage(str(klein))) == 40


# --- kaartbeelden vooraf ophalen ---------------------------------------------------------------

def test_every_map_page_asks_for_one_image_at_the_size_it_will_be_printed(project, gent_zone,
                                                                          tmp_path):
    """De QGIS-WMS-provider haalt tijdens het renderen tegel na tegel op, een blad tegelijk, en het
    rapport wacht daarop. Dus wordt elk kaartbeeld vooraf als een enkele GetMap opgehaald, op de
    extent en de pixelmaat waarop het blad het toch afdrukt."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layout

    pages = [MapPage("grb", "Ligging", scale=2500), MapPage("ferraris", "Ferraris", scale=25000)]

    requests = layout.plan_map_images(_report(pages), gent_zone.ring, {})

    assert [request.map_id for request in requests] == ["grb", "ferraris"]
    first = requests[0]
    # 180 x 200 mm op de exportresolutie, en nooit meer dan de dienst aankan
    assert first.width == int(round(layout.MAP_W / 25.4 * layout.MAP_IMAGE_DPI))
    assert first.height == int(round(layout.MAP_H / 25.4 * layout.MAP_IMAGE_DPI))
    assert max(first.width, first.height) <= layout.MAP_IMAGE_MAX_PX
    assert first.extent == layout.map_extent(gent_zone.ring, 2500, 3.0)


def test_two_pages_of_the_same_map_at_the_same_extent_share_one_image(project, gent_zone, tmp_path):
    """De GRB-basiskaart staat op vier bladen. Waar de uitsnede dezelfde is, hoeft ze maar een keer
    opgehaald te worden; waar ze verschilt (hoofdstuk 5 rekt open voor de zoekstraal) niet."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layout

    pages = [MapPage("grb", "Ligging", scale=2500), MapPage("grb", "Nog eens", scale=2500),
             MapPage("grb", "Overzicht", scale=5000, extent_factor=1.0)]

    requests = layout.plan_map_images(_report(pages), gent_zone.ring, {})

    assert len(requests) == 2, [request.key for request in requests]
    assert len({request.key for request in requests}) == 2


def test_a_fetched_map_image_lands_next_to_its_world_file(qgs_app, gent_zone, tmp_path):
    """Een PNG zonder wereldbestand ligt nergens: de layout moet hem op de meter kunnen plaatsen."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _drawn_png(tmp_path / "tegel.png", 120, 130).read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            return blob

    requests = layout.plan_map_images(_report([MapPage("grb", "Ligging", scale=2500)]),
                                      gent_zone.ring, {})

    images, empty = layout.prepare_map_images(requests, tmp_path, _Client(cache_dir=None))

    path = images[requests[0].key]
    assert path.parent.name == layout.MAP_IMAGE_DIR and path.suffix == ".png"
    world = path.with_suffix(".pgw")
    assert world.exists()
    lines = world.read_text(encoding="utf-8").splitlines()
    extent = requests[0].extent
    assert float(lines[0]) == pytest.approx(extent.width() / requests[0].width, rel=1e-6)
    assert float(lines[3]) == pytest.approx(-extent.height() / requests[0].height, rel=1e-6)
    assert float(lines[4]) == pytest.approx(extent.xMinimum() + float(lines[0]) / 2, rel=1e-6)
    assert empty == set()
    assert "REQUEST=GetMap" in asked[0][0] and "VERSION=1.1.1" in asked[0][0]
    assert asked[0][1:] == (layout.MAP_IMAGE_TIMEOUT_S, layout.MAP_IMAGE_RETRIES)


def test_an_empty_map_image_is_the_coverage_answer_too(qgs_app, gent_zone, tmp_path):
    """De dekkingsproef was een extra GetMap per kaart. Nu het beeld er toch al is, valt het
    antwoord eruit: een volledig lege tegel betekent geen kaartbeeld op deze locatie - en alleen
    voor kaarten zonder feiten, want een lege watertoetstegel is data."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    leeg = _solid_png(tmp_path / "leeg.png", 64, 64).read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return leeg

    pages = [MapPage("popp", "Popp", scale=5000), MapPage("watertoets_pluviaal", "Watertoets",
                                                          scale=10000)]
    requests = layout.plan_map_images(_report(pages), gent_zone.ring, {})

    _images, empty = layout.prepare_map_images(requests, tmp_path, _Client(cache_dir=None))

    assert empty == {requests[0].key}, "per kader, niet per kaart"


def test_the_same_map_request_always_gets_the_same_file_name(qgs_app, tmp_path):
    """Dezelfde kaartaanvraag krijgt altijd dezelfde bestandsnaam.

    `hash()` op een str is per proces anders (PYTHONHASHSEED); een headless run die dezelfde
    `--out` hergebruikt liet daarmee bij elke run nieuwe weesbestanden achter, en twee kaders van
    dezelfde kaart konden op dezelfde naam uitkomen. De naam staat hier voluit: wie het schema
    verandert, verandert deze test bewust mee.
    """
    from qgis.core import QgsRectangle

    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _drawn_png(tmp_path / "tegel.png", 40, 40).read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    extent = QgsRectangle(104226.0, 192406.0, 104426.0, 192606.0)
    request = layout.MapRequest(layout.map_image_key("grb", extent), "grb", extent, 40, 40)

    images, _empty = layout.prepare_map_images([request], tmp_path, _Client(cache_dir=None))

    assert request.key == "grb:104226:192406:104426:192606"
    assert images[request.key].name == "grb_84a197c3.png"


def test_a_map_image_that_fails_leaves_no_file_and_no_coverage_claim(qgs_app, gent_zone, tmp_path):
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import layout

    class _Down(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            raise HttpError(url, 500, "dienst plat")

    requests = layout.plan_map_images(_report([MapPage("popp", "Popp", scale=5000)]),
                                      gent_zone.ring, {})
    lines = []

    images, empty = layout.prepare_map_images(requests, tmp_path, _Down(cache_dir=None),
                                              Log("layout", lines.append, scope="qgis"))

    assert images == {} and empty == set(), "een mislukte ophaling zegt niets over dekking"
    assert any("WARNING" in line for line in lines), lines


def test_a_map_page_draws_the_fetched_image_instead_of_the_live_service(project, gent_zone,
                                                                        tmp_path):
    """Het blad tekent de opgehaalde momentopname; de live WMS-laag blijft voor het project."""
    from qgis.core import QgsLayoutItemMap

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layers, layout

    _png(tmp_path / "data" / "kaarten" / "grb_1.png", 120, 130)
    snapshot = layers.snapshot_layer(tmp_path / "data" / "kaarten" / "grb_1.png", "GRB momentopname")
    project.addMapLayer(snapshot, False)
    wms = layers.zone_layer(gent_zone)
    wms.setName("GRB live")
    project.addMapLayer(wms, False)
    page = MapPage("grb", "Ligging", scale=2500)
    extent = layout.map_extent(gent_zone.ring, 2500, 3.0)

    lay = layout.build_layout(project, _report([page]), {}, tmp_path,
                              gent_zone.ring, _meta(),
                              map_images={layout.map_image_key("grb", extent): snapshot})

    item = [i for i in lay.pageCollection().itemsOnPage(1) if isinstance(i, QgsLayoutItemMap)][0]
    assert snapshot in item.layers()
    assert wms not in item.layers(), "de trage laag hoort niet meer op het blad te staan"


def test_a_map_page_without_an_image_says_the_source_was_not_available(project, gent_zone,
                                                                       tmp_path):
    """Kon het beeld niet opgehaald worden, dan blijft de kaart leeg - met een regel die zegt
    waarom, want een wit vlak zonder uitleg is het ergste van alles."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layers, layout

    wms = layers.zone_layer(gent_zone)
    project.addMapLayer(wms, False)

    lay = layout.build_layout(project, _report([MapPage("grb", "Ligging", scale=2500)]),
                              {}, tmp_path, gent_zone.ring, _meta(), map_images={})

    texts = " ".join(item.text() for item in _items_of(lay, 1, QgsLayoutItemLabel))
    assert layout.MISSING_MAP_NOTE in texts


# --- de dozen waarvoor een kaart openrekt komen uit de studie, niet uit de lagen -----------------

def _gent_result(gent_zone):
    from desktopstudie.core.model import Cpt, StudyResult

    result = StudyResult(zone=gent_zone, created_at="2026-09-15T10:00:00", municipality="Gent")
    result.cpts = [Cpt("k1", "GEO-01", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01", "continu elektrisch",
                       "M1", "Uitvoerder", "Opdracht", "https://www.dov.vlaanderen.be/data/sondering/k1", 12.0)]
    return result


def test_the_boxes_a_page_widens_for_are_read_from_the_study_itself(gent_zone):
    """De planner van de kaartbeelden draait in de werkthread, zonder een enkele laag; het blad
    tekent daarna met lagen. Allebei moeten ze dezelfde uitsnede vinden, dus de dozen komen uit de
    studie zelf: de proefpunten, de zoekstraal rond de zone en de doorsnedelijn - en niets als de
    studie die niet heeft."""
    from desktopstudie.core import geometry
    from desktopstudie.qgis import layout

    result = _gent_result(gent_zone)

    boxes = layout.overlay_boxes(result)

    minx, miny, maxx, maxy = geometry.bbox(gent_zone.ring)
    assert (minx - 500.0, miny - 500.0, maxx + 500.0, maxy + 500.0) in boxes["investigations"]
    assert (104300.0, 192500.0, 104300.0, 192500.0) in boxes["investigations"]
    assert boxes["section"] == []
    gent_zone.section_line = ((104226.0, 192406.0), (104426.0, 192606.0))
    assert layout.overlay_boxes(result)["section"] == [(104226.0, 192406.0, 104426.0, 192606.0)]


def test_map_extent_reads_a_plain_box_exactly_as_it_reads_a_layer(qgs_app, gent_zone):
    """Een kale (minx, miny, maxx, maxy) en een laag met precies die extent leveren dezelfde
    uitsnede op; anders vindt het blad het beeld niet dat de planner voor het ophaalde."""
    from desktopstudie.qgis import layers, layout

    search_area = layers.circle_layer(gent_zone)
    extent = search_area.extent()
    box = (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())

    assert layout.map_extent(gent_zone.ring, 5000, 1.0, [box]) == \
        layout.map_extent(gent_zone.ring, 5000, 1.0, [search_area])


def test_a_page_widens_for_the_study_boxes_it_was_given_not_for_its_layers(project, gent_zone, tmp_path):
    """Krijgt de bouwer de dozen van de studie mee, dan rekt de pagina daarvoor open, ook als er
    geen enkele laag te tekenen valt: de dozen zijn de waarheid, de lagen alleen het beeld."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layout

    boxes = layout.overlay_boxes(_gent_result(gent_zone))
    page = MapPage(MAP_ID, "Overzicht", legend=False, scale=5000, extent_factor=1.0,
                   show_investigations=True)

    lay = layout.build_layout(project, _report([page]), {}, tmp_path, gent_zone.ring, _meta(),
                              overlay_boxes=boxes)

    texts = [lbl.text() for lbl in _items_of(lay, 1, QgsLayoutItemLabel)]
    assert any("schaal 1:10 000" in text for text in texts), texts
    planned = layout.plan_map_images(_report([page]), gent_zone.ring, boxes)
    assert planned[0].extent == layout.map_extent(gent_zone.ring, 5000, 1.0, boxes["investigations"])


def test_the_layout_is_named_after_its_study(project, gent_zone, tmp_path):
    """Twee studies in één project, twee layouts: de naam draagt de studienaam, en zonder
    studienaam blijft het de kale naam van de plugin."""
    from desktopstudie.qgis import layout

    assert layout.layout_name("Gent") == "DOV Desktopstudie - Gent"
    assert layout.layout_name("") == layout.LAYOUT_NAME
    lay = layout.build_layout(project, _report([]), {}, tmp_path, gent_zone.ring, _meta(),
                              name=layout.layout_name("Gent"))
    assert lay.name() == "DOV Desktopstudie - Gent"


def test_a_portal_page_is_followed_to_the_file_and_never_kept(qgs_app, tmp_path, gent_zone):
    """Stuurt het portaal zijn eigen webpagina in plaats van de tekening, dan wijst die pagina zelf
    naar het bestand: die link wordt gevolgd. En de pagina blijft niet in de cache staan, want dan
    kwam ze er bij elke volgende run zonder netwerk weer uit."""
    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import layout

    blob = _profile_drawing(tmp_path / "bron.png").read_bytes()
    link = ("https://datasets-services.omgeving.vlaanderen.be/server/api/core/bitstreams/"
            "0082d459-f86d-4a5b-9508-bbb98ae38e88/content")
    page = ('<html>' + link + '"_name":"DOV_Quartair_50000_22026.png"</html>').encode()
    asked, forgotten = [], []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append(url)
            return blob if url == link else page

        def forget(self, url, params=None):
            forgotten.append(url)
            return True

    images = layout.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert profile_image_key("22026") in images, (
        "de tekening hoort er via de link uit de pagina te zijn")
    assert link in asked, "de link uit de pagina is niet gevolgd"
    assert any(url.endswith("_png") for url in forgotten), (
        "de webpagina hoort uit de cache gegooid te worden")
