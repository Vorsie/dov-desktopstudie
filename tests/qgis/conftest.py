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
