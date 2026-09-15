"""Small shims so the shell runs on QGIS 3.34 (PyQt5) through 4.x (PyQt6).

Everything the shell places on a layout is measured in millimetres, so the layout unit is
resolved once, here, in its scoped form (`Qgis.LayoutUnit.Millimeters` exists in 3.34 and is
the only spelling Qt6 accepts; the unscoped `QgsUnitTypes.LayoutMillimeters` is deprecated).
"""
from __future__ import annotations

from qgis.core import Qgis, QgsLayoutPoint, QgsLayoutSize

MM = Qgis.LayoutUnit.Millimeters


def point_mm(x: float, y: float) -> QgsLayoutPoint:
    """A layout position in millimetres."""
    return QgsLayoutPoint(x, y, MM)


def size_mm(width: float, height: float) -> QgsLayoutSize:
    """A layout size in millimetres."""
    return QgsLayoutSize(width, height, MM)


def qgis_version() -> str:
    """The running QGIS version, e.g. "3.40.15-Bratislava"."""
    return Qgis.QGIS_VERSION
