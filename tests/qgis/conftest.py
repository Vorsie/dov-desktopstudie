"""QGIS shell tests: they run only in a Python that has qgis (python-qgis-ltr.bat or the
Docker images). In the plain dev venv the importorskip below skips this whole directory,
so `pytest tests` stays green there."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("qgis.core")


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
def gent_zone():
    """The fixed test location: a 50 m circle around Gent (X 104326, Y 192506)."""
    from desktopstudie.core import geometry
    from desktopstudie.core.model import StudyZone

    return StudyZone(ring=geometry.buffer_point(104326.0, 192506.0, 50.0), name="Gent test",
                     radius_m=500.0, address="Kortrijksesteenweg 100, 9000 Gent")
