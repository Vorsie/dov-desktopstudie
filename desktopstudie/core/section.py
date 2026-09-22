"""Cross-section along a line: a handful of doorprik anchors at sampled points, the dense DOV
profile query stacked on the modelled surface (its own datum, with the anchors as fallback), plus
investigations projected onto the line when they lie within the corridor."""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from . import geometry, parallel
from .logging_util import Log
from .model import (
    Borehole,
    Cpt,
    GwFilter,
    Point,
    ProjectedPoint,
    Section,
    SectionProfile,
    StudyZone,
    VirtualBorehole,
)
from .services.virtuele_boring import (
    fetch_profile,
    fetch_virtual_borehole,
    parse_profile,
    profile_surface_at,
)

# One profile column per 1/40th of the line, but never finer than 5 m: enough columns to read
# as a continuous section without asking DOV for thousands of samples on a long line.
MIN_PROFILE_RESOLUTION_M = 5.0
PROFILE_COLUMNS = 40


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
                  log: Optional[Log],
                  should_cancel: Optional[Callable[[], bool]]) -> Tuple[List[VirtualBorehole], int]:
    """Fetch one doorprik per point in parallel; a failing point is skipped and counted rather
    than aborting the whole section. Order of the returned boreholes follows `points`, not the
    order in which the threads finished: the anchors are read by chainage further down.

    This is the longest run of network calls the section phase makes, so it is also where a
    cancel has to be heard - `load_each` polls between items.
    """
    results: List[Optional[VirtualBorehole]] = [None] * len(points)

    def fetch(item) -> None:
        index, (x, y) = item
        results[index] = fetch_virtual_borehole(client, x, y, model)

    failed = parallel.load_each(
        list(enumerate(points)), fetch,
        lambda item: f"virtuele boring op {item[1][0]:.0f}/{item[1][1]:.0f}",
        max_workers, log, should_cancel)
    return [vb for vb in results if vb is not None], failed


def _anchor_surface(line: Tuple[Point, Point], anchors: Sequence[VirtualBorehole]):
    """Fallback surface: linear interpolation between the doorprik anchors' own tops."""
    xs = geometry.chainages(line, [(vb.x, vb.y) for vb in anchors])
    surfaces = [vb.surface_mtaw for vb in anchors]

    def surface_at(along: float) -> float:
        return geometry.interpolate(along, xs, surfaces)

    return surface_at


def _build_profile(client, line: Tuple[Point, Point], anchors: Sequence[VirtualBorehole], model: str,
                   length: float, log: Optional[Log]) -> SectionProfile:
    """The dense profile, stacked from the top because the answer holds thicknesses only. Its own
    datum is preferred: it reproduces the doorprik surface exactly (see `profile_surface_at`) and,
    unlike a surface interpolated between anchors a hundred metres apart, it does not tilt the
    layer boundaries inside a G3Dv3 grid cell. The anchors give the stacking order and are the
    fallback surface for an answer without a datum; with no anchors at all the profile has to carry
    both itself, so the units stack on their numeric suffix and a missing datum is fatal."""
    resolution_m = max(MIN_PROFILE_RESOLUTION_M, length / PROFILE_COLUMNS)
    order = [layer.code for layer in anchors[0].layers] if anchors else []
    payload = fetch_profile(client, model, line[0], line[1], resolution_m, log=log)
    surface_at = profile_surface_at(payload, log=log)
    if surface_at is None:
        if not anchors:
            raise RuntimeError("profiel zonder eigen maaiveld-datum en geen doorprik-anker om op te hangen")
        if log:
            log.warning(f"profiel {model} zonder eigen maaiveld-datum; terugval op de doorprik-ankers")
        surface_at = _anchor_surface(line, anchors)
    return parse_profile(payload, model, order, surface_at, resolution_m, log=log)


def build_section(client, line: Tuple[Point, Point], zone: StudyZone, cpts: Sequence[Cpt],
                  boreholes: Sequence[Borehole], filters: Sequence[GwFilter], n_points: int,
                  corridor_m: float, model: str, log: Optional[Log] = None, max_workers: int = 4,
                  with_profile: bool = True,
                  should_cancel: Optional[Callable[[], bool]] = None) -> Section:
    length = geometry.distance(line[0], line[1])
    points = geometry.sample_line(line[0], line[1], n_points)
    vbs, failed = _fetch_points(client, points, model, max_workers, log, should_cancel)
    # The profile is tried even when every anchor failed: it carries both the layers and, through
    # its own datum, the elevations, so it alone is enough for a section. Only when both sources
    # are gone is there nothing left to draw.
    profile: Optional[SectionProfile] = None
    if with_profile:
        try:
            profile = _build_profile(client, line, vbs, model, length, log)
        except Exception as exc:  # isolate: without the profile the doorprik section is still valid
            if log:
                log.warning(f"profiel langs de doorsnedelijn niet beschikbaar: {type(exc).__name__}: {exc}")
    if not vbs and profile is None:
        raise RuntimeError("geen virtuele boring en geen profiel langs de doorsnedelijn beschikbaar")
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
                   zone_to_m=zone_to_m, failed_points=failed, profile=profile)
