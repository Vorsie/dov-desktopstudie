# desktopstudie/core/geometry.py
"""Pure planar geometry on tuples, in metres (EPSG:31370). Rings are lists of (x, y)
without a repeated closing vertex."""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]
Ring = List[Point]
BBox = Tuple[float, float, float, float]


def distance(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def buffer_point(x: float, y: float, radius: float, n: int = 64) -> Ring:
    return [(x + radius * math.cos(2 * math.pi * i / n), y + radius * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def area(ring: Sequence[Point]) -> float:
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def centroid(ring: Sequence[Point]) -> Point:
    a = 0.0
    cx = cy = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:  # degenerate: mean of vertices
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    a *= 0.5
    return (cx / (6.0 * a), cy / (6.0 * a))


def bbox(ring: Sequence[Point]) -> BBox:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def expand_bbox(b: BBox, margin: float) -> BBox:
    return (b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin)


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def polygon_wkt(ring: Sequence[Point]) -> str:
    pts = list(ring) + [ring[0]]
    return "POLYGON((" + ",".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts) + "))"


def line_wkt(p: Point, q: Point) -> str:
    return f"LINESTRING({_fmt(p[0])} {_fmt(p[1])},{_fmt(q[0])} {_fmt(q[1])})"


def longest_axis(ring: Sequence[Point]) -> Tuple[Point, Point]:
    best = (ring[0], ring[0])
    best_d = -1.0
    for i in range(len(ring)):
        for j in range(i + 1, len(ring)):
            d = distance(ring[i], ring[j])
            if d > best_d:
                best_d = d
                best = (ring[i], ring[j])
    return best


def extend_line(p: Point, q: Point, extension: float) -> Tuple[Point, Point]:
    length = distance(p, q)
    if length == 0.0:
        return p, q
    ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
    return (p[0] - ux * extension, p[1] - uy * extension), (q[0] + ux * extension, q[1] + uy * extension)


def sample_line(p: Point, q: Point, n: int) -> List[Point]:
    if n < 2:
        return [p]
    return [(p[0] + (q[0] - p[0]) * i / (n - 1), p[1] + (q[1] - p[1]) * i / (n - 1)) for i in range(n)]


def project_onto_line(pt: Point, p: Point, q: Point) -> Tuple[float, float]:
    """Return (distance along the line from p, signed perpendicular offset; positive = left of p->q)."""
    length = distance(p, q)
    if length == 0.0:
        return 0.0, distance(pt, p)
    ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
    dx, dy = pt[0] - p[0], pt[1] - p[1]
    return dx * ux + dy * uy, dy * ux - dx * uy


def point_in_ring(x: float, y: float, ring: Sequence[Point]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _distance_to_segment(pt: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    if seg == 0.0:
        return distance(pt, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return distance(pt, (ax + t * dx, ay + t * dy))


def distance_to_ring(pt: Point, ring: Sequence[Point]) -> float:
    """0 inside the polygon, otherwise the distance to the nearest edge."""
    if point_in_ring(pt[0], pt[1], ring):
        return 0.0
    return min(_distance_to_segment(pt, ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))
