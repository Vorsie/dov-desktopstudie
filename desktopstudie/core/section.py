"""Cross-section along a line: virtual boreholes at sampled points plus investigations
projected onto the line when they lie within the corridor."""
from __future__ import annotations

from typing import List, Sequence, Tuple

from . import geometry
from .model import Borehole, Cpt, GwFilter, Point, ProjectedPoint, Section, StudyZone
from .services.virtuele_boring import fetch_virtual_borehole


def section_line(zone: StudyZone, extension_m: float) -> Tuple[Point, Point]:
    if zone.section_line is not None:
        return zone.section_line
    p, q = geometry.longest_axis(zone.ring)
    return geometry.extend_line(p, q, extension_m)


def _project(kind: str, label: str, x: float, y: float, z: float, depth: float,
             line: Tuple[Point, Point]) -> ProjectedPoint:
    along, offset = geometry.project_onto_line((x, y), line[0], line[1])
    return ProjectedPoint(kind=kind, label=label, along_m=along, offset_m=offset, z_mtaw=z, depth_m=depth)


def build_section(client, zone: StudyZone, cpts: Sequence[Cpt], boreholes: Sequence[Borehole],
                  filters: Sequence[GwFilter], n_points: int, corridor_m: float, model: str) -> Section:
    line = section_line(zone, extension_m=100.0)  # returns the user's line untouched when it is set
    length = geometry.distance(line[0], line[1])
    points = geometry.sample_line(line[0], line[1], n_points)
    vbs = [fetch_virtual_borehole(client, x, y, model) for x, y in points]
    projected: List[ProjectedPoint] = []
    for c in cpts:
        projected.append(_project("cpt", c.number, c.x, c.y, c.z_mtaw, c.depth_m, line))
    for b in boreholes:
        projected.append(_project("boring", b.number, b.x, b.y, b.z_mtaw, b.depth_m, line))
    for f in filters:
        projected.append(_project("peilput", f"{f.gw_id}/{f.filter_no}", f.x, f.y, f.z_mtaw, f.filter_base_m, line))
    projected = [p for p in projected if abs(p.offset_m) <= corridor_m and 0.0 <= p.along_m <= length]
    alongs = [geometry.project_onto_line(v, line[0], line[1])[0] for v in zone.ring]
    return Section(line=line, boreholes=vbs, projected=projected, zone_from_m=min(alongs), zone_to_m=max(alongs))
