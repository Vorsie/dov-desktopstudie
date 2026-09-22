"""De dialoog als formulier: wat de widgets samen tot een studie maken, en wat Start doet met een
formulier dat niet af is. Offscreen, met een namaak-iface en een eigen instellingenbestand, zodat
geen test het QGIS-profiel van wie ze draait aanraakt. De zone-logica zelf staat in
test_zone_input.py; hier gaat het om de lijm."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.qgis.conftest import Click as _Click
from tests.qgis.conftest import FakeIface

GENT = (104326.0, 192506.0)


def _moved(points, from_authid, to_authid):
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsCoordinateTransformContext,
        QgsPointXY,
    )

    transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem(from_authid),
                                       QgsCoordinateReferenceSystem(to_authid), QgsCoordinateTransformContext())
    return [(p.x(), p.y()) for p in (transform.transform(QgsPointXY(x, y)) for x, y in points)]


def _close(ring, other, tolerance):
    return len(ring) == len(other) and all(abs(a[0] - b[0]) < tolerance and abs(a[1] - b[1]) < tolerance
                                           for a, b in zip(ring, other))


def _wgs84_canvas(dialog):
    """The canvas in WGS 84 over Gent, so every drawn point has to be transformed to be right."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    canvas = dialog.iface.canvas
    canvas.resize(400, 400)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    canvas.setExtent(QgsRectangle(3.70, 51.02, 3.74, 51.06))
    return canvas


def _clicks(tool, canvas, pixels):
    """Left-click the pixels, then right-click; returns the map coordinates the canvas gave them."""
    from qgis.PyQt.QtCore import QPoint, Qt

    seen = [canvas.getCoordinateTransform().toMapCoordinates(QPoint(x, y)) for x, y in pixels]
    for x, y in pixels:
        tool.canvasReleaseEvent(_Click(Qt.MouseButton.LeftButton, QPoint(x, y)))
    tool.canvasReleaseEvent(_Click(Qt.MouseButton.RightButton, QPoint(0, 0)))
    return [(p.x(), p.y()) for p in seen]


class _StubRunner:
    """Neemt aanvragen aan zonder ooit een taak te starten."""

    def __init__(self):
        from qgis.PyQt.QtCore import QObject, pyqtSignal

        class _Signals(QObject):
            finished = pyqtSignal(object)

        self._signals = _Signals()
        self.finished = self._signals.finished
        self.started = []
        self.running = False

    def start(self, request):
        self.started.append(request)


def _settings(tmp_path):
    from qgis.PyQt.QtCore import QSettings

    from desktopstudie.qgis.settings import PluginSettings

    return PluginSettings(QSettings(str(tmp_path / "instellingen.ini"), QSettings.Format.IniFormat))


def _dialog(tmp_path, runner=None):
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis.dialog import StudyDialog

    return StudyDialog(FakeIface(), runner or _StubRunner(), log=Log("dialoog", lambda _m: None, scope="qgis"),
                       settings=_settings(tmp_path))


def _fill_xy(dialog, tmp_path):
    dialog.mode_point.setChecked(True)
    dialog.x_spin.setValue(104326.0)
    dialog.y_spin.setValue(192506.0)
    dialog.buffer_spin.setValue(50.0)
    dialog.radius_spin.setValue(600.0)
    dialog.project_edit.setText("Proef Gent")
    dialog.company_edit.setText("Testbureau")
    dialog.author_edit.setText("A. Tester")
    dialog.output_edit.setText(str(tmp_path / "uit"))
    dialog.cache_combo.setCurrentIndex(dialog.cache_combo.findData("refresh"))
    dialog.legends_check.setChecked(False)
    dialog.compact_check.setChecked(True)


def test_the_form_in_xy_mode_becomes_one_request(qgs_app, tmp_path):
    """Alles wat de gebruiker invulde komt in één `StudyRequest`: de zone rond X/Y met de
    zoekstraal, de instellingen, het titelblad, de cachemodus, de legendakeuze en een eigen
    uitvoermap per run onder de gekozen map."""
    dialog = _dialog(tmp_path)
    _fill_xy(dialog, tmp_path)

    request = dialog.build_request()

    assert request.zone.name == "104326/192506" and request.zone.radius_m == 600.0
    assert request.zone.section_line is None, "automatisch: de kern kiest de langste as"
    assert request.settings.radius_m == 600.0 and request.settings.map_ids is None
    assert (request.meta.project, request.meta.company, request.meta.author) == \
        ("Proef Gent", "Testbureau", "A. Tester")
    assert request.out_dir.parent == tmp_path / "uit" and request.out_dir.name.startswith("Proef_Gent_")
    assert request.cache_mode == "refresh" and request.legends is False
    assert request.settings.compact is True
    # The cache sits next to the run folders, shared by every run under this output folder.
    assert request.cache_dir == tmp_path / "uit" / "cache"


