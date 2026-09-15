"""Cross-section along a line: virtual boreholes at sampled points plus investigations
projected onto the line when they lie within the corridor."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Sequence, Tuple

from . import geometry
from .logging_util import Log
from .model import Borehole, Cpt, GwFilter, Point, ProjectedPoint, Section, StudyZone, VirtualBorehole
from .services.virtuele_boring import fetch_virtual_borehole


def section_line(zone: StudyZone, extension_m: float) -> Tuple[Point, Point]:
    if zone.section_line is not None:
        return zone.section_line
    p, q = geometry.longest_axis(zone.ring)
    return geometry.extend_line(p, q, extension_m)


def _project(kind: str, label: str, x: float, y: float, z: Optional[float], depth: Optional[float],
             line: Tuple[Point, Point]) -> ProjectedPoint:
    along, offset = geometry.project_onto_line((x, y), line[0], line[1])
    return ProjectedPoint(kind=kind, label=label, along_m=along, offset_m=offset, z_mtaw=z, depth_m=depth)


def _fetch_points(client, points: Sequence[Point], model: str, max_workers: int,
                  log: Optional[Log]) -> Tuple[List[VirtualBorehole], int]:
    """Fetch one doorprik per point in parallel; a failing point is skipped and counted rather
    than aborting the whole section. Order of the returned boreholes follows `points`, not the
    order in which the threads finished."""
    results: List[Optional[VirtualBorehole]] = [None] * len(points)
    failed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {pool.submit(fetch_virtual_borehole, client, x, y, model): i
                           for i, (x, y) in enumerate(points)}
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                results[i] = future.result()
            except Exception as exc:  # isolate: one bad point must not kill the whole section
                failed += 1
                x, y = points[i]
                if log:
                    log.warning(f"virtuele boring op {x:.0f}/{y:.0f} mislukt: {type(exc).__name__}: {exc}")
    return [vb for vb in results if vb is not None], failed


def build_section(client, line: Tuple[Point, Point], zone: StudyZone, cpts: Sequence[Cpt],
                  boreholes: Sequence[Borehole], filters: Sequence[GwFilter], n_points: int,
                  corridor_m: float, model: str, log: Optional[Log] = None, max_workers: int = 4) -> Section:
    length = geometry.distance(line[0], line[1])
    points = geometry.sample_line(line[0], line[1], n_points)
    vbs, failed = _fetch_points(client, points, model, max_workers, log)
    if not vbs:
        raise RuntimeError("geen enkele virtuele boring langs de doorsnedelijn beschikbaar")
    projected: List[ProjectedPoint] = []
    for c in cpts:
        projected.append(_project("cpt", c.number, c.x, c.y, c.z_mtaw, c.depth_m, line))
    for b in boreholes:
        projected.append(_project("boring", b.number, b.x, b.y, b.z_mtaw, b.depth_m, line))
    for f in filters:
        projected.append(_project("peilput", f"{f.gw_id}/{f.filter_no}", f.x, f.y, f.z_mtaw, f.filter_base_m, line))
    projected = [p for p in projected if abs(p.offset_m) <= corridor_m and 0.0 <= p.along_m <= length]
    # A linear functional (the along-line projection) attains its extrema over a polygon at a
    # vertex - exactly, even for a concave ring - so min/max over the ring's vertices gives the
    # true along-line extent of the zone; only the zone's *contiguity* along the line (nothing
    # in between the extrema falls outside it) is approximated.
    alongs = [geometry.project_onto_line(v, line[0], line[1])[0] for v in zone.ring]
    zone_from_m = min(max(min(alongs), 0.0), length)
    zone_to_m = min(max(max(alongs), 0.0), length)
    return Section(line=line, boreholes=vbs, projected=projected, zone_from_m=zone_from_m,
                   zone_to_m=zone_to_m, failed_points=failed)
