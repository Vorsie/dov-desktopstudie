"""De layout uit de rapportboom: één pagina per rapportpagina, een aparte legendapagina achter
elke kaart die er een vraagt, en de extentregel van een kaartpagina. Alles offline: er wordt niets
geëxporteerd en de "WMS-laag" is een memory-laag, zodat de test niets van een service verwacht."""
from __future__ import annotations

import pytest

MAP_ID = "grb"  # een echte catalogusentry: de layout leest er titel, attributie en licentie uit
ZONE_WIDTH_M = 100.0  # de Gent-zone is een cirkel van 50 m straal
TABLE_COLUMNS = ["Eenheid", "Top (mTAW)", "Basis (mTAW)"]


def _png(path):
    """Een echte 100 x 100 PNG: QgsLayoutItemPicture weigert een pad dat geen afbeelding is."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(QColor(30, 80, 160))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))


def _report(figure_rel_path):
    from desktopstudie.core.report_content import Chapter, FigurePage, MapPage, Report, TablePage, TextPage

    pages = [
        MapPage(MAP_ID, "Ligging op de GRB-basiskaart", legend=True, scale=2500, extent_factor=3.0),
        FigurePage("Sondering GEO-01", figure_rel_path, caption="Sondering nabij de zone"),
        TablePage("Lagen", list(TABLE_COLUMNS),
                  [[f"laag {i}", f"{10 - i}.00", f"{9 - i}.00"] for i in range(4)],
                  note="Modelwaarden, geen terreinmeting."),
        TextPage("Bronnen", "<p>DOV en geopunt, opgehaald op 2026-09-15.</p>"),
    ]
    return Report(title="Desktopstudie testproject", meta={}, chapters=[Chapter(1, "Test", pages)])


def _meta():
    return {"project": "Testproject", "project_number": "T-001", "author": "A. Tester",
            "company": "Testbureau", "address": "Kortrijksesteenweg 100", "municipality": "Gent",
            "zone_name": "Gent test", "created_at": "2026-09-15T10:00:00",
            "disclaimer": "<p>Geen interpretatie.</p>", "logo_path": ""}


@pytest.fixture
def built(project, gent_zone, tmp_path):
    """De layout, plus alles wat een test erover nodig heeft. De 'WMS'-laag is een memory-laag die
    wél in het project zit: een legendaknoop bewaart een laag-id en zoekt de laag in het project."""
    from desktopstudie.qgis import layers, layout

    figure_rel = "figuren/sondering.png"
    _png(tmp_path / figure_rel)
    wms_stand_in = layers.zone_layer(gent_zone)
    wms_stand_in.setName("GRB-basiskaart")
    project.addMapLayer(wms_stand_in, False)
    zone = layers.zone_layer(gent_zone)
    project.addMapLayer(zone, False)

    def build(legends=True):
        return layout.build_layout(project, _report(figure_rel), {MAP_ID: [wms_stand_in]},
                                   {"zone": [zone]}, tmp_path, gent_zone.ring, _meta(), legends=legends)

    return build


def _items_of(lay, index, cls):
    return [item for item in lay.pageCollection().itemsOnPage(index) if isinstance(item, cls)]


def test_a_page_per_report_page_plus_a_title_page_and_a_legend_page(built):
    """Titelblad + vier rapportpagina's + één legendapagina, want de kaart vraagt een legenda."""
    lay = built()
    assert lay.pageCollection().pageCount() == 1 + 4 + 1


def test_every_page_is_a4_portrait(built):
    """Van kaft tot kaft staand A4. `QgsPrintLayout.initializeDefaults()` legt zijn eerste pagina
    liggend neer, en op een liggend titelblad valt alles onder 210 mm - de inhoudsopgave, de
    disclaimer - gewoon van het papier af."""
    from desktopstudie.qgis import compat

    lay = built()  # de layout moet blijven leven: met haar sterven haar pagina's
    collection = lay.pageCollection()
    for index in range(collection.pageCount()):
        size = collection.page(index).pageSize()
        assert size.units() == compat.MM
        assert size.width() == pytest.approx(210.0, abs=0.5), f"pagina {index} is niet 210 mm breed"
        assert size.height() == pytest.approx(297.0, abs=0.5), f"pagina {index} is niet 297 mm hoog"


def test_without_legends_no_legend_pages_are_made(built):
    """De schakelaar van de plugin/CLI: geen legendapagina's, de rest ongewijzigd."""
    lay = built(legends=False)
    assert lay.pageCollection().pageCount() == 1 + 4


def test_the_map_page_carries_the_map_scale_bar_arrow_and_info_boxes_but_no_legend(built):
    from qgis.core import (
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
    )

    lay = built()
    maps = _items_of(lay, 1, QgsLayoutItemMap)
    bars = _items_of(lay, 1, QgsLayoutItemScaleBar)
    assert len(maps) == 1 and len(bars) == 1
    assert bars[0].linkedMap().uuid() == maps[0].uuid()
    assert len(_items_of(lay, 1, QgsLayoutItemPicture)) == 1  # de noordpijl
    framed = [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]
    assert len(framed) == 2  # bron/schaal rechtsboven en attributie/licentie rechtsonder
    # De legenda staat op haar eigen pagina: op de kaartpagina hoort ze niet.
    assert _items_of(lay, 1, QgsLayoutItemLegend) == []