def test_the_map_list_shows_every_entry_and_unchecking_one_narrows_the_study(qgs_app, tmp_path):
    """Alle kaarten uit de catalogus, ook de uitgeschakelde - grijs, niet aangevinkt, met hun reden
    als tooltip. Alles aangevinkt is de standaard (None); één kaart uit, en de studie krijgt
    precies de rest."""
    from qgis.PyQt.QtCore import Qt

    from desktopstudie.core import catalogue

    dialog = _dialog(tmp_path)
    items = [dialog.maps_list.item(i) for i in range(dialog.maps_list.count())]

    assert [item.data(Qt.ItemDataRole.UserRole) for item in items] == \
        [entry.id for entry in catalogue.entries(enabled_only=False)]
    disabled = [item for item in items if item.flags() == Qt.ItemFlag.NoItemFlags]
    assert {item.data(Qt.ItemDataRole.UserRole) for item in disabled} == \
        {entry.id for entry in catalogue.entries(enabled_only=False) if not entry.enabled}
    assert all(item.checkState() == Qt.CheckState.Unchecked and item.toolTip() for item in disabled)
    assert dialog.map_ids() is None

    first = next(item for item in items if item not in disabled)
    first.setCheckState(Qt.CheckState.Unchecked)

    assert dialog.map_ids() == [entry.id for entry in catalogue.entries()
                                if entry.id != first.data(Qt.ItemDataRole.UserRole)]


def test_address_mode_needs_a_chosen_candidate(qgs_app, tmp_path):
    """Zonder kandidaat geen studie - en de kandidaten die de geocoder terugbrengt komen in de
    lijst, de eerste gekozen, zodat Start daarna de zone rond dat adres maakt."""
    from desktopstudie.core.services.geocoder import GeocodeHit

    dialog = _dialog(tmp_path)
    dialog.output_edit.setText(str(tmp_path))
    with pytest.raises(ValueError, match="Zoek eerst een adres"):
        dialog.build_request()

    dialog._address_found(None, None, [GeocodeHit("Kortrijksesteenweg 100, 9000 Gent", 104326.0, 192506.0,
                                                  "Gent", "9000", "basisregisters_huisnummer"),
                                       GeocodeHit("Kortrijksesteenweg, 9000 Gent", 104000.0, 192000.0,
                                                  "Gent", "9000", "basisregisters_straat")])

    assert [dialog.hits_list.item(i).text() for i in range(dialog.hits_list.count())] == [
        "Kortrijksesteenweg 100, 9000 Gent", "Kortrijksesteenweg, 9000 Gent (niet op huisnummer)"]
    assert dialog.hits_list.currentRow() == 0
    request = dialog.build_request()
    assert request.zone.address == "Kortrijksesteenweg 100, 9000 Gent"
    assert request.zone.centroid == pytest.approx((104326.0, 192506.0), abs=0.01)


def test_start_with_an_incomplete_form_warns_and_starts_nothing(qgs_app, tmp_path):
    """Een formulier dat niet af is geeft een waarschuwing in de berichtenbalk die zegt wat er
    ontbreekt; er start geen taak en de knop blijft bruikbaar."""
    from qgis.core import Qgis

    runner = _StubRunner()
    dialog = _dialog(tmp_path, runner)
    dialog.mode_point.setChecked(True)  # X en Y nog op nul

    dialog.start()

    assert runner.started == []
    assert dialog.start_button.isEnabled()
    assert dialog.iface.pushed[-1][:2] == (Qgis.MessageLevel.Warning, "Geef X en Y in Lambert 72 op.")


