"""QGIS shell tests: they run only in a Python that has qgis (python-qgis-ltr.bat or the
Docker images). In the plain dev venv the importorskip below skips this whole directory,
so `pytest tests` stays green there."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("qgis.core")


def write_png(path, width=100, height=100):
    """Een echte PNG op `path`. QgsLayoutItemPicture weigert stilzwijgend een pad dat geen
    afbeelding is, dus een aangeraakt leeg bestand levert een lege pagina in plaats van een fout."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(30, 80, 160))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def report_meta():
    """De `report.meta` die een layout verwacht: alles wat op het titelblad en in de voettekst
    terechtkomt. Hier en niet in twee testbestanden, want twee kopieën van dezelfde dict drijven
    uit elkaar zodra er een sleutel bijkomt."""
    return {"project": "Testproject", "project_number": "T-001", "author": "A. Tester",
            "company": "Testbureau", "address": "Kortrijksesteenweg 100", "municipality": "Gent",
            "zone_name": "Gent test", "created_at": "2026-09-15T10:00:00",
            "disclaimer": "<p>Geen interpretatie.</p>", "logo_path": ""}


class Click:
    """Wat een DrawTool van een canvas-event leest: de knop en de pixel."""

    def __init__(self, button, pos):
        self._button, self._pos = button, pos

    def button(self):
        return self._button

    def pos(self):
        return self._pos


class FakeIface:
    """What the runner and the dialog use of `iface`: a real message bar and a real canvas,
    offscreen. `pushed` records (level, text, item) for every message the bar received."""

    def __init__(self):
        from qgis.gui import QgsMapCanvas, QgsMessageBar

        self.bar = QgsMessageBar()
        self.canvas = QgsMapCanvas()
        self.pushed = []
        self.bar.widgetAdded.connect(self._record)

    def _record(self, widget):
        # An item the bar made itself (pushMessage) arrives as a bare QWidget; cast it back. An
        # exception in a slot would abort the process under pytest (PyQt calls qFatal).
        from qgis.gui import QgsMessageBarItem
        from qgis.PyQt import sip

        item = sip.cast(widget, QgsMessageBarItem)
        self.pushed.append((item.level(), item.text(), item))

    def messageBar(self):
        return self.bar

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return None


@pytest.fixture(scope="session")
def qgs_app():
    """One standalone QgsApplication for the whole session: initQgis() loads the providers
    (memory, wms, wcs, ogr) that every layer test needs.

    GUI-enabled (`QgsApplication([], True)`) although nothing here shows a window: rendering a
    layout goes through the QApplication machinery behind fonts, pixmaps and SVG, which a GUI-less
    QgsApplication (a QCoreApplication) does not have. The offscreen platform keeps it headless.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    app = QgsApplication([], True)
    app.initQgis()
    yield app
    app.exitQgis()


@pytest.fixture
def project(qgs_app):
    """A throwaway QgsProject, one per test.

    This is about destruction ORDER, not about leaks. A project owns its layers, and a layout
    keeps a raw pointer to the project it was built for, so the project has to outlive both. Left
    to Python that order is not guaranteed: a QgsProject a fixture still holds is released during
    fixture finalisation, and on Windows (QGIS 3.40.15) the destructor then lands in freed memory.
    The process dies with an access violation *after* every test already reported PASSED - the run
    reads green and still exits non-zero. `deleteLater()` hands the object to Qt, which frees it
    once nothing is using it any more. A project created inside a test body and dropped there is
    safe; one that a fixture outlives is not.
    """
    from qgis.core import QgsProject

    instance = QgsProject()
    yield instance
    instance.deleteLater()


@pytest.fixture
def gent_zone():
    """The fixed test location: a 50 m circle around Gent (X 104326, Y 192506)."""
    from desktopstudie.core import geometry
    from desktopstudie.core.model import StudyZone

    return StudyZone(ring=geometry.buffer_point(104326.0, 192506.0, 50.0), name="Gent test",
                     radius_m=500.0, address="Kortrijksesteenweg 100, 9000 Gent")