def test_the_info_boxes_are_readable_over_the_map(built):
    """Een infovak staat bovenop de kaart. Zonder eigen achtergrond leest de tekst over gevels en
    straatnamen heen en is ze onleesbaar, precies waar de schaal en de bronvermelding staan."""
    from qgis.core import QgsLayoutItemLabel

    lay = built()
    framed = [lbl for lbl in _items_of(lay, 1, QgsLayoutItemLabel) if lbl.frameEnabled()]
    assert framed
    for box in framed:
        assert box.hasBackground(), f"infovak zonder achtergrond: {box.text()[:40]!r}"
        assert box.backgroundColor().alpha() == 255


def test_the_legend_page_is_named_linked_and_switchable(built):
    from qgis.core import QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutObject

    lay = built()
    page_item = lay.pageCollection().page(2)
    assert page_item.id() == f"legenda-{MAP_ID}"
    legends = _items_of(lay, 2, QgsLayoutItemLegend)
    assert len(legends) == 1
    assert legends[0].linkedMap().uuid() == _items_of(lay, 1, QgsLayoutItemMap)[0].uuid()
    # Eén layoutvariabele zet alle legendapagina's uit zonder ze te verwijderen.
    prop = page_item.dataDefinedProperties().property(QgsLayoutObject.DataDefinedProperty.ExcludeFromExports)
    assert prop.expressionString() == "@legendas = 0"


def _excluded_from_exports(lay, index):
    """Evaluate the ExcludeFromExports expression of a page in the layout's own context."""
    from qgis.core import QgsExpression, QgsLayoutObject

    prop = lay.pageCollection().page(index).dataDefinedProperties().property(
        QgsLayoutObject.DataDefinedProperty.ExcludeFromExports)
    return bool(QgsExpression(prop.expressionString()).evaluate(lay.createExpressionContext()))


def test_one_layout_variable_switches_the_legend_pages_out_of_the_export(built):
    """De tweede schakelaar: de legendapagina's blijven bestaan, maar vallen uit de export zodra
    de gebruiker `legendas` op 0 zet. QGIS bewaart een layoutvariabele als tekst, dus de waarde
    komt als '1'/'0' terug; wat telt is dat de uitsluitingsexpressie erop omslaat."""
    from qgis.core import QgsExpressionContextUtils

    lay = built()
    assert int(QgsExpressionContextUtils.layoutScope(lay).variable("legendas")) == 1
    assert _excluded_from_exports(lay, 2) is False

    QgsExpressionContextUtils.setLayoutVariable(lay, "legendas", 0)
    assert _excluded_from_exports(lay, 2) is True


def test_without_legends_the_variable_is_off_too(built):
    """`build_layout(legends=False)` zet de variabele mee om, zodat een layout zonder
    legendapagina's niet met een schakelaar op "aan" in QGIS opent."""
    from qgis.core import QgsExpressionContextUtils

    lay = built(legends=False)
    assert int(QgsExpressionContextUtils.layoutScope(lay).variable("legendas")) == 0


def test_the_extent_is_the_wider_of_the_target_scale_and_the_zone(project, gent_zone, tmp_path):
    """`MapPage.scale` is een doelschaal. Bij 1:2500 toont het kaartitem van 180 mm 450 m; drie
    keer een zone van 100 m is minder, dus de schaal wint. Tien keer die zone is 1000 m en die
    wint, want anders valt de zone buiten beeld."""
    from desktopstudie.qgis import layout

    builder = layout.LayoutBuilder(project, _report("x.png"), {}, {}, tmp_path, gent_zone.ring, _meta())
    assert builder.map_extent(2500, 3.0).width() == pytest.approx(layout.MAP_W / 1000.0 * 2500, abs=0.5)
    assert builder.map_extent(2500, 3.0).width() == pytest.approx(450.0, abs=0.5)
    assert builder.map_extent(2500, 10.0).width() == pytest.approx(ZONE_WIDTH_M * 10.0, abs=0.5)
    assert builder.map_extent(2500, 10.0).width() == pytest.approx(1000.0, abs=0.5)
    # het kaartitem is hoger dan breed, dus de extent ook
    wide = builder.map_extent(2500, 10.0)
    assert wide.height() == pytest.approx(wide.width() * layout.MAP_H / layout.MAP_W, abs=0.5)


def test_the_table_page_has_a_frame_the_columns_and_runs_on(built):
    from qgis.core import QgsLayoutFrame, QgsLayoutMultiFrame

    lay = built()
    frames = _items_of(lay, 4, QgsLayoutFrame)
    assert frames, "geen tabelframe op de tabelpagina"
    table = frames[0].multiFrame()
    assert table.frameCount() >= 1
    assert [column.heading() for column in table.columns()] == TABLE_COLUMNS
    # Een tabel die niet op één pagina past, moet doorlopen in plaats van afgekapt te worden.
    assert table.resizeMode() == QgsLayoutMultiFrame.ResizeMode.ExtendToNextPage


def test_the_figure_page_shows_the_png_from_the_output_directory(built, tmp_path):
    from qgis.core import QgsLayoutItemPicture

    lay = built()  # de layout moet blijven leven: met haar sterven haar items
    pictures = _items_of(lay, 3, QgsLayoutItemPicture)
    assert len(pictures) == 1
    assert pictures[0].picturePath() == str(tmp_path / "figuren/sondering.png")


def test_the_title_page_names_the_report_and_lists_the_chapters(built):
    from qgis.core import QgsLayoutItemLabel

    lay = built()
    texts = [lbl.text() for lbl in _items_of(lay, 0, QgsLayoutItemLabel)]
    assert any("Desktopstudie testproject" in text for text in texts)
    assert any("1. Test" in text for text in texts)
    assert any("Testbureau" in text for text in texts)
