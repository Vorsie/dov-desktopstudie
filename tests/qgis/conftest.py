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


def pdf_pages(path):
    """Het aantal pagina's in een PDF. Elke pagina is een object met /Type /Page; de paginaboom
    zelf draagt /Type /Pages en die telt niet mee. Hier, want de exporttests en de pijplijntests
    stellen allebei dezelfde vraag aan hetzelfde bestand."""
    data = path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def rings_close(ring, other, tolerance):
    """Of twee ringen punt voor punt binnen `tolerance` samenvallen.

    Een ring die door een coordinaattransformatie is geweest komt nooit exact terug, dus wordt er
    op afstand vergeleken - in de dialoogtests en in de zone-invoertests op dezelfde manier.
    """
    return len(ring) == len(other) and all(
        abs(a[0] - b[0]) < tolerance and abs(a[1] - b[1]) < tolerance for a, b in zip(ring, other))


def report_of(pages):
    """Een rapportboom van een hoofdstuk met deze pagina's erin - genoeg om een layout te bouwen
    of een reeks kaartbeelden uit te plannen, en wat beide testmodules ervoor nodig hebben."""
    from desktopstudie.core.report_content import Chapter, Report

    return Report(title="Desktopstudie testproject", meta={}, chapters=[Chapter(1, "Test", pages)])


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

# --- pictures the shell has to read: what a service actually hands over -----------------------
# Built here rather than in one test module, because the raster tests, the prefetch tests and
# the layout tests all need the same shapes: a legend with gaps in it, a colour bar, a drawing
# with a header on it, a tile with something on it and a tile with nothing on it.

def striped_png(path, width=200, blocks=100, block_h=30, gap_h=6):
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


def profile_drawing(path, width=980, header_h=103, gap_h=14, body_h=586):
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


def solid_png(path, width=64, height=64, rgba=(255, 255, 255, 0)):
    """Een tegel zonder tekening: één kleur, of volledig doorzichtig."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(*rgba))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def drawn_png(path, width=64, height=64):
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


def tile(colour, size=40, alpha=255):
    """Een GetMap-antwoord: een effen tegel, desnoods volledig doorzichtig."""
    from qgis.PyQt.QtCore import QBuffer, QByteArray
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(*colour, alpha))
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(store)


def inset_legend(path, margin=1):
    """De GxG-legenda: een kleurloop met een witte rand van een pixel ernaast, met de labels
    rechts (live 2026-09-17: 38 x 272 px, band van x=1 tot x=20)."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(38, 100, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    for y in range(1, 99):
        share = (y - 1) / 97.0
        colour = QColor(int(240 - 220 * share), int(250 - 230 * share), 255)
        for x in range(margin, margin + 20):
            image.setPixelColor(x, y, colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def dhmv_legend(path):
    """Een GetLegendGraphic zoals de DHMV-dienst hem levert: een titelregel, daaronder een
    verticale kleurverloop-balk van 16 px breed met het bereik ernaast (live 2026-09-17)."""
    from qgis.PyQt.QtGui import QColor, QImage

    image = QImage(102, 68, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    for x in range(20, 90):  # de titeltekst
        image.setPixelColor(x, 6, QColor(0, 0, 0))
    for y in range(18, 66):  # de kleurbalk zelf: bruin bovenaan, groen onderaan
        share = (y - 18) / 47.0
        colour = QColor(int(184 - 140 * share), int(79 + 131 * share), int(22 + 118 * share))
        for x in range(16):
            image.setPixelColor(x, y, colour)
    for x in range(40, 80):  # het bereik "300 - -50" naast de balk
        image.setPixelColor(x, 40, QColor(0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return path


def pixels(path):
    from qgis.PyQt.QtGui import QImage

    image = QImage(str(path))
    assert not image.isNull()
    return image
