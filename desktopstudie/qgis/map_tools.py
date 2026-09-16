"""Draw a polygon or a line on the canvas: left click adds a vertex, right click finishes.

The tool hands back plain (x, y) tuples in the CANVAS CRS and nothing else; turning them into a
zone or a section line in Lambert 72 is `zone_input`'s job, and deciding what to do with them is
the dialog's. The rubber band follows the mouse from the last clicked vertex, so the user sees the
edge that a click is about to fix.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

from qgis.core import Qgis, QgsPointXY
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

BAND_COLOR = QColor(255, 0, 0, 120)
BAND_WIDTH = 2
OnDone = Callable[[List[Tuple[float, float]]], None]


class DrawTool(QgsMapTool):
    """Collect vertices on the canvas until a right click; then hand them to `on_done`."""

    def __init__(self, canvas, geometry_type, on_done: OnDone):
        super().__init__(canvas)
        self.on_done = on_done
        self.geometry_type = geometry_type
        self.band = QgsRubberBand(canvas, geometry_type)
        self.band.setColor(BAND_COLOR)
        self.band.setWidth(BAND_WIDTH)
        self.points: List[QgsPointXY] = []
        self.setCursor(Qt.CursorShape.CrossCursor)

    def canvasReleaseEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        if event.button() == Qt.MouseButton.RightButton:
            points = [(point.x(), point.y()) for point in self.points]
            self.clear()
            self.on_done(points)
            return
        point = self.toMapCoordinates(event.pos())
        if self.points:
            self.band.movePoint(point)  # pin the vertex the mouse was dragging
        else:
            self.band.addPoint(point)
        self.band.addPoint(point)  # and a new one to follow the mouse
        self.points.append(point)

    def canvasMoveEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        if self.points:
            self.band.movePoint(self.toMapCoordinates(event.pos()))

    def clear(self) -> None:
        self.band.reset(self.geometry_type)
        self.points = []

    def deactivate(self) -> None:
        self.clear()
        super().deactivate()


def polygon_tool(canvas, on_done: OnDone) -> DrawTool:
    return DrawTool(canvas, Qgis.GeometryType.Polygon, on_done)


def line_tool(canvas, on_done: OnDone) -> DrawTool:
    return DrawTool(canvas, Qgis.GeometryType.Line, on_done)
