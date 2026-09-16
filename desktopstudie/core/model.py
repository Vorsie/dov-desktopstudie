"""Domain dataclasses. Depths: '_m' = metres below surface (positive down); '_mtaw' = elevation."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import geometry

Point = geometry.Point


@dataclass
class StudyZone:
    ring: List[Point]
    name: str
    radius_m: float = 500.0
    section_line: Optional[Tuple[Point, Point]] = None
    address: Optional[str] = None

    @property
    def centroid(self) -> Point:
        return geometry.centroid(self.ring)

    @property
    def bbox(self) -> geometry.BBox:
        return geometry.bbox(self.ring)

    @property
    def wkt(self) -> str:
        return geometry.polygon_wkt(self.ring)

    @property
    def area_m2(self) -> float:
        return geometry.area(self.ring)

    @property
    def representative_point(self) -> Point:
        return geometry.representative_point(self.ring)

    @classmethod
    def around_point(cls, x: float, y: float, buffer_m: float, radius_m: float,
                     address: Optional[str] = None) -> StudyZone:
        """The circular zone of `buffer_m` around a point, named after the address when there is
        one and after the coordinate otherwise. The one constructor behind the plugin's address and
        X/Y modes and the scripts' --adres and --x/--y."""
        return cls(ring=geometry.buffer_point(x, y, buffer_m), name=address or point_name(x, y),
                   radius_m=radius_m, address=address)


def point_name(x: float, y: float) -> str:
    """A coordinate as a name, to the metre: "104326/192506"."""
    return f"{x:.0f}/{y:.0f}"


def now_iso() -> str:
    """The moment a source was consulted, to the second, with the local offset.

    One spelling for the whole project: the orchestrator stamps its own sources with it and the
    shell stamps the ones only it can reach (the DTM, the WMS layers, the legends), and a report
    must not mix two notations of the same clock.
    """
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


@dataclass
class Provenance:
    source: str
    url: str
    retrieved_at: str
    ok: bool = True
    message: str = ""


@dataclass
class CptProfile:
    depth_m: List[float]
    qc_mpa: List[Optional[float]]
    fs_kpa: List[Optional[float]]
    u_kpa: List[Optional[float]]


@dataclass
class Cpt:
    permkey: str
    number: str
    x: float
    y: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]
    date: Optional[str]
    method: Optional[str]
    cone: Optional[str]
    contractor: Optional[str]
    project: Optional[str]
    url: str
    distance_m: float
    profile: Optional[CptProfile] = None


@dataclass
class LithologyLayer:
    top_m: float
    base_m: float
    description: str
    kind: str = "beschrijving"  # or "gecodeerd"
    raw: Dict[str, Any] = field(default_factory=dict)  # coded layers: hoofdnaam/kleur/bijmenging tokens


@dataclass
class Borehole:
    permkey: str
    number: str
    x: float
    y: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]
    date: Optional[str]
    method: Optional[str]
    purpose: Optional[str]
    contractor: Optional[str]
    url: str
    distance_m: float
    interpretation_url: Optional[str] = None
    lithology: List[LithologyLayer] = field(default_factory=list)


@dataclass
class GwLevel:
    date: str
    level_mtaw: float
    method: Optional[str] = None
    reliability: Optional[str] = None


@dataclass
class GwFilter:
    gw_id: str
    filter_no: str
    x: float
    y: float
    z_mtaw: Optional[float]
    aquifer: Optional[str]
    filter_base_m: Optional[float]
    filter_length_m: Optional[float]
    network: Optional[str]
    url: str
    report_url: Optional[str]
    distance_m: float
    levels_from: Optional[str] = None
    levels_to: Optional[str] = None
    latest: Optional[GwLevel] = None

    @property
    def latest_depth_m(self) -> Optional[float]:
        if self.latest is None or self.z_mtaw is None:
            return None
        return self.z_mtaw - self.latest.level_mtaw


@dataclass
class VbLayer:
    code: str
    name: str
    top_mtaw: float
    base_mtaw: float
    thickness_m: float
    color: str
    texture: str


@dataclass
class VirtualBorehole:
    x: float
    y: float
    model: str
    layers: List[VbLayer]

    @property
    def surface_mtaw(self) -> Optional[float]:
        return self.layers[0].top_mtaw if self.layers else None

    def depth_of(self, layer: VbLayer) -> Tuple[float, float]:
        surface = self.surface_mtaw if self.surface_mtaw is not None else 0.0
        return surface - layer.top_mtaw, surface - layer.base_mtaw


@dataclass
class ProjectedPoint:
    kind: str  # "cpt" | "boring" | "peilput"
    label: str
    along_m: float
    offset_m: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]


@dataclass
class ProfileColumn:
    """One distance step of the DOV profile query: the layers stacked from `surface_mtaw` down."""
    along_m: float
    surface_mtaw: float
    layers: List[VbLayer]


@dataclass
class SectionProfile:
    """The whole line sampled at `resolution_m` intervals by the DOV profile endpoint; far denser
    than the handful of doorprik anchors, which stay in `Section.boreholes`."""
    model: str
    resolution_m: float
    columns: List[ProfileColumn]


@dataclass
class Section:
    line: Tuple[Point, Point]
    boreholes: List[VirtualBorehole]
    projected: List[ProjectedPoint]
    zone_from_m: float
    zone_to_m: float
    failed_points: int = 0
    profile: Optional[SectionProfile] = None


@dataclass
class MapFact:
    map_id: str
    title: str
    rows: List[Dict[str, Any]]


@dataclass
class Signalering:
    code: str
    fact: str
    source: str
    advice: str
    severity: str = "aandacht"  # "info" | "aandacht"


@dataclass
class StudyResult:
    zone: StudyZone
    created_at: str
    municipality: Optional[str] = None
    cpts: List[Cpt] = field(default_factory=list)
    boreholes: List[Borehole] = field(default_factory=list)
    gw_filters: List[GwFilter] = field(default_factory=list)
    virtual_boreholes: Dict[str, VirtualBorehole] = field(default_factory=dict)
    section: Optional[Section] = None
    map_facts: List[MapFact] = field(default_factory=list)
    signaleringen: List[Signalering] = field(default_factory=list)
    provenance: List[Provenance] = field(default_factory=list)
    figures: Dict[str, str] = field(default_factory=dict)
    relief: Optional[Tuple[float, float, float]] = None  # (min, max, mean) mTAW, filled by the shell
    # Which catalogue maps this study covers, straight from the dialog's checklist; None means
    # every enabled entry. It travels with the result rather than staying in the Settings because
    # the shell reads it for its layers, legends and map images - and because a reader of
    # studie.json has to be able to see which maps the study did NOT look at.
    map_ids: Optional[List[str]] = None

    def summary(self) -> Dict[str, Any]:
        return {
            "n_cpts": len(self.cpts),
            "n_boreholes": len(self.boreholes),
            "n_gw_filters": len(self.gw_filters),
            "n_signaleringen": len(self.signaleringen),
            "n_sources_failed": sum(1 for p in self.provenance if not p.ok),
        }

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data["summary"] = self.summary()
        return data

    def write_json(self, path: Path) -> None:
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent=1, default=_jsonable)
        Path(path).write_text(text, encoding="utf-8")


def _jsonable(value: Any) -> Any:
    """json.dumps(default=...) hook: paths become their string form, numpy scalars and arrays
    (which carry a .tolist() but are not one of json's native types) unwrap to plain Python."""
    if isinstance(value, pathlib.PurePath):
        return str(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")
