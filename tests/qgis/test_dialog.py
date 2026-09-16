"""De dialoog als formulier: wat de widgets samen tot een studie maken, en wat Start doet met een
formulier dat niet af is. Offscreen, met een namaak-iface en een eigen instellingenbestand, zodat
geen test het QGIS-profiel van wie ze draait aanraakt. De zone-logica zelf staat in
test_zone_input.py; hier gaat het om de lijm."""
from __future__ import annotations

from pathlib import Path

import pytest


class _FakeIface:
    def __init__(self):
        from qgis.gui import QgsMapCanvas, QgsMessageBar

        self.bar = QgsMessageBar()
        self.canvas = QgsMapCanvas()
        self.pushed = []
        self.bar.widgetAdded.connect(self._record)

    def _record(self, widget):
        # An item the bar made itself (pushWarning) arrives as a bare QWidget; cast it back.
        from qgis.gui import QgsMessageBarItem
        from qgis.PyQt import sip

        item = sip.cast(widget, QgsMessageBarItem)
        self.pushed.append((item.level(), item.text()))

    def messageBar(self):
        return self.bar

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return None


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

    return StudyDialog(_FakeIface(), runner or _StubRunner(), log=Log("dialoog", lambda _m: None, scope="qgis"),
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

    dialog._address_found(None, [GeocodeHit("Kortrijksesteenweg 100, 9000 Gent", 104326.0, 192506.0,
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
    assert dialog.iface.pushed[-1] == (Qgis.MessageLevel.Warning, "Geef X en Y in Lambert 72 op.")


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

    runner.finished.emit(None)

    assert dialog.start_button.isEnabled()
