"""De teken-tools: linksklik voegt een hoekpunt toe, de band volgt de muis vanaf het laatste
hoekpunt, rechtsklik sluit af en levert de punten in het CRS van het canvas; daarna is de band leeg.
Offscreen, met een echt QgsMapCanvas en nagebootste klikken."""
from __future__ import annotations

import pytest


class _Click:
    def __init__(self, button, pos):
        self._button, self._pos = button, pos

    def button(self):
        return self._button

    def pos(self):
        return self._pos


def _canvas():
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle
    from qgis.gui import QgsMapCanvas

    canvas = QgsMapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    canvas.setExtent(QgsRectangle(3.70, 51.02, 3.74, 51.06))
    return canvas


def test_left_clicks_collect_vertices_and_a_right_click_hands_them_over_in_canvas_coordinates(qgs_app):
    from qgis.PyQt.QtCore import QPoint, Qt

    from desktopstudie.qgis import map_tools

    canvas = _canvas()
    got = []
    tool = map_tools.polygon_tool(canvas, got.append)
    canvas.setMapTool(tool)
    pixels = [QPoint(100, 100), QPoint(300, 100), QPoint(200, 300)]
    expected = [canvas.getCoordinateTransform().toMapCoordinates(pixel) for pixel in pixels]

    for pixel in pixels:
        tool.canvasReleaseEvent(_Click(Qt.MouseButton.LeftButton, pixel))
    assert len(tool.points) == 3
    assert tool.band.numberOfVertices() == 4, "drie hoekpunten en het punt dat de muis volgt"
    tool.canvasReleaseEvent(_Click(Qt.MouseButton.RightButton, QPoint(0, 0)))

    assert len(got) == 1 and len(got[0]) == 3
    for point, wanted in zip(got[0], expected):
        assert point == pytest.approx((wanted.x(), wanted.y()))
    assert all(3.70 < x < 3.74 and 51.02 < y < 51.06 for x, y in got[0]), "in het CRS van het canvas"
    assert tool.points == [] and tool.band.numberOfVertices() == 0


def test_the_band_follows_the_mouse_and_deactivating_clears_it(qgs_app):
    from qgis.PyQt.QtCore import QPoint, Qt

    from desktopstudie.qgis import map_tools

    canvas = _canvas()
    tool = map_tools.line_tool(canvas, lambda points: None)
    canvas.setMapTool(tool)

    tool.canvasMoveEvent(_Click(None, QPoint(50, 50)))  # before any click: nothing to drag
    assert tool.band.numberOfVertices() == 0
    tool.canvasReleaseEvent(_Click(Qt.MouseButton.LeftButton, QPoint(100, 100)))
    tool.canvasMoveEvent(_Click(None, QPoint(300, 300)))
    assert tool.band.numberOfVertices() == 2
    dragged = tool.band.getPoint(0, 1)
    assert dragged == canvas.getCoordinateTransform().toMapCoordinates(QPoint(300, 300))

    canvas.unsetMapTool(tool)

    assert tool.band.numberOfVertices() == 0 and tool.points == []