def test_start_hands_the_request_to_the_runner_and_saves_the_settings(qgs_app, tmp_path):
    """Start bewaart wat de volgende studie ook nodig heeft - bedrijf, auteur, straal, uitvoermap,
    cache, legenda's - en geeft de aanvraag aan de runner; tot die klaar meldt is Start uit."""
    runner = _StubRunner()
    dialog = _dialog(tmp_path, runner)
    _fill_xy(dialog, tmp_path)

    dialog.start()

    assert len(runner.started) == 1 and runner.started[0].meta.project == "Proef Gent"
    assert not dialog.start_button.isEnabled()
    saved = _settings(tmp_path)
    assert (saved.company, saved.author, saved.radius_m) == ("Testbureau", "A. Tester", 600.0)
    assert Path(saved.output_dir) == tmp_path / "uit"
    assert saved.cache_mode == "refresh" and saved.legends is False
    assert saved.compact is True

    runner.finished.emit(None)

    assert dialog.start_button.isEnabled()


def test_one_geocode_at_a_time_and_a_stale_answer_is_ignored(qgs_app, tmp_path):
    """Twee keer Enter start geen tweede zoekopdracht, en een antwoord op een oudere zoekopdracht
    komt niet in de lijst - anders wijst de gekozen rij naar een ander adres dan er staat."""
    from desktopstudie.core.services.geocoder import GeocodeHit

    dialog = _dialog(tmp_path)
    started = []
    dialog._start_geocode = lambda query, token: started.append((query, token))
    dialog.address_edit.setText("Kortrijksesteenweg 100 Gent")

    dialog.search_address()
    dialog.search_address()

    assert [query for query, _token in started] == ["Kortrijksesteenweg 100 Gent"]
    assert not dialog.search_button.isEnabled()
    stale = GeocodeHit("Verouderd 1, 9000 Gent", 104000.0, 192000.0, "Gent", "9000", "basisregisters_huisnummer")
    dialog._address_found(object(), None, [stale])
    assert dialog.hits == [] and dialog.hits_list.count() == 0, "een verouderd antwoord telt niet"
    fresh = GeocodeHit("Kortrijksesteenweg 100, 9000 Gent", GENT[0], GENT[1], "Gent", "9000",
                       "basisregisters_huisnummer")
    dialog._address_found(started[0][1], None, [fresh])
    assert [hit.address for hit in dialog.hits] == [fresh.address]
    assert dialog.search_button.isEnabled()

    dialog.search_address()

    assert len(started) == 2, "na een antwoord mag er weer gezocht worden"


def test_closing_the_dialog_drops_a_search_that_is_still_running(qgs_app, tmp_path):
    """Een antwoord van de geocoder dat na het sluiten binnenkomt, hoort nergens meer te landen.

    De dialoog wordt hergebruikt (de plugin houdt haar vast), dus een zoekopdracht die bij het
    sluiten nog liep laat anders twee dingen achter: een token waarop het late antwoord de lijst
    alsnog vult, en een knop Zoek die bij het heropenen uitgeschakeld blijft.
    """
    from desktopstudie.core.services.geocoder import GeocodeHit

    dialog = _dialog(tmp_path)
    started = []
    dialog._start_geocode = lambda query, token: started.append((query, token))
    dialog.address_edit.setText("Kortrijksesteenweg 100 Gent")
    dialog.search_address()
    assert not dialog.search_button.isEnabled()

    dialog.close()

    assert dialog.search_button.isEnabled(), "heropend met een dode knop Zoek"
    late = GeocodeHit("Te laat 1, 9000 Gent", 104000.0, 192000.0, "Gent", "9000",
                      "basisregisters_huisnummer")
    dialog._address_found(started[0][1], None, [late])
    assert dialog.hits == [] and dialog.hits_list.count() == 0


def test_the_extension_only_applies_to_the_automatic_section_line(qgs_app, tmp_path):
    """De verlenging hoort bij de lijn die de kern zelf legt; een getekende of gekozen lijn is wat
    ze is. Buiten 'Automatisch' staat het veld uit."""
    from desktopstudie.qgis.dialog import SECTION_AUTO, SECTION_DRAW, SECTION_LAYER

    dialog = _dialog(tmp_path)

    assert dialog.extension_spin.isEnabled()
    dialog.section_combo.setCurrentIndex(SECTION_DRAW)
    assert not dialog.extension_spin.isEnabled()
    dialog.section_combo.setCurrentIndex(SECTION_LAYER)
    assert not dialog.extension_spin.isEnabled()
    dialog.section_combo.setCurrentIndex(SECTION_AUTO)
    assert dialog.extension_spin.isEnabled()


