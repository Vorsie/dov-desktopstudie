"""De instellingen van de plugin: wat er staat voor er ooit iets bewaard is, en wat na een herstart
terugkomt. Elke test krijgt een eigen ini-bestand als opslag, zodat het echte QGIS-profiel van wie
de tests draait onaangeroerd blijft."""
from __future__ import annotations

from pathlib import Path


def _store(tmp_path):
    from qgis.PyQt.QtCore import QSettings

    return QSettings(str(tmp_path / "instellingen.ini"), QSettings.Format.IniFormat)


def test_the_defaults_before_anything_was_saved(qgs_app, tmp_path):
    """Een verse installatie: 500 m zoekstraal, de studies onder Documenten, de schijfcache aan en
    de legenda's op aparte pagina's; de velden van het titelblad leeg."""
    from desktopstudie.qgis.settings import PluginSettings

    settings = PluginSettings(_store(tmp_path))

    assert settings.radius_m == 500.0
    assert (settings.company, settings.author, settings.logo) == ("", "", "")
    assert Path(settings.output_dir) == Path.home() / "Documents" / "Desktopstudies"
    assert settings.cache_mode == "use"
    assert settings.legends is True


def test_what_is_saved_comes_back_to_a_fresh_reader(qgs_app, tmp_path):
    """Bedrijf, auteur, logo, zoekstraal, uitvoermap, cachemodus en legendakeuze overleven een
    herstart van QGIS: een tweede lezer op dezelfde opslag ziet precies wat de eerste bewaarde."""
    from desktopstudie.qgis.settings import PluginSettings

    first = PluginSettings(_store(tmp_path))
    first.company = "Testbureau"
    first.author = "A. Tester"
    first.logo = str(tmp_path / "logo.png")
    first.radius_m = 750.0
    first.output_dir = str(tmp_path / "studies")
    first.cache_mode = "refresh"
    first.legends = False
    first.sync()

    again = PluginSettings(_store(tmp_path))

    assert (again.company, again.author, again.logo) == ("Testbureau", "A. Tester", str(tmp_path / "logo.png"))
    assert again.radius_m == 750.0
    assert again.output_dir == str(tmp_path / "studies")
    assert again.cache_mode == "refresh"
    assert again.legends is False


def test_the_keys_live_under_the_plugin_prefix(qgs_app, tmp_path):
    """Alles onder `desktopstudie/`, met de Nederlandse namen uit het plan, zodat de instellingen in
    de geavanceerde instellingen van QGIS bij elkaar staan en herkenbaar zijn."""
    from desktopstudie.qgis.settings import PluginSettings

    store = _store(tmp_path)
    settings = PluginSettings(store)
    settings.company, settings.author, settings.logo = "X", "Y", "Z"
    settings.radius_m, settings.output_dir, settings.cache_mode, settings.legends = 600.0, "map", "off", True
    settings.sync()

    assert sorted(store.allKeys()) == ["desktopstudie/auteur", "desktopstudie/bedrijf", "desktopstudie/cache",
                                       "desktopstudie/legendas", "desktopstudie/logo", "desktopstudie/straal",
                                       "desktopstudie/uitvoermap"]


def test_a_value_that_cannot_be_read_falls_back_to_its_default(qgs_app, tmp_path):
    """Een met de hand verknoeide straal of een cachemodus die niet bestaat mag de dialoog niet
    onderuithalen: de standaardwaarde komt terug."""
    from desktopstudie.qgis.settings import PluginSettings

    store = _store(tmp_path)
    store.setValue("desktopstudie/straal", "vijfhonderd")
    store.setValue("desktopstudie/cache", "misschien")
    store.setValue("desktopstudie/legendas", "nee")

    settings = PluginSettings(store)

    assert settings.radius_m == 500.0
    assert settings.cache_mode == "use"
    assert settings.legends is False, "een tekst die geen 'true' is, is uit"


def test_the_fields_can_be_read_off_the_class(qgs_app):
    """`PluginSettings.radius_m` op de klasse is het veld zelf, niet een lezing van niets: wie de
    sleutels wil opsommen, kan dat zonder een opslag."""
    from desktopstudie.qgis.settings import PluginSettings

    assert PluginSettings.radius_m.key == "straal"
    assert PluginSettings.legends.key == "legendas"
