# tests/core/test_geometry.py
from __future__ import annotations

import math

import pytest

from desktopstudie.core import geometry as g


def test_buffer_point_makes_closed_circle_of_requested_radius():
    ring = g.buffer_point(100.0, 200.0, 50.0, n=8)
    assert len(ring) == 8
    for x, y in ring:
        assert math.isclose(math.hypot(x - 100.0, y - 200.0), 50.0, abs_tol=1e-9)


def test_area_and_centroid_of_square(gent_ring):
    assert math.isclose(g.area(gent_ring), 200.0 * 200.0)
    assert g.centroid(gent_ring) == pytest.approx((104326.0, 192506.0))


def test_bbox_and_expand(gent_ring):
    assert g.bbox(gent_ring) == (104226.0, 192406.0, 104426.0, 192606.0)
    assert g.expand_bbox((0, 0, 10, 10), 5) == (-5, -5, 15, 15)


def test_polygon_wkt_closes_the_ring(gent_ring):
    wkt = g.polygon_wkt(gent_ring)
    assert wkt.startswith("POLYGON((104226 192406,")
    assert wkt.endswith("104226 192406))")


def test_longest_axis_of_rectangle_is_a_diagonal():
    ring = [(0.0, 0.0), (100.0, 0.0), (100.0, 20.0), (0.0, 20.0)]
    p, q = g.longest_axis(ring)
    assert math.isclose(g.distance(p, q), math.hypot(100.0, 20.0))


def test_extend_line_adds_distance_on_both_ends():
    p, q = g.extend_line((0.0, 0.0), (10.0, 0.0), 5.0)
    assert p == pytest.approx((-5.0, 0.0))
    assert q == pytest.approx((15.0, 0.0))


def test_sample_line_is_inclusive_and_evenly_spaced():
    pts = g.sample_line((0.0, 0.0), (10.0, 0.0), 6)
    assert pts[0] == (0.0, 0.0) and pts[-1] == (10.0, 0.0)
    assert [round(x, 6) for x, _ in pts] == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]


def test_project_onto_line_gives_distance_along_and_signed_offset():
    along, offset = g.project_onto_line((5.0, 3.0), (0.0, 0.0), (10.0, 0.0))
    assert along == pytest.approx(5.0)
    assert offset == pytest.approx(3.0)


def test_point_in_ring_and_distance_to_ring(gent_ring):
    assert g.point_in_ring(104326.0, 192506.0, gent_ring)
    assert not g.point_in_ring(0.0, 0.0, gent_ring)
    assert g.distance_to_ring((104326.0, 192506.0), gent_ring) == 0.0
    assert g.distance_to_ring((104526.0, 192506.0), gent_ring) == pytest.approx(100.0)
