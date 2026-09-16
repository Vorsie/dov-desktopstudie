"""Wat QGIS van een plugin vraagt: `classFactory` in het pakket, `initGui`/`unload` die een actie
zetten en weer weghalen, en een metadata.txt die zegt welke QGIS-versies ze aankan. Met een
namaak-iface: de echte bestaat alleen in een draaiende QGIS."""
from __future__ import annotations

import configparser
from pathlib import Path

from tests.versions import pyproject_version


class _FakeIface:
    def __init__(self):
        self.toolbar, self.menu = [], []

    def mainWindow(self):
        return None

    def addToolBarIcon(self, action):
        self.toolbar.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar.remove(action)

    def addPluginToMenu(self, name, action):
        self.menu.append((name, action))

    def removePluginMenu(self, name, action):
        self.menu.remove((name, action))


def test_the_package_entry_point_builds_the_plugin_lazily(qgs_app):
    """`desktopstudie.classFactory(iface)` is wat QGIS aanroept. Het pakket zelf importeert de
    schil pas dan, zodat de kern buiten QGIS importeerbaar blijft (bewaakt in tests/core)."""
    import desktopstudie

    plugin = desktopstudie.classFactory(_FakeIface())

    assert type(plugin).__name__ == "DesktopstudiePlugin"


def test_init_gui_adds_the_action_and_unload_removes_it(qgs_app):
    """Eén knop in de werkbalk en één item in het pluginmenu, met icoon; na `unload` allebei weg."""
    import desktopstudie
    from desktopstudie.qgis.plugin import MENU_NAME, PLUGIN_NAME

    iface = _FakeIface()
    plugin = desktopstudie.classFactory(iface)

    plugin.initGui()

    assert len(iface.toolbar) == 1
    action = iface.toolbar[0]
    assert action.text() == PLUGIN_NAME
    assert not action.icon().isNull(), "het icoon uit resources/icoon.svg hoort te laden"
    assert iface.menu == [(MENU_NAME, action)]

    plugin.unload()

    assert iface.toolbar == [] and iface.menu == []


def test_unload_lets_go_of_the_message_bar_and_the_runner(qgs_app):
    """Een uitgeladen plugin hoort niets meer te horen.

    De runner hangt aan `messageBar().widgetRemoved` - een signaal van QGIS zelf, niet van de
    plugin - dus na `unload` (Plugin Reloader, of de gebruiker die de plugin afvinkt) roept die
    balk nog een slot aan van een object dat er niet meer hoort te zijn. Losmaken is het werk van
    `unload`, net als de knop uit de werkbalk halen.
    """
    import pytest

    import desktopstudie
    from desktopstudie.qgis.task import StudyRunner
    from tests.qgis.conftest import FakeIface

    iface = FakeIface()
    plugin = desktopstudie.classFactory(iface)
    plugin.initGui()
    runner = StudyRunner(iface)
    plugin.runner = runner

    plugin.unload()

    assert plugin.runner is None
    with pytest.raises(TypeError):  # al losgemaakt; een tweede keer kan niet
        iface.messageBar().widgetRemoved.disconnect(runner._progress_item_removed)


def test_metadata_names_the_versions_the_plugin_claims():
    """qgisMinimumVersion 3.34 en supportsQt6: de twee regels waarop de huisregel "3.34 t/m 4.x"
    staat. Het icoon dat metadata.txt noemt moet bestaan, anders toont QGIS een leeg vakje."""
    import desktopstudie

    package = Path(desktopstudie.__file__).parent
    config = configparser.ConfigParser()
    config.read(package / "metadata.txt", encoding="utf-8")
    general = config["general"]

    assert general["name"] == "DOV Desktopstudie"
    assert general["qgisMinimumVersion"] == "3.34"
    assert general.getboolean("supportsQt6") is True
    assert general["version"] == pyproject_version(), "één versie: metadata.txt volgt pyproject.toml"
    assert general.getboolean("experimental") is True
    assert (package / general["icon"]).is_file()