def test_drawing_a_polygon_on_a_wgs84_canvas_gives_a_zone_in_lambert_72(qgs_app, tmp_path):
    """Tekenmodus van begin tot einde: de knop zet de tool op het canvas, drie klikken en een
    rechtsklik maken de ring, het label zegt hoeveel hoekpunten, de tool is weer los - en de
    aanvraag draagt de ring in Lambert 72, ook al stond het canvas in WGS 84."""
    from desktopstudie.qgis import map_tools
    from desktopstudie.qgis.dialog import DRAW_RING_HINT

    dialog = _dialog(tmp_path)
    canvas = _wgs84_canvas(dialog)
    dialog.output_edit.setText(str(tmp_path))

    dialog.draw_ring()

    tool = canvas.mapTool()
    assert isinstance(tool, map_tools.DrawTool) and dialog.ring_label.text() == DRAW_RING_HINT
    drawn = _clicks(tool, canvas, [(100, 100), (300, 100), (200, 300)])

    assert dialog.mode_ring.isChecked()
    assert "3 hoekpunten" in dialog.ring_label.text()
    assert canvas.mapTool() is not tool, "na de rechtsklik is de tekentool los"
    request = dialog.build_request()
    assert _close(request.zone.ring, _moved(drawn, "EPSG:4326", "EPSG:31370"), 0.01)
    assert all(100000.0 < x < 110000.0 and 190000.0 < y < 196000.0 for x, y in request.zone.ring)


def test_a_polygon_of_two_clicks_is_refused_with_the_reason_on_the_label(qgs_app, tmp_path):
    """Twee hoekpunten zijn geen vlak: het label zegt het, de modus springt niet om en Start
    weigert zolang er geen polygoon is."""
    dialog = _dialog(tmp_path)
    canvas = _wgs84_canvas(dialog)
    dialog.output_edit.setText(str(tmp_path))

    dialog.draw_ring()
    _clicks(canvas.mapTool(), canvas, [(100, 100), (300, 100)])

    assert "minstens drie hoekpunten" in dialog.ring_label.text()
    assert not dialog.mode_ring.isChecked()
    dialog.mode_ring.setChecked(True)
    with pytest.raises(ValueError, match="Teken eerst een polygoon"):
        dialog.build_request()


def test_a_drawn_section_line_keeps_its_two_ends_in_lambert_72(qgs_app, tmp_path):
    """Doorsnedelijn tekenen: de tekenknop hoort bij die keuze, begin en einde van de getekende
    lijn komen in Lambert 72 op de aanvraag, de tussenpunten niet."""
    from desktopstudie.qgis.dialog import SECTION_DRAW

    dialog = _dialog(tmp_path)
    canvas = _wgs84_canvas(dialog)
    _fill_xy(dialog, tmp_path)
    dialog.section_combo.setCurrentIndex(SECTION_DRAW)
    assert dialog.section_button.isEnabled()

    dialog.draw_section()
    drawn = _clicks(canvas.mapTool(), canvas, [(100, 100), (200, 150), (300, 300)])

    assert dialog.section_label.text().startswith("Lijn van")
    start, end = _moved([drawn[0], drawn[-1]], "EPSG:4326", "EPSG:31370")
    line = dialog.build_request().zone.section_line
    assert line[0] == pytest.approx(start, abs=0.01) and line[1] == pytest.approx(end, abs=0.01)


