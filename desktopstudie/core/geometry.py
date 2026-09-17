"""Pure planar geometry on tuples, in metres (EPSG:31370). Rings are lists of (x, y)
without a repeated closing vertex."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

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
    # Shift to a local origin before accumulating: at Lambert-72 scale (coordinates ~1e5) the
    # shoelace terms otherwise subtract two large near-equal numbers and lose precision for a
    # thin ring, e.g. a sliver where the vertices agree to 6+ significant digits.
    ox, oy = ring[0]
    a = 0.0
    cx = cy = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i][0] - ox, ring[i][1] - oy
        x2, y2 = ring[(i + 1) % len(ring)][0] - ox, ring[(i + 1) % len(ring)][1] - oy
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:  # degenerate: mean of vertices
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    a *= 0.5
    return (cx / (6.0 * a) + ox, cy / (6.0 * a) + oy)


def bbox(ring: Sequence[Point]) -> BBox:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


# Reserved for the QGIS shell (plan 2): the map pages pad the zone bbox before setting an extent.
def expand_bbox(b: BBox, margin: float) -> BBox:
    return (b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin)


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def polygon_wkt(ring: Sequence[Point]) -> str:
    pts = list(ring) + [ring[0]]
    return "POLYGON((" + ",".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts) + "))"


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


def interpolate(along: float, xs: Sequence[float], ys: Sequence[Optional[float]]) -> float:
    """Linear interpolation of `ys` over `xs` (both in sampling order, xs ascending), holding the
    first and last value flat outside the sampled range. Samples whose y is None are dropped, so
    a gap is bridged rather than turned into a hole; 0.0 when no sample has a value at all."""
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if not pts:
        return 0.0
    if along <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= along <= x1:
            return y0 + (y1 - y0) * (along - x0) / (x1 - x0) if x1 > x0 else y0
    return pts[-1][1]


def project_onto_line(pt: Point, p: Point, q: Point) -> Tuple[float, float]:
    """Return (distance along the line from p, signed perpendicular offset; positive = left of p->q)."""
    length = distance(p, q)
    if length == 0.0:
        return 0.0, distance(pt, p)
    ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
    dx, dy = pt[0] - p[0], pt[1] - p[1]
    return dx * ux + dy * uy, dy * ux - dx * uy


def chainages(line: Tuple[Point, Point], points: Sequence[Point]) -> List[float]:
    """Distance along `line` for each point, from its real position - not its index - so samples
    that are missing or irregularly spaced still line up with everything else measured along the
    line (projected investigations, profile columns)."""
    p, q = line
    return [project_onto_line(pt, p, q)[0] for pt in points]


def point_in_ring(x: float, y: float, ring: Sequence[Point]) -> bool:
    """Points exactly on an edge are classified side-dependently (PNPOLY behaviour); regardless,
    distance_to_ring returns 0 for them."""
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


def representative_point(ring: Sequence[Point]) -> Point:
    """A point guaranteed to lie inside the ring, unlike centroid() for a non-convex ring (e.g.
    an L-shape) where the plain area centroid can fall in the notch outside the shape. Returns
    centroid(ring) when that already lies inside; otherwise the midpoint of the widest horizontal
    chord through the ring at the centroid's y."""
    cx, cy = centroid(ring)
    if point_in_ring(cx, cy, ring):
        return (cx, cy)
    n = len(ring)
    crossings = []
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > cy) != (y2 > cy):
            crossings.append(x1 + (cy - y1) * (x2 - x1) / (y2 - y1))
    if not crossings:  # degenerate: no edge crosses the centroid's y
        return (cx, cy)
    crossings.sort()
    best_lo, best_hi, best_width = crossings[0], crossings[0], -1.0
    for i in range(0, len(crossings) - 1, 2):
        lo, hi = crossings[i], crossings[i + 1]
        if hi - lo > best_width:
            best_lo, best_hi, best_width = lo, hi, hi - lo
    return ((best_lo + best_hi) / 2.0, cy)


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


def vertices(geojson) -> List[Point]:
    """Every (x, y) in a GeoJSON geometry, whatever its nesting depth.

    A contour layer answers with LineStrings and a soil map with Polygons; the distance to either
    is measured against the same flat list of corners, so nothing here needs to know which it got.
    """
    found: List[Point] = []
    stack = [(geojson or {}).get("coordinates") or []]
    while stack:
        item = stack.pop()
        if not item:
            continue
        if isinstance(item[0], (int, float)):
            found.append((float(item[0]), float(item[1])))
        else:
            stack.extend(item)
    return found


def distance_to_geometry(geojson, ring: Sequence[Point]) -> Optional[float]:
    """How far the nearest corner of `geojson` lies from `ring`, or None for an empty geometry.

    Corner to ring, not edge to edge: a contour is sampled every few metres, so the nearest corner
    is within that of the true distance - and the number is printed to the metre in a table about
    kilometres.
    """
    points = vertices(geojson)
    if not points:
        return None
    return min(distance_to_ring(point, ring) for point in points)
