"""De layout uit de rapportboom: een pagina per rapportpagina, aparte legendapagina's achter elke
kaart die er een vraagt, de extentregel van een kaartpagina en wat er gebeurt als een tabel niet
op een blad past.

Bijna alles offline: de "WMS-laag" is een memory-laag en de legenda is een zelfgemaakte PNG, zodat
de test niets van een service verwacht. Alleen de legenda-ophaler heeft een live variant, want
alleen de echte GeoServer bewijst dat de GetLegendGraphic-URL klopt."""
from __future__ import annotations

import pytest

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


def _meta():
    return {"project": "Testproject", "project_number": "T-001", "author": "A. Tester",
            "company": "Testbureau", "address": "Kortrijksesteenweg 100", "municipality": "Gent",
            "zone_name": "Gent test", "created_at": "2026-09-15T10:00:00",
            "disclaimer": "<p>Geen interpretatie.</p>", "logo_path": ""}


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

    def build(pages=None, legends=True, legend_images=None, overlays=None):
        if legend_images is None:
            legend_images = {MAP_ID: _png(tmp_path / "legendas" / f"{MAP_ID}.png", 120, 300)}
        merged = {"zone": [zone]}
        merged.update(overlays or {})
        return layout.build_layout(project, _report(_standard_pages() if pages is None else pages),
                                   {MAP_ID: [wms_stand_in]}, merged, tmp_path, gent_zone.ring,
                                   _meta(), legends=legends, legend_images=legend_images)

    return build


def _items_of(lay, index, cls):
    return [item for item in lay.pageCollection().itemsOnPage(index) if isinstance(item, cls)]


def _footers_on(lay, index):
    from qgis.core import QgsLayoutItemLabel

    return [lbl for lbl in _items_of(lay, index, QgsLayoutItemLabel) if "@layout_page" in lbl.text()]


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
                                  {}, {}, tmp_path, gent_zone.ring, _meta())
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

    builder = layout.LayoutBuilder(project, _report([]), {}, {}, tmp_path, gent_zone.ring, _meta())
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
    builder = layout.LayoutBuilder(project, _report([]), {}, {}, tmp_path, gent_zone.ring, _meta())

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
    builder = layout.LayoutBuilder(project, _report([]), {}, {}, tmp_path, gent_zone.ring, _meta())

    extent = builder.map_extent(5000, 1.0, [search_area])  # de overzichtspagina van hoofdstuk 5

    assert extent.width() / (layout.MAP_W / 1000.0) == pytest.approx(10000, abs=1)
    assert extent.contains(search_area.extent())


def test_a_map_that_was_not_widened_keeps_the_catalogue_scale(project, gent_zone, tmp_path):
    """Past alles op de doelschaal, dan blijft die staan: de catalogusschaal is een keuze, geen
    tussenstap die naar de ladder mag worden getrokken."""
    from desktopstudie.qgis import layout

    builder = layout.LayoutBuilder(project, _report([]), {}, {}, tmp_path, gent_zone.ring, _meta())

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
    lay = layout.build_layout(project, _report([page]), {}, overlays, tmp_path, gent_zone.ring, _meta())

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
    assert "LAYER=gxg%3Aghg_mmv_main" in url or "LAYER=gxg:ghg_mmv_main" in url
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
        def get(self, url, params=None, timeout=None, retries=None):
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
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout

    lay = layout.build_layout(project, _report([]), {}, {}, tmp_path, gent_zone.ring,
                              {"project": "", "company": "", "created_at": "2026-09-15T10:00:00"})
    footer = next(lbl for lbl in _items_of(lay, 0, QgsLayoutItemLabel) if "@layout_page" in lbl.text())
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
    lay = layout.build_layout(project, _report([page]), {}, {}, tmp_path, gent_zone.ring, _meta())

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
    lay = layout.build_layout(project, _report([page]), {}, {}, tmp_path, gent_zone.ring, _meta())

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
    lay = layout.build_layout(project, _report([page]), {}, {}, tmp_path, gent_zone.ring, _meta())

    texts = [item.text() for item in lay.items() if isinstance(item, QgsLayoutItemLabel)]
    assert any("https://www.dov.vlaanderen.be/data/sondering/" in text for text in texts), texts


def test_a_figure_wider_than_tall_gets_a_landscape_sheet(project, gent_zone, tmp_path):
    """De doorsnede is breder dan hoog. Op een staand blad wordt ze tot een strook op de
    bovenhelft geperst; liggend gebruikt ze het blad."""
    from desktopstudie.core.report_content import FigurePage
    from desktopstudie.qgis import layout

    _png(tmp_path / "figuren" / "breed.png", 1400, 1142)
    lay = layout.build_layout(project, _report([FigurePage("Doorsnede", "figuren/breed.png")]), {}, {},
                              tmp_path, gent_zone.ring, _meta())

    sheet = lay.pageCollection().page(1)
    assert sheet.pageSize().width() > sheet.pageSize().height()


def test_a_tall_figure_stays_on_a_portrait_sheet(project, gent_zone, tmp_path):
    from desktopstudie.core.report_content import FigurePage
    from desktopstudie.qgis import layout

    _png(tmp_path / "figuren" / "hoog.png", 535, 985)
    lay = layout.build_layout(project, _report([FigurePage("Sondering", "figuren/hoog.png")]), {}, {},
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
        layout.build_layout(project, _report(pages), {}, {}, tmp_path, gent_zone.ring, _meta(),
                            should_cancel=lambda: True)


def test_a_column_of_unbreakable_words_keeps_its_own_width(qgs_app):
    """WrapText breekt op spaties. Een datum of een permkey heeft er geen, dus die kolom moet haar
    hele woord krijgen - anders leest de bronnentabel "2026-09-15T22:2" en denkt de lezer dat de
    studie op een halve seconde is gemaakt. Gemeten op de echte bronnentabel van een studie waarin
    elke DOV-dienst plat lag."""
    from desktopstudie.qgis import layout

    columns = ["Bron", "URL", "Opgehaald", "Status"]
    rows = [["Sonderingen", "https://www.dov.vlaanderen.be/geoserver/wfs", "2026-09-15",
             "fout: HttpError: netwerkfout voor https://www.dov.vlaanderen.be/geoserver/wfs "
             "(DescribeFeatureType dov-pub:Sonderingen): RemoteDisconnected: Remote end closed "
             "connection without response"],
            ["Grondwaterkwetsbaarheidskaart (feiten)", "https://www.dov.vlaanderen.be/geoserver/wfs",
             "2026-09-15", "ok"]]

    widths = layout.column_widths(columns, rows, 169.5)

    assert sum(widths) <= 169.5 + 0.01
    for index, word in ((2, "2026-09-15"), (0, "Grondwaterkwetsbaarheidskaart")):
        assert widths[index] >= layout._text_width_mm([word], layout.TABLE_FONT_PT), columns[index]


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