def test_layer_mode_takes_the_first_selected_polygon_in_its_own_crs(qgs_app, tmp_path, gent_zone):
    """Uit laag: de lijst volgt het project (een laag erbij staat erin zonder de dialoog te
    heropenen, een laag weg is weg), zonder selectie weigert Start met de reden, en het eerste
    geselecteerde vlak - in Web Mercator - wordt de zone in Lambert 72."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

    layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "percelen", "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolygonXY(
        [[QgsPointXY(*p) for p in _moved(gent_zone.ring, "EPSG:31370", "EPSG:3857")]]))
    assert layer.dataProvider().addFeatures([feature])
    dialog = _dialog(tmp_path)
    dialog.output_edit.setText(str(tmp_path))
    dialog.mode_layer.setChecked(True)
    assert dialog.layer_combo.count() == 0
    QgsProject.instance().addMapLayer(layer, False)
    layer_id = layer.id()  # the project owns the layer and deletes it on removal
    try:
        assert dialog.layer_combo.findData(layer_id) >= 0, "de lijst volgt het project"
        dialog.layer_combo.setCurrentIndex(dialog.layer_combo.findData(layer_id))
        fid = next(layer.getFeatures()).id()
        layer.selectByIds([fid])
        request = dialog.build_request()

        assert request.zone.name == f"percelen #{fid}"
        assert _close(request.zone.ring, gent_zone.ring, 0.05)
    finally:
        QgsProject.instance().removeMapLayer(layer_id)
    assert dialog.layer_combo.findData(layer_id) < 0, "een verwijderde laag verdwijnt uit de lijst"


def test_a_section_line_from_a_selected_line_layer(qgs_app, tmp_path):
    """Doorsnedelijn uit laag: de lijnlagen van het project, de eerste geselecteerde lijn, de twee
    einden in Lambert 72."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

    from desktopstudie.qgis.dialog import SECTION_LAYER

    start, end = (104226.0, 192406.0), (104426.0, 192606.0)
    layer = QgsVectorLayer("LineString?crs=EPSG:3857", "assen", "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolylineXY(
        [QgsPointXY(*p) for p in _moved([start, end], "EPSG:31370", "EPSG:3857")]))
    assert layer.dataProvider().addFeatures([feature])
    dialog = _dialog(tmp_path)
    _fill_xy(dialog, tmp_path)
    dialog.section_combo.setCurrentIndex(SECTION_LAYER)
    assert dialog.section_layer_combo.isEnabled()
    QgsProject.instance().addMapLayer(layer, False)
    try:
        assert dialog.section_layer_combo.findData(layer.id()) >= 0
        assert dialog.layer_combo.findData(layer.id()) < 0, "een lijnlaag is geen zone"
        dialog.section_layer_combo.setCurrentIndex(dialog.section_layer_combo.findData(layer.id()))
        layer.selectByIds([next(layer.getFeatures()).id()])
        line = dialog.build_request().zone.section_line

        assert line[0] == pytest.approx(start, abs=0.01) and line[1] == pytest.approx(end, abs=0.01)
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_the_legend_pages_start_unticked_and_the_compact_layout_too(qgs_app, tmp_path):
    """De aparte legendapagina's staan standaard UIT - de kaarten met een legenda leveren er
    tientallen -
    en de compacte opmaak ook, want de standaardopmaak hoort voorspelbaar te zijn. Wie ze wil,
    vinkt ze aan, en die keuze wordt onthouden."""
    dialog = _dialog(tmp_path)

    assert dialog.legends_check.isChecked() is False
    assert dialog.compact_check.isChecked() is False


