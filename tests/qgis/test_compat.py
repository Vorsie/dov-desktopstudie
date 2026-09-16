"""De schil draait op QGIS 3.34 t/m 4.x: layout-maten worden altijd in millimeter gemaakt
en de versie is herkenbaar als 3.x of 4.x."""
from __future__ import annotations


def test_point_mm_is_in_millimetres(qgs_app):
    from desktopstudie.qgis import compat

    p = compat.point_mm(10, 20)
    assert (p.x(), p.y()) == (10, 20)
    assert p.units() == compat.MM


def test_size_mm_is_in_millimetres(qgs_app):
    from desktopstudie.qgis import compat

    s = compat.size_mm(180, 200)
    assert (s.width(), s.height()) == (180, 200)
    assert s.units() == compat.MM


def test_version_is_three_or_four(qgs_app):
    from desktopstudie.qgis import compat

    assert compat.qgis_version().startswith(("3.", "4."))


def test_an_enum_value_is_named_not_numbered(qgs_app):
    """Een kale "3" in een logregel zegt niemand iets. PyQt5 levert de oude QGIS-enums als gewone
    getallen zonder `.name`, dus de naam wordt bij de houder opgezocht; een echte Python-enum
    (QGIS 3.36+ en Qt6) draagt haar naam zelf."""
    from qgis.analysis import QgsZonalStatistics
    from qgis.core import QgsLayoutExporter

    from desktopstudie.qgis import compat

    result = QgsLayoutExporter.ExportResult
    assert compat.enum_name(QgsLayoutExporter, result.Success) == "Success"
    assert compat.enum_name(QgsLayoutExporter, result.FileError) == "FileError"
    assert compat.enum_name(QgsLayoutExporter, 999) == "999"
    assert compat.enum_name(QgsZonalStatistics.Result, QgsZonalStatistics.Result.LayerTypeWrong) == "LayerTypeWrong"


def test_an_old_enum_type_names_its_value_too(qgs_app):
    """Een naam opzoeken moet ook lukken als de houder het enum TYPE is en niet de klasse eromheen.

    Zo staat het in `dem.py` (`QgsZonalStatistics.Result`), en op QGIS 3.34 is dat type een
    `sip.enumtype`: `getattr` erop werkt, maar `dir()` geeft alleen de methodes van int terug, dus
    er valt niets te doorlopen. De leden staan wél op de klasse die het type bezit. Zonder die
    omweg leest het logpaneel op 3.34 "DHMV zonale statistiek gaf 1" - precies de kale cijfers waar
    deze shim voor bestaat. `QgsLayoutExporter.ExportResult` is op 3.40 nog zo'n oud type en staat
    hier model voor het geval op 3.34.
    """
    from qgis.core import QgsLayoutExporter

    from desktopstudie.qgis import compat

    result = QgsLayoutExporter.ExportResult

    assert compat.enum_name(result, result.FileError) == "FileError"
    assert compat.enum_name(result, result.Success) == "Success"
    assert compat.enum_name(result, 999) == "999"


def test_a_value_is_never_named_after_another_enum_of_the_same_class(qgs_app):
    """Twee enums van dezelfde klasse dragen dezelfde getallen: `QgsZonalStatistics.Count` is 1 en
    `QgsZonalStatistics.Result.LayerTypeWrong` is dat ook. Een naam die van de verkeerde enum komt
    is erger dan een cijfer - die liegt."""
    from qgis.analysis import QgsZonalStatistics

    from desktopstudie.qgis import compat

    result = getattr(QgsZonalStatistics, "Result", QgsZonalStatistics)

    assert compat.enum_name(result, result.LayerTypeWrong) == "LayerTypeWrong"


def test_offscreen_without_a_font_dir_gets_one(qgs_app, monkeypatch):
    """Het offscreen-platform zoekt lettertypes in een map die niet bestaat en tekent daarna elke
    letter als zwart blokje. Ontbreekt QT_QPA_FONTDIR, dan hoort de schil er zelf een te zetten en
    dat te zeggen - in de export is het verschil niet te zien aan een foutmelding."""
    import os

    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import compat

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    lines = []

    chosen = compat.ensure_font_dir(Log("compat", lines.append, scope="qgis"))

    assert chosen and os.path.isdir(chosen)
    assert os.environ["QT_QPA_FONTDIR"] == chosen
    assert any("QT_QPA_FONTDIR" in line for line in lines), lines


def test_a_font_dir_the_caller_chose_is_left_alone(qgs_app, monkeypatch, tmp_path):
    """Wie zelf een lettertypemap zet, weet waarom; de schil overschrijft die nooit."""
    import os

    from desktopstudie.qgis import compat

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QPA_FONTDIR", str(tmp_path))

    assert compat.ensure_font_dir() == str(tmp_path)
    assert os.environ["QT_QPA_FONTDIR"] == str(tmp_path)


def test_a_normal_platform_needs_no_font_dir(qgs_app, monkeypatch):
    """Met een echt platform komt de lettertypedatabank van het systeem; er valt niets te zetten."""
    import os

    from desktopstudie.qgis import compat

    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)

    assert compat.ensure_font_dir() is None
    assert "QT_QPA_FONTDIR" not in os.environ