def _polygon_layer(name, count):
    """Een kladlaag zoals de gebruiker er zelf een maakt, met `count` vlakken erin."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    layer = QgsVectorLayer("Polygon?crs=EPSG:31370", name, "memory")
    features = []
    for n in range(count):
        x, y = 104000.0 + n * 500.0, 192000.0
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(x, y), QgsPointXY(x + 200.0, y),
                                                        QgsPointXY(x + 200.0, y + 200.0),
                                                        QgsPointXY(x, y + 200.0)]]))
        features.append(feature)
    assert layer.dataProvider().addFeatures(features)
    return layer


def _in_layer_mode(tmp_path, layer):
    from qgis.core import QgsProject

    dialog = _dialog(tmp_path)
    _fill_xy(dialog, tmp_path)
    dialog.mode_layer.setChecked(True)
    QgsProject.instance().addMapLayer(layer, False)
    dialog.layer_combo.setCurrentIndex(dialog.layer_combo.findData(layer.id()))
    return dialog


def test_one_polygon_in_the_layer_is_the_polygon(qgs_app, tmp_path):
    """"een vlak in de laag, dan is dat het vlak". Een kladlaag tekenen en de plugin erop wijzen is
    de gewone werkwijze; daar nog een aparte selectiestap voor eisen is pietluttig. En het gebeurt
    niet stilzwijgend: de meldingsbalk zegt achteraf welk vlak gebruikt is."""
    from qgis.core import QgsProject

    layer = _polygon_layer("contour", 1)
    dialog = _in_layer_mode(tmp_path, layer)
    try:
        assert not layer.selectedFeatureCount()

        dialog.start()

        assert dialog.runner.started, "zonder selectie hoort dit gewoon te lopen"
        texts = [text for _level, text, _item in dialog.iface.pushed]
        assert any("Geen selectie; het enige vlak in de laag contour is gebruikt." in text
                   for text in texts), texts
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_several_polygons_and_none_selected_says_how_many_and_what_to_do(qgs_app, tmp_path):
    """Pas als er meerdere vlakken zijn en er geen gekozen is, weigert de dialoog - en dan zegt ze
    hoeveel het er zijn en wat de gebruiker moet doen, niet alleen dat het misging."""
    from qgis.core import QgsProject

    layer = _polygon_layer("contour", 7)
    dialog = _in_layer_mode(tmp_path, layer)
    try:
        dialog.start()

        assert not dialog.runner.started
        texts = [text for _level, text, _item in dialog.iface.pushed]
        assert any("De laag contour heeft 7 vlakken. Selecteer er een met het selectiegereedschap "
                   "en start opnieuw." in text for text in texts), texts
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_the_state_of_the_chosen_layer_stands_next_to_the_combo(qgs_app, tmp_path):
    """De weigering hoort niet pas na Start te komen: de modus is gekozen en de laag staat in de
    lijst, dus de dialoog weet het al. De stand staat naast de lijst en volgt de kaart - de
    dialoog is niet modaal, dus hij kan buiten de dialoog om selecteren - en Start blijft bruikbaar.
    """
    from qgis.core import QgsProject

    layer = _polygon_layer("contour", 7)
    dialog = _in_layer_mode(tmp_path, layer)
    try:
        assert "7 vlakken" in dialog.layer_hint.text()
        assert "geen selectie" in dialog.layer_hint.text().lower()
        assert dialog.start_button.isEnabled(), "Start blijft bruikbaar"

        layer.selectByIds([next(layer.getFeatures()).id()])

        assert "1 geselecteerd" in dialog.layer_hint.text(), dialog.layer_hint.text()
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_a_hint_from_another_mode_does_not_linger(qgs_app, tmp_path):
    """"een zone heeft minstens drie hoekpunten nodig (1 gegeven)" bleef naast de Tekenen-knop
    staan terwijl de gebruiker al in de laagmodus zat. Een hint hoort bij zijn eigen modus."""
    from desktopstudie.qgis.dialog import NOTHING_DRAWN, SECTION_AUTO, SECTION_DRAW

    dialog = _dialog(tmp_path)
    dialog.mode_ring.setChecked(True)
    dialog.ring_label.setText("een zone heeft minstens drie hoekpunten nodig (1 gegeven)")

    dialog.mode_layer.setChecked(True)

    assert dialog.ring_label.text() == NOTHING_DRAWN

    dialog.section_combo.setCurrentIndex(SECTION_DRAW)
    dialog.section_label.setText("een doorsnedelijn heeft twee punten nodig (1 gegeven)")
    dialog.section_combo.setCurrentIndex(SECTION_AUTO)

    assert dialog.section_label.text() == ""


def test_one_line_in_the_layer_is_the_section_line(qgs_app, tmp_path):
    """Dezelfde regel voor de doorsnedelijn uit een laag: een lijn in de laag is die lijn, en
    meerdere zonder selectie zegt er hoeveel het zijn."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

    from desktopstudie.qgis.dialog import SECTION_LAYER

    layer = QgsVectorLayer("LineString?crs=EPSG:31370", "assen", "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolylineXY(
        [QgsPointXY(104226.0, 192406.0), QgsPointXY(104426.0, 192606.0)]))
    assert layer.dataProvider().addFeatures([feature])
    dialog = _dialog(tmp_path)
    _fill_xy(dialog, tmp_path)
    dialog.section_combo.setCurrentIndex(SECTION_LAYER)
    QgsProject.instance().addMapLayer(layer, False)
    try:
        dialog.section_layer_combo.setCurrentIndex(dialog.section_layer_combo.findData(layer.id()))

        dialog.start()

        assert dialog.runner.started
        texts = [text for _level, text, _item in dialog.iface.pushed]
        assert any("Geen selectie; de enige lijn in de laag assen is gebruikt." in text
                   for text in texts), texts
    finally:
        QgsProject.instance().removeMapLayer(layer.id())
